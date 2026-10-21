-- Job Market Analyser schema. Six source tables, all reachable from
-- companies, plus review_summary, which is derived from reviews.
--
-- Conventions (see PRD.md "Data dictionary"):
--   company_id        lowercase slug, e.g. tata-consultancy-services
--   dates             TEXT holding ISO 8601
--   india_cities      semicolon-separated list, as is jobs.city
--   sentiment_label   positive at compound >= 0.05, negative at <= -0.05,
--                     neutral otherwise (standard VADER cut-offs)
--
-- Applied with executescript() by jmsa.db.apply_schema, so every statement
-- here must be idempotent.

CREATE TABLE IF NOT EXISTS companies (
    -- The first block mirrors the data/companies.csv header exactly, in
    -- order; ingest.load_companies checks this. The glassdoor_* block is
    -- filled later by the ratings loader, not by the CSV. Other names the
    -- sources use for a company live in data/raw/company_aliases.csv, not here.
    company_id              TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    sector                  TEXT NOT NULL,
    hq_country              TEXT,
    india_cities            TEXT,
    size_band               TEXT,
    careers_url             TEXT,
    publishes_attrition     TEXT,       -- yes | no, as curated in the CSV
    -- From data/raw/glassdoor_company_ratings.csv. When several rows share
    -- the name, the one with the highest review_count wins.
    glassdoor_rating        REAL,
    glassdoor_review_count  INTEGER,
    glassdoor_employer_size TEXT,
    glassdoor_industry      TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    -- Loaded from data/raw/glassdoor_reviews_matched.csv by ingest.load_reviews;
    -- the sentiment and theme columns are filled by process.review_sentiment.
    -- No reviewer names or other personal fields are stored.
    review_id           TEXT PRIMARY KEY,  -- gd-0000001: record number in the matched CSV
    company_id          TEXT NOT NULL REFERENCES companies(company_id),
    review_date         TEXT,              -- NULL for the 34 rows with an unparseable date
    rating              REAL,
    headline            TEXT,
    pros                TEXT,
    cons                TEXT,
    job_title           TEXT,
    location            TEXT,              -- always NULL: the source has no location
    is_pre_merger       INTEGER NOT NULL DEFAULT 0 CHECK (is_pre_merger IN (0, 1)),
    -- Glassdoor's coded answers, stored as given. Meanings are unverified (check
    -- the Kaggle dataset card): v positive, r mild, o no opinion, x negative.
    recommend           TEXT CHECK (recommend IN ('v', 'r', 'o', 'x')),
    ceo_approval        TEXT CHECK (ceo_approval IN ('v', 'r', 'o', 'x')),
    business_outlook    TEXT CHECK (business_outlook IN ('v', 'r', 'o', 'x')),
    -- Star sub-ratings. Anything that isn't 1-5 in the source (some cells hold
    -- scraped codes such as "10u0eun") is stored as NULL.
    career_opportunities      INTEGER CHECK (career_opportunities BETWEEN 1 AND 5),
    compensation_and_benefits INTEGER CHECK (compensation_and_benefits BETWEEN 1 AND 5),
    senior_management         INTEGER CHECK (senior_management BETWEEN 1 AND 5),
    work_life_balance         INTEGER CHECK (work_life_balance BETWEEN 1 AND 5),
    culture_and_values        INTEGER CHECK (culture_and_values BETWEEN 1 AND 5),
    diversity_and_inclusion   INTEGER CHECK (diversity_and_inclusion BETWEEN 1 AND 5),
    -- mean(headline, mean(pros, cons)), each part scored by VADER on its own;
    -- NULL when the review has no text. See jmsa/sentiment.py.
    sentiment_compound  REAL,
    sentiment_label     TEXT CHECK (sentiment_label IN ('positive', 'neutral', 'negative')),
    themes              TEXT,          -- semicolon-separated: pay;culture;wlb;management
    -- VADER score of the section(s) that mention the theme; NULL if not mentioned.
    theme_pay           REAL,
    theme_culture       REAL,
    theme_wlb           REAL,
    theme_management    REAL
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

CREATE TABLE IF NOT EXISTS review_summary (
    -- Derived, not a source: per-company review figures precomputed by
    -- process.review_sentiment, so a page reads one row instead of
    -- aggregating up to 163k reviews. One row per company per period, and
    -- only for companies with at least one scored review. The numbers are
    -- stored as computed; the 20-review rule is applied when they are shown.
    company_id          TEXT NOT NULL REFERENCES companies(company_id),
    period              TEXT NOT NULL CHECK (period IN ('all', '2020-2023')),
    review_count        INTEGER NOT NULL,  -- reviews with a sentiment score
    first_date          TEXT,
    last_date           TEXT,
    avg_compound        REAL,
    share_positive      REAL,
    share_neutral       REAL,
    share_negative      REAL,
    pay_count           INTEGER,           -- reviews mentioning the theme
    pay_compound        REAL,
    culture_count       INTEGER,
    culture_compound    REAL,
    wlb_count           INTEGER,
    wlb_compound        REAL,
    management_count    INTEGER,
    management_compound REAL,
    pre_merger_count    INTEGER NOT NULL,
    PRIMARY KEY (company_id, period)
);

-- Per-company lookups. The F2 filters don't use these: they read
-- review_summary, which has its own primary key. One composite index serves
-- both "a company's reviews" and "a company's reviews in a date range" (the
-- sentiment step's per-period summaries); it replaces the company-only index.
DROP INDEX IF EXISTS idx_reviews_company;
CREATE INDEX IF NOT EXISTS idx_reviews_company_date ON reviews(company_id, review_date);
CREATE INDEX IF NOT EXISTS idx_articles_company ON articles(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_company     ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_job_skills_skill ON job_skills(skill);
