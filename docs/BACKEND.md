# Backend: real-time job-posting pipeline

A small production-style backend beside the Shortlist dashboard, on the `feature/realtime-backend` branch. It polls 15 public Greenhouse job boards, stores postings idempotently in SQLite or ClickHouse, keeps skill and volume aggregates up to date as rows arrive, and streams them over a WebSocket to one dashboard page. The Shortlist pipeline (Kaggle CSVs, GNews, `data/jmsa.db`, pages 1–5) is unchanged and does not depend on any of it.

Everything under `backend/`, plus `docker-compose.yml`, `scripts/kill_restart_check.py`, `app/pages/6_Live_postings.py` and `tests/test_backend.py`.

## Architecture

```mermaid
flowchart LR
  GH["Greenhouse Job Board API<br/>15 boards (backend/boards.csv)"] -->|"HTTPS JSON<br/>retry + backoff"| W["backend.worker"]
  CA[("data/raw/greenhouse/<br/>response cache")] -.->|"--source cache"| W
  FX[("tests/fixtures/greenhouse/<br/>SYNTHETIC fixture")] -.->|"--source fixture"| W
  W -->|"new keys only,<br/>then board checkpoint"| ST{"BACKEND_STORE"}
  ST --> SQ[("SQLite data/backend.db<br/>postings, runs, checkpoints,<br/>aggregates in the same transaction")]
  ST --> CH[("ClickHouse jmsa<br/>postings, run_events, checkpoints")]
  CH -->|"materialized views"| AG[("volume_daily<br/>skill_daily")]
  GEN["backend.generate<br/>seeded SYNTHETIC rows"] --> SY[("synthetic_postings")]
  SY -->|"materialized views"| SAG[("synthetic_volume_daily<br/>synthetic_skill_daily")]
  SQ --> API["backend.api (FastAPI)<br/>one poller per dataset"]
  AG --> API
  SAG --> API
  API -->|"WS /ws/aggregates"| UI["Streamlit: Live postings page<br/>(WebSocket in the browser)"]
  KG["Kaggle CSVs + GNews"] --> PIPE["ingest/ + process/"] --> JDB[("data/jmsa.db")] --> SL["Shortlist pages 1-5"]
```

## Setup and commands

Git Bash, from the repo root.

```bash
source .venv/Scripts/activate
pip install -r requirements-backend.txt        # fastapi, uvicorn, clickhouse-connect, numpy

# 1. Ingest (SQLite, no Docker needed)
python -m backend.worker                        # one pass over the 15 live boards
python -m backend.worker --loop 300             # poll every 5 minutes
python -m backend.worker --source cache         # replay the last live responses, offline
python -m backend.worker --source fixture       # the labelled SYNTHETIC fixture boards

# 2. Self-healing check: hard-kills the worker twice mid-board, restarts, compares
python scripts/kill_restart_check.py                       # SQLite
python scripts/kill_restart_check.py --store clickhouse    # ClickHouse

# 3. ClickHouse + SYNTHETIC data
docker compose up -d --wait
BACKEND_STORE=clickhouse python -m backend.worker
python -m backend.generate --replace            # 10M SYNTHETIC rows, seed 42 (--rows N, --seed S)

# 4. Live stream and panel
BACKEND_STORE=clickhouse uvicorn backend.api:app --port 8000
streamlit run app/app.py                        # then open "Live postings"

# 5. Benchmark (writes docs/benchmarks/)
python -m backend.bench                         # --rows, --queries, --repeats, --skip-synthetic

# Tests (in-memory SQLite, no network, no Docker)
pytest tests/test_backend.py
```

Settings are optional and listed in `.env.example` (`BACKEND_STORE`, `BACKEND_SQLITE_PATH`, `CLICKHOUSE_*`, plus `BACKEND_WS_URL` for the page). No secrets are needed: the Greenhouse Job Board API is public and the local ClickHouse has no password.

## Design and tradeoffs

**Public API only, with a replayable cache.** The worker calls `boards-api.greenhouse.io/v1/boards/<token>/jobs?content=true`, which is Greenhouse's documented public endpoint for job boards, and scrapes nothing. Each response is saved (written aside, then renamed) so `--source cache` replays it exactly. That is what makes the kill check and the benchmark reproducible.

**Retries.** Network errors, 429 and 5xx are retried up to 5 attempts with capped exponential backoff and full jitter (`uniform(0, min(30, 0.5·2^k))` seconds), honouring `Retry-After`. Other 4xx responses fail at once, because a wrong board token never recovers. A board that still fails gets a `failed` checkpoint and the pass moves on, so one bad board can't stall the other 14.

**Checkpoint + idempotent writes instead of a transaction across systems.** Each posting's key is `greenhouse:<board>:<job id>`, which is stable for the posting's life. Rows go in batches of 500. A batch inserts only keys the store doesn't have, and the board's checkpoint is appended after its last batch. A crash at any point leaves at worst a half-written board without a checkpoint. On restart the unfinished run resumes, done boards are skipped, and the half-written board is re-read: its stored keys are skipped and nothing is duplicated. This works on ClickHouse, which has no multi-statement transactions, and it is what `kill_restart_check.py` proves with `TerminateProcess`, not a polite shutdown. ReplacingMergeTree is a second line of defence only: its merges are asynchronous, so the check counts raw rows without `FINAL`.

**Two stores, one interface.** SQLite needs nothing installed and backs the tests. ClickHouse is the analytics store: columnar, compressed, and fast at `GROUP BY` over millions of rows. The worker only sees `write_rows`, `start_or_resume_run`, `checkpoint`, `finish_run` and `aggregates`.

**Incremental aggregates.** In ClickHouse, a materialized view runs on each inserted block and adds its counts to a SummingMergeTree, so the stream reads a few thousand pre-summed rows instead of scanning 10M postings. This is exact only because rows are never updated or deleted, and that in turn depends on the dedupe step above. In SQLite the same deltas (`aggregate_delta`) are added in the same transaction as the postings, so the aggregate test can compare them with a full recount.

**Poll-and-fan-out WebSocket.** One background task per dataset reads the aggregates every 2 s and pushes to every client only when they changed. Database load doesn't grow with the number of viewers, and an idle feed sends nothing. The cost is up to 2 s of latency and a full (small, ~2 KB) snapshot per change instead of a delta. A message bus such as Redis pub/sub would remove the polling, but it is another service to run.

**Synthetic data is never mixed with real data.** It goes in separate tables with separate aggregates. It is labelled by table name and comment, by `is_synthetic = 1` (enforced by a `CHECK` constraint, which refuses any other row), by a `synthetic:` key prefix and `board = 'synthetic'`, and by "Synthetic Employer NNN" names, never a real company. The API sets `"synthetic": true` on its messages and the page prints "SYNTHETIC DATA".

## Benchmark results

Measured 2026-11-04 12:42 by `python -m backend.bench`.

**Hardware.** 13th Gen Intel(R) Core(TM) i7-13650HX (14 cores, 20 threads), 23.7 GB RAM, Windows-10-10.0.26300-SP0, Python 3.11.0. ClickHouse 25.8.33.6 in Docker (max_threads 20, 11.5 GB).

| Measure | Dataset | Result |
|---|---|---|
| Skill matching, before (`match_tokens_reference`) | 3,968 real Greenhouse postings, 3,732,056 tokens | 1.70 s |
| Skill matching, after (`match_tokens`) | same | 0.17 s (10.0x; identical output: True) |
| Worker pass under cProfile, before / after | same | 6.2 s / 2.2 s |
| Worker ingest into ClickHouse (parse, skills, dedupe, insert) | 3,968 real postings | 1,785 rows/s |
| SYNTHETIC generate (numpy, Python lists) | 10,000,000 rows | 798,183 rows/s |
| SYNTHETIC insert (clickhouse-connect, 500,000-row batches, 2 materialized views) | 10,000,000 rows | 422,757 rows/s |
| SYNTHETIC generate + insert | 10,000,000 rows | 276,375 rows/s (36 s) |

Queries on 10,000,000 SYNTHETIC rows, 300 timed runs each after 5 warm-ups, client-side wall time over HTTP:

| Query | p50 | p99 |
|---|---|---|
| api_snapshot (materialized views) | 19.4 ms | 27.0 ms |
| top 10 skills, 30 days (materialized view) | 5.0 ms | 7.2 ms |
| top 10 skills, 30 days (raw table) | 9.3 ms | 13.5 ms |
| daily volume, 2 years (materialized view) | 3.7 ms | 5.2 ms |
| daily volume, 2 years (raw table) | 7.7 ms | 9.1 ms |
| one employer's daily volume, 90 days (raw table) | 7.3 ms | 9.5 ms |

In the profiled pass, `match_tokens_reference` took 3.44 s of 6.18 s self time (4.49 s with its callees). After the change, `match_tokens` takes 0.17 s self time (0.51 s with its callees) of 2.18 s, and the regex `sub` (tag stripping), `findall` (tokenising) and `html.unescape` lead the profile.

How to read these numbers:
- The materialized views win less than you might expect at 10M rows (5.0 ms against 9.3 ms for the top skills). ClickHouse scans 10M rows in a few milliseconds, and roughly 3–4 ms of every query is the HTTP round trip. The gap widens as the raw table grows, while the view tables grow only with days × skills.
- `api_snapshot` is five round trips: emptiness check, latest day, volume, skills and total.
- Worker ingest (1,785 rows/s) is bound by work per posting (HTML unescape and skills on about 940 tokens each) and by two round trips per 500-row batch (dedupe lookup, then insert), not by ClickHouse.

### Profile

`docs/benchmarks/profile_before.txt` and `profile_after.txt` hold cProfile's top 15 functions by self time for one CPU-only worker pass (responses preloaded, in-memory SQLite). Before the change, `match_tokens` was the single slowest function by a wide margin. It tried every 1–3-token window at every token, about 11M dict lookups for 3.7M tokens. The rewrite does one set lookup per token in a list comprehension to find the few tokens that can start a skill name, and builds windows only there. It is checked against the kept original (`match_tokens_reference`) on every posting on each benchmark run. Afterwards the pass is dominated by `html.unescape`, the tag-stripping regex and tokenising, which are already C code inside the standard library.

**Rust: not done.** The plan was to move `match_tokens` into a PyO3 extension with the Python version as fallback. This machine has no Rust toolchain: no `cargo`/`rustc`, an empty `~/.rustup` from an earlier aborted install, and no MSVC Build Tools for the default Windows linker. Installing one was out of scope, so the profiled function got the algorithmic fix above instead, and SIMD was not attempted. The `match_tokens` / `match_tokens_reference` pair and the benchmark are the harness a Rust version would plug into.

## Known limitations

- **Rust rewrite skipped** (see above). The before/after numbers compare two Python versions.
- **One worker per database.** The check-then-insert dedupe has a race if two workers write the same board at once. ReplacingMergeTree would merge the row away later, but the materialized views would already have counted it twice.
- **First version wins.** A posting edited on Greenhouse keeps its first stored row. Closed postings are not detected or removed, so totals only grow.
- **Views count only what is inserted after they exist.** There is no backfill command. A fresh `docker compose up` has the views from the start; for an older database, drop it and rerun the worker.
- **Skill matching is a word list.** It uses the 137 synonyms in `data/skills.csv`, longest match first. Single-letter names (R, C) are dropped because "R&D" and "C-suite" would match them. Generic terms are over-counted: "Artificial Intelligence" tops the live feed because many postings mention AI in boilerplate.
- **Not India-specific.** The 15 boards are global tech employers outside the 82-company library. Their numbers never appear on the Shortlist pages.
- **Project rule exception.** CLAUDE.md says GNews is the only API and rules out live job APIs. This branch adds the Greenhouse public API on request. Merging it into `main` would need that rule (and PRD.md) updated.
- **API pollers share one ClickHouse client.** With `BACKEND_STORE=clickhouse`, the live and synthetic pollers in `backend.api` use the same clickhouse-connect client from two threads. Their queries sometimes overlap and fail with "Attempt to execute concurrent queries within the same session": 6 of about 20 polls in one 20-second check. A failed poll is logged and retried 2 s later, so updates arrive late rather than not at all. The fix is to open one store per poller.
- **Local-only ClickHouse.** No password, bound to 127.0.0.1. A deployment would need users, TLS and secrets management.
- **Benchmark noise.** The i7-13650HX mixes performance and efficiency cores and runs on a laptop power profile, so CPU-bound timings vary between runs (the matcher's speedup measured 8.6×, 21.9× and 10.0× on three separate runs, and a 10M synthetic insert ran at 131k rows/s while other work shared the machine and at 423k rows/s in the benchmark). The table reports the median of 5 runs for the matcher, and percentiles of 300 runs for queries. Query times are client-side over HTTP and include the round trip.
- **Test scope.** Three tests by design: dedupe, checkpoint recovery and aggregate correctness, all on SQLite. The retry path, the ClickHouse store and the WebSocket were checked by hand and by the scripts above, not by pytest.
