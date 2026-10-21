-- Job Market Analyser schema. Six tables, all reachable from companies.
--
-- Conventions (see PRD.md "Data dictionary"):
--   company_id        lowercase slug, e.g. tata-consultancy-services
--   dates             TEXT holding ISO 8601
--   india_cities      semicolon-separated list
--   sentiment_label   positive at compound >= 0.05, negative at <= -0.05,
--                     neutral otherwise (standard VADER cut-offs)
--
-- Applied with executescript() by jmsa.db.apply_schema, so every statement
-- here must be idempotent.

CREATE TABLE IF NOT EXISTS companies (
    -- Columns mirror the data/companies.csv header exactly: the library
    -- loader inserts the CSV rows unchanged.
    company_id           TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    sector               TEXT NOT NULL,
    hq_country           TEXT,
    india_cities         TEXT,
    size_band            TEXT,
    ats_type             TEXT,          -- greenhouse | lever | empty
    ats_board_id         TEXT,
    careers_url          TEXT,
    publishes_attrition  TEXT           -- yes | no, as curated in the CSV
);

CREATE TABLE IF NOT EXISTS reviews (
    review_id           TEXT PRIMARY KEY,
    company_id          TEXT NOT NULL REFERENCES companies(company_id),
    review_date         TEXT,
    rating              REAL,
    headline            TEXT,
    pros                TEXT,
    cons                TEXT,
    job_title           TEXT,
    location            TEXT,
    sentiment_compound  REAL,
    sentiment_label     TEXT CHECK (sentiment_label IN ('positive', 'neutral', 'negative')),
    themes              TEXT           -- semicolon-separated: pay;culture;wlb;management
);

CREATE TABLE IF NOT EXISTS turnover (
    company_id     TEXT NOT NULL REFERENCES companies(company_id),
    period         TEXT NOT NULL,      -- e.g. FY25 or 2025-Q1
    attrition_pct  REAL,
    is_proxy       INTEGER NOT NULL DEFAULT 0 CHECK (is_proxy IN (0, 1)),
    source_url     TEXT,
    method_note    TEXT,               -- required when is_proxy = 1
    PRIMARY KEY (company_id, period)
);

CREATE TABLE IF NOT EXISTS articles (
    article_id          TEXT PRIMARY KEY,
    company_id          TEXT NOT NULL REFERENCES companies(company_id),
    title               TEXT,
    outlet              TEXT,
    published_at        TEXT,
    url                 TEXT,
    summary             TEXT,
    sentiment_compound  REAL,
    sentiment_label     TEXT CHECK (sentiment_label IN ('positive', 'neutral', 'negative'))
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    company_id   TEXT NOT NULL REFERENCES companies(company_id),
    title        TEXT,
    city         TEXT,
    posted_at    TEXT,
    url          TEXT,
    description  TEXT,
    source       TEXT,                 -- adzuna | greenhouse | lever
    fetched_at   TEXT                  -- drives the "last refresh" date on F8
);

CREATE TABLE IF NOT EXISTS job_skills (
    -- Reaches companies through jobs, not directly.
    job_id  TEXT NOT NULL REFERENCES jobs(job_id),
    skill   TEXT NOT NULL,
    PRIMARY KEY (job_id, skill)
);

-- The F2 filters, the F7 skills chart and every company page scan by these.
CREATE INDEX IF NOT EXISTS idx_reviews_company  ON reviews(company_id);
CREATE INDEX IF NOT EXISTS idx_articles_company ON articles(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company     ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill ON job_skills(skill);
