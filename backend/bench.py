"""Reproducible benchmark of the backend. Every number is measured on this run.

Run with:  python -m backend.bench [--rows N] [--queries Q] [--skip-synthetic]
Needs:     docker compose up -d, and data/raw/greenhouse/ from one live worker run
           (python -m backend.worker); without it the labelled fixture is used.

Writes docs/benchmarks/results.json, results.md and profile_*.txt.

  hardware         CPU, cores, RAM, OS, Python, ClickHouse version
  skill matching   match_tokens_reference (before) against match_tokens (after)
                   on every cached Greenhouse posting: median of --repeats runs,
                   and the two must agree on every posting
  profile          cProfile of one worker pass (CPU only: responses preloaded,
                   in-memory SQLite) with each matcher, top 15 by self time
  worker ingest    the real worker on the cached postings into a fresh
                   ClickHouse database: parse + skills + dedupe + insert, rows/s
  synthetic ingest backend.generate: N SYNTHETIC rows (default 10M, seed 42),
                   generate and insert timed apart, rows/s
  queries          Q timed runs of each query after 5 warm-ups, p50 and p99
"""

from __future__ import annotations

import argparse
import cProfile
import html
import io
import json
import os
import platform
import pstats
import statistics
import subprocess
import sys
import time
from pathlib import Path

from backend import config, skills
from backend.greenhouse import fetch_board
from backend.store import ClickHouseStore, SQLiteStore
from backend.worker import run_pass

OUT_DIR = config.REPO_ROOT / "docs" / "benchmarks"
BENCH_DB = "bench_worker"


def hardware() -> dict:
    info = {"os": platform.platform(), "python": platform.python_version(), "logical_cpus": os.cpu_count()}
    if os.name == "nt":
        ps = ("(Get-CimInstance Win32_Processor).Name; (Get-CimInstance Win32_Processor).NumberOfCores;"
              " (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout
        name, cores, ram = [line.strip() for line in out.strip().splitlines()]
        info.update(cpu=name, physical_cores=int(cores), ram_gb=round(int(ram) / 2**30, 1))
    else:
        info.update(cpu=platform.processor())
    client = ClickHouseStore.connect("default")
    info["clickhouse"] = client.command("SELECT version()")
    # max_threads defaults to the cores the server can see.
    info["clickhouse_cpus"] = int(client.command("SELECT getSetting('max_threads')"))
    info["clickhouse_ram_gb"] = round(float(client.command(
        "SELECT value FROM system.asynchronous_metrics WHERE metric = 'OSMemoryTotal'")) / 2**30, 1)
    client.close()
    return info


def cached_boards() -> tuple[str, list[tuple[str, str]], dict]:
    """The source to replay, its boards and their preloaded responses."""
    source = "cache" if any(config.CACHE_DIR.glob("*.json")) else "fixture"
    boards = config.read_boards(config.FIXTURE_DIR / "boards.csv" if source == "fixture" else config.BOARDS_CSV)
    return source, boards, {b: fetch_board(b, source) for b, _ in boards}


def bench_matching(payloads: dict, repeats: int) -> dict:
    docs = [skills.tokens(skills.TAG.sub(" ", html.unescape(html.unescape(job.get("content") or ""))))
            for payload in payloads.values() for job in payload["jobs"]]
    same = all(skills.match_tokens(d) == skills.match_tokens_reference(d) for d in docs)
    timings = {}
    for name, fn in (("before", skills.match_tokens_reference), ("after", skills.match_tokens)):
        runs = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            for d in docs:
                fn(d)
            runs.append(time.perf_counter() - t0)
        timings[name] = statistics.median(runs)
    return {"postings": len(docs), "tokens": sum(map(len, docs)), "repeats": repeats, "identical_output": same,
            "before_s": timings["before"], "after_s": timings["after"],
            "speedup": timings["before"] / timings["after"]}


def profile_pass(boards, payloads, source: str, matcher, path: Path) -> float:
    """cProfile one CPU-only worker pass with the given matcher; returns its wall seconds."""
    original = skills.match_tokens
    skills.match_tokens = matcher
    store = SQLiteStore(":memory:")
    profiler = cProfile.Profile()
    t0 = time.perf_counter()
    profiler.enable()
    run_pass(store, boards, source, fetch=lambda board, _source: payloads[board])
    profiler.disable()
    seconds = time.perf_counter() - t0
    skills.match_tokens = original
    store.close()
    text = io.StringIO()
    pstats.Stats(profiler, stream=text).strip_dirs().sort_stats("tottime").print_stats(15)
    path.write_text(f"worker pass, {matcher.__name__}, {seconds:.2f} s under cProfile\n{text.getvalue()}",
                    encoding="utf-8")
    return seconds


def bench_worker(boards, payloads, source: str) -> dict:
    admin = ClickHouseStore.connect("default")
    admin.command(f"DROP DATABASE IF EXISTS {BENCH_DB}")
    admin.close()
    store = ClickHouseStore(BENCH_DB)
    t0 = time.perf_counter()
    added = run_pass(store, boards, source, fetch=lambda board, _source: payloads[board])
    seconds = time.perf_counter() - t0
    store.close()
    return {"rows": added, "seconds": seconds, "rows_per_s": added / seconds}


QUERIES = {
    # What the WebSocket poller runs for dataset=synthetic: three small queries.
    "api_snapshot (materialized views)": None,
    "top 10 skills, 30 days (materialized view)":
        "SELECT skill, sum(postings) AS n FROM synthetic_skill_daily WHERE day >= toDate('2026-10-31') - 29"
        " GROUP BY skill ORDER BY n DESC LIMIT 10",
    "top 10 skills, 30 days (raw table)":
        "SELECT arrayJoin(skills) AS skill, count() AS n FROM synthetic_postings"
        " WHERE posted_day >= toDate('2026-10-31') - 29 GROUP BY skill ORDER BY n DESC LIMIT 10",
    "daily volume, 2 years (materialized view)":
        "SELECT day, sum(postings) FROM synthetic_volume_daily GROUP BY day ORDER BY day",
    "daily volume, 2 years (raw table)":
        "SELECT posted_day, count() FROM synthetic_postings GROUP BY posted_day ORDER BY posted_day",
    "one employer's daily volume, 90 days (raw table)":
        "SELECT posted_day, count() FROM synthetic_postings WHERE company = 'Synthetic Employer 007'"
        " AND posted_day >= toDate('2026-10-31') - 89 GROUP BY posted_day ORDER BY posted_day",
}


def bench_queries(n: int) -> dict:
    store = ClickHouseStore(config.CLICKHOUSE_DB)
    results = {}
    for name, sql in QUERIES.items():
        run = (lambda: store.aggregates(synthetic=True)) if sql is None else (lambda sql=sql: store.client.query(sql))
        for _ in range(5):
            run()
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            run()
            times.append((time.perf_counter() - t0) * 1000)
        cuts = statistics.quantiles(times, n=100, method="inclusive")
        results[name] = {"runs": n, "p50_ms": cuts[49], "p99_ms": cuts[98]}
    results["_table_rows"] = store.client.command("SELECT count() FROM synthetic_postings")
    store.close()
    return results


def markdown(r: dict) -> str:
    hw, m = r["hardware"], r["skill_matching"]
    lines = [
        f"Measured {r['measured_at']} by `python -m backend.bench`.",
        "",
        f"**Hardware.** {hw['cpu']} ({hw.get('physical_cores', '?')} cores, {hw['logical_cpus']} threads), "
        f"{hw.get('ram_gb', '?')} GB RAM, {hw['os']}, Python {hw['python']}. ClickHouse {hw['clickhouse']} in "
        f"Docker (max_threads {hw['clickhouse_cpus']}, {hw['clickhouse_ram_gb']} GB).",
        "",
        "| Measure | Dataset | Result |",
        "|---|---|---|",
        f"| Skill matching, before (`match_tokens_reference`) | {m['postings']:,} real Greenhouse postings, "
        f"{m['tokens']:,} tokens | {m['before_s']:.2f} s |",
        f"| Skill matching, after (`match_tokens`) | same | {m['after_s']:.2f} s "
        f"({m['speedup']:.1f}x; identical output: {m['identical_output']}) |",
        f"| Worker pass under cProfile, before / after | same | {r['profile']['before_s']:.1f} s / "
        f"{r['profile']['after_s']:.1f} s |",
        f"| Worker ingest into ClickHouse (parse, skills, dedupe, insert) | {r['worker']['rows']:,} real postings "
        f"| {r['worker']['rows_per_s']:,.0f} rows/s |",
    ]
    if "synthetic" in r:
        s = r["synthetic"]
        lines += [
            f"| SYNTHETIC generate (numpy, Python lists) | {s['rows']:,} rows | {s['generate_rows_per_s']:,.0f} rows/s |",
            f"| SYNTHETIC insert (clickhouse-connect, {s['batch']:,}-row batches, 2 materialized views) | "
            f"{s['rows']:,} rows | {s['insert_rows_per_s']:,.0f} rows/s |",
            f"| SYNTHETIC generate + insert | {s['rows']:,} rows | {s['end_to_end_rows_per_s']:,.0f} rows/s "
            f"({s['generate_s'] + s['insert_s']:.0f} s) |",
        ]
    q = r["queries"]
    lines += ["", f"Queries on {q['_table_rows']:,} SYNTHETIC rows, {next(iter(q.values()))['runs']} timed runs "
              "each after 5 warm-ups, client-side wall time over HTTP:", "",
              "| Query | p50 | p99 |", "|---|---|---|"]
    lines += [f"| {name} | {v['p50_ms']:.1f} ms | {v['p99_ms']:.1f} ms |" for name, v in q.items()
              if not name.startswith("_")]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=10_000_000, help="SYNTHETIC rows to generate")
    parser.add_argument("--queries", type=int, default=300, help="timed runs per query")
    parser.add_argument("--repeats", type=int, default=5, help="runs of each skill matcher")
    parser.add_argument("--skip-synthetic", action="store_true", help="query the synthetic rows already stored")
    args = parser.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    r = {"measured_at": time.strftime("%Y-%m-%d %H:%M"), "hardware": hardware()}
    source, boards, payloads = cached_boards()
    r["source"] = source
    print("skill matching ...", file=sys.stderr)
    r["skill_matching"] = bench_matching(payloads, args.repeats)
    print("profiling ...", file=sys.stderr)
    r["profile"] = {
        "before_s": profile_pass(boards, payloads, source, skills.match_tokens_reference,
                                 OUT_DIR / "profile_before.txt"),
        "after_s": profile_pass(boards, payloads, source, skills.match_tokens, OUT_DIR / "profile_after.txt"),
    }
    print("worker ingest ...", file=sys.stderr)
    r["worker"] = bench_worker(boards, payloads, source)
    if not args.skip_synthetic:
        from backend.generate import generate
        r["synthetic"] = generate(args.rows, replace=True)
    print("queries ...", file=sys.stderr)
    r["queries"] = bench_queries(args.queries)

    (OUT_DIR / "results.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    (OUT_DIR / "results.md").write_text(markdown(r), encoding="utf-8")
    print(markdown(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
