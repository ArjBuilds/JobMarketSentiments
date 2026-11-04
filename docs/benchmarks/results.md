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
