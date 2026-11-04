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

-- Real-time aggregates (M4), kept up to date incrementally: a materialized
-- view runs on every block inserted into its source table and adds that
-- block's counts to a SummingMergeTree, which merges rows with the same key
-- by adding them, in the background. Read with sum() ... GROUP BY, because
-- unmerged parts can still hold several rows per key. Each skill counts once
-- per posting (skills arrays hold distinct names), and a posting counts on
-- its posted_day. Inserted rows are never updated or deleted, so adding is
-- exact; that is why the worker inserts only keys it doesn't have yet.
CREATE TABLE IF NOT EXISTS volume_daily (
    day      Date,
    postings UInt64
)
ENGINE = SummingMergeTree
ORDER BY day;

CREATE MATERIALIZED VIEW IF NOT EXISTS volume_daily_mv TO volume_daily AS
SELECT posted_day AS day, count() AS postings FROM postings GROUP BY day;

CREATE TABLE IF NOT EXISTS skill_daily (
    day      Date,
    skill    LowCardinality(String),
    postings UInt64
)
ENGINE = SummingMergeTree
ORDER BY (day, skill);

CREATE MATERIALIZED VIEW IF NOT EXISTS skill_daily_mv TO skill_daily AS
SELECT posted_day AS day, arrayJoin(skills) AS skill, count() AS postings FROM postings GROUP BY day, skill;

-- The same two aggregates over SYNTHETIC rows, never mixed with the real ones.
CREATE TABLE IF NOT EXISTS synthetic_volume_daily (
    day      Date,
    postings UInt64
)
ENGINE = SummingMergeTree
ORDER BY day
COMMENT 'SYNTHETIC DATA aggregate.';

CREATE MATERIALIZED VIEW IF NOT EXISTS synthetic_volume_daily_mv TO synthetic_volume_daily AS
SELECT posted_day AS day, count() AS postings FROM synthetic_postings GROUP BY day;

CREATE TABLE IF NOT EXISTS synthetic_skill_daily (
    day      Date,
    skill    LowCardinality(String),
    postings UInt64
)
ENGINE = SummingMergeTree
ORDER BY (day, skill)
COMMENT 'SYNTHETIC DATA aggregate.';

CREATE MATERIALIZED VIEW IF NOT EXISTS synthetic_skill_daily_mv TO synthetic_skill_daily AS
SELECT posted_day AS day, arrayJoin(skills) AS skill, count() AS postings FROM synthetic_postings GROUP BY day, skill;
