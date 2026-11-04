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
