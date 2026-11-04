-- The backend's ClickHouse schema, applied statement by statement by
-- backend.store.ClickHouseStore. Every statement is idempotent.
--
-- Two posting tables that are never mixed:
--   postings            real Greenhouse postings, written by backend.worker
--                       (is_synthetic = 1 only for the labelled test fixture);
--   synthetic_postings  SYNTHETIC rows from backend.generate, for load tests
--                       and benchmarks. Its CHECK refuses any other row.

CREATE TABLE IF NOT EXISTS postings (
    dedupe_key      String,                 -- greenhouse:<board>:<job id>
    board           LowCardinality(String),
    job_id          String,
    company         LowCardinality(String),
    title           String,
    location        String,
    department      LowCardinality(String),
    first_published DateTime('UTC'),
    posted_day      Date,
    updated_at      DateTime('UTC'),
    url             String,
    skills          Array(LowCardinality(String)),
    is_synthetic    UInt8,
    fetched_at      DateTime('UTC')
)
-- The worker inserts only keys it doesn't have yet. ReplacingMergeTree is the
-- second line of defence: should two writers race, merges keep one row per key.
ENGINE = ReplacingMergeTree
ORDER BY dedupe_key;

CREATE TABLE IF NOT EXISTS synthetic_postings (
    dedupe_key      String,                 -- synthetic:<seed>:<row number>
    board           LowCardinality(String), -- always 'synthetic'
    job_id          String,
    company         LowCardinality(String), -- 'Synthetic Employer 001' ...: no real employer
    title           String,
    location        String,
    department      LowCardinality(String),
    first_published DateTime('UTC'),
    posted_day      Date,
    updated_at      DateTime('UTC'),
    url             String,                 -- always empty
    skills          Array(LowCardinality(String)),
    is_synthetic    UInt8,
    fetched_at      DateTime('UTC'),
    CONSTRAINT synthetic_only CHECK is_synthetic = 1 AND startsWith(dedupe_key, 'synthetic:')
)
ENGINE = MergeTree
ORDER BY (posted_day, company)
COMMENT 'SYNTHETIC DATA from backend.generate. Not real job postings.';

-- Run log and per-board checkpoints, append-only (ClickHouse has no cheap
-- UPDATE). A run with a 'start' event and no 'finish' event was killed.
CREATE TABLE IF NOT EXISTS run_events (
    run_id  UInt64,
    event   Enum8('start' = 1, 'finish' = 2),
    at      DateTime('UTC')
)
ENGINE = MergeTree
ORDER BY (run_id, event);

CREATE TABLE IF NOT EXISTS checkpoints (
    run_id      UInt64,
    board       String,
    status      Enum8('done' = 1, 'failed' = 2),
    postings    UInt32,
    finished_at DateTime('UTC')
)
ENGINE = ReplacingMergeTree(finished_at)
ORDER BY (run_id, board);

