-- The backend's SQLite store (data/backend.db), used when BACKEND_STORE is
-- sqlite and by the tests. Separate from data/jmsa.db. Applied with
-- executescript(), so every statement is idempotent.

CREATE TABLE IF NOT EXISTS postings (
    dedupe_key      TEXT PRIMARY KEY,   -- greenhouse:<board>:<job id>
    board           TEXT NOT NULL,
    job_id          TEXT NOT NULL,
    company         TEXT NOT NULL,
    title           TEXT NOT NULL,
    location        TEXT,
    department      TEXT,
    first_published TEXT,               -- ISO 8601, UTC
    posted_day      TEXT,               -- first_published's date
    updated_at      TEXT,
    url             TEXT,
    skills          TEXT,               -- semicolon-separated
    is_synthetic    INTEGER NOT NULL CHECK (is_synthetic IN (0, 1)),
    fetched_at      TEXT NOT NULL
);

-- One row per pass over the boards. A run with no finished_at was killed;
-- the next start resumes it instead of starting over.
CREATE TABLE IF NOT EXISTS runs (
    run_id      INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT
);

-- The per-board checkpoint, written only after every row of the board is
-- stored, so a board without one is re-read on resume. Rows of it that were
-- stored before the kill are skipped by dedupe_key: no duplicates.
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id      INTEGER NOT NULL REFERENCES runs(run_id),
    board       TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('done', 'failed')),
    postings    INTEGER NOT NULL,
    finished_at TEXT NOT NULL,
    PRIMARY KEY (run_id, board)
);
