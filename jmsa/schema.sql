-- Job Market Analyser schema. Six tables, all reachable from companies.
--
-- Conventions (see PRD.md "Data dictionary"):
--   company_id        lowercase slug, e.g. tata-consultancy-services
--   dates             TEXT holding ISO 8601
--   india_cities      semicolon-separated list, as are aliases and jobs.city
--   sentiment_label   positive at compound >= 0.05, negative at <= -0.05,
--                     neutral otherwise (standard VADER cut-offs)
--
-- Applied with executescript() by jmsa.db.apply_schema, so every statement
-- here must be idempotent.

CREATE TABLE IF NOT EXISTS companies (
    -- The first block mirrors the data/companies.csv header exactly: the
    -- library loader inserts the CSV rows unchanged. The glassdoor_* block
    -- is filled later by the ratings loader, not by the CSV.
    company_id              TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    sector                  TEXT NOT NULL,
    hq_country              TEXT,
    india_cities            TEXT,
    size_band               TEXT,
    careers_url             TEXT,
    publishes_attrition     TEXT,       -- yes | no, as curated in the CSV
    aliases                 TEXT,       -- other names the sources use for this company
    -- From data/raw/glassdoor_company_ratings.csv. When several rows share
    -- the name, the one with the highest review_count wins.
    glassdoor_rating        REAL,
    glassdoor_review_count  INTEGER,
    glassdoor_employer_size TEXT,
    glassdoor_industry      TEXT
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
    -- Indian data-science and analytics postings from
    -- data/raw/naukri_jobs_merged.csv. There is no posted date column
    -- because the source has no dates, only relative strings.
    job_id           TEXT PRIMARY KEY,
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    title            TEXT,
    city             TEXT,             -- semicolon-separated if the posting lists several
    posted_relative  TEXT,             -- "1 Day Ago", "30+ Days Ago"; empty for 19,479 rows
    url              TEXT,             -- empty for those same rows
    skills_raw       TEXT,             -- source string, skills concatenated with no separator
    source           TEXT,             -- naukri
    loaded_at        TEXT              -- when the snapshot was loaded
);

CREATE TABLE IF NOT EXISTS job_skills (
    -- Reaches companies through jobs, not directly. Filled by matching
    -- skills.csv against jobs.skills_raw with the spaCy PhraseMatcher.
    job_id  TEXT NOT NULL REFERENCES jobs(job_id),
    skill   TEXT NOT NULL,
    PRIMARY KEY (job_id, skill)
);

-- The F2 filters, the F7 skills chart and every company page scan by these.
CREATE INDEX IF NOT EXISTS idx_reviews_company  ON reviews(company_id);
CREATE INDEX IF NOT EXISTS idx_articles_company ON articles(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company     ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill ON job_skills(skill);
