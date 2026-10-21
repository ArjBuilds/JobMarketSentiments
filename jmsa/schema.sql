-- Job Market Analyser schema. Six source tables, all reachable from
-- companies, plus two derived tables: review_summary, derived from reviews,
-- and skill_counts, market-wide skill counts that reach no company. A ninth,
-- news_fetches, records each company's last GNews fetch for articles.
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
    -- Two kinds of row, never mixed (F5):
    --   is_proxy = 0  published attrition from a primary document
    --                 (data/turnover.csv, loaded by ingest.load_turnover);
    --   is_proxy = 1  the review-based proxy, from process.turnover_proxy: the
    --                 share of reviews in a fixed window whose headline or cons
    --                 mention leaving, attrition or layoffs.
    -- The proxy is a share of reviews, not of staff, so it has its own column
    -- and the CHECK below keeps it out of attrition_pct.
    company_id        TEXT NOT NULL REFERENCES companies(company_id),
    is_proxy          INTEGER NOT NULL CHECK (is_proxy IN (0, 1)),
    period            TEXT NOT NULL,   -- label: 'FY2024-25', 'LTM to Sep 2025', '2021-04 to 2023-03'
    period_start      TEXT,            -- ISO 8601
    period_end        TEXT NOT NULL,   -- ISO 8601; a company's latest figure has the latest period_end
    -- Published only. basis is what the document says: 'not-stated' when it
    -- doesn't say voluntary or total, never inferred.
    attrition_pct     REAL CHECK (attrition_pct BETWEEN 0 AND 100),
    attrition_text    TEXT,            -- the value as printed ('13', '8.80'), shown so no precision is implied
    basis            TEXT CHECK (basis IN ('voluntary', 'total', 'not-stated')),
    scope             TEXT CHECK (scope IN ('group', 'segment', 'india-subsidiary')),
    -- Proxy only. A review can mention both leaving and layoffs, so
    -- reviews_leaving + reviews_layoffs can exceed reviews_matched.
    proxy_share       REAL CHECK (proxy_share BETWEEN 0 AND 1),   -- reviews_matched / reviews_in_window
    reviews_in_window INTEGER,
    reviews_matched   INTEGER,         -- mentioning either kind
    reviews_leaving   INTEGER,         -- mentioning leaving or attrition
    reviews_layoffs   INTEGER,         -- mentioning layoffs
    -- Both
    definition        TEXT NOT NULL,   -- e.g. 'voluntary attrition, LTM, IT services employees'
    entity            TEXT NOT NULL,   -- whose figure: 'Infosys Ltd (group)', 'Glassdoor reviews of Infosys'
    source_url        TEXT,
    source_ref        TEXT,            -- page, table or BRSR question in the source
    retrieved_on      TEXT,            -- ISO 8601 date
    method_note       TEXT,
    PRIMARY KEY (company_id, is_proxy, period),
    CHECK (
        (is_proxy = 1 AND attrition_pct IS NULL AND basis IS NULL AND scope IS NULL
         AND proxy_share IS NOT NULL AND reviews_in_window IS NOT NULL AND method_note IS NOT NULL)
        OR
        (is_proxy = 0 AND proxy_share IS NULL AND attrition_pct IS NOT NULL
         AND attrition_text IS NOT NULL AND basis IS NOT NULL AND scope IS NOT NULL
         -- IS NOT NULL first: NULL LIKE '...' is NULL, which a CHECK lets through
         AND source_url IS NOT NULL AND source_url LIKE 'https://%'
         AND source_ref IS NOT NULL AND retrieved_on IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS articles (
    -- News about working at a company (F6), from GNews by ingest.load_news.
    -- Only the headline and GNews's short description are kept, never the
    -- article text. When the company's articles were fetched is in news_fetches.
    article_id          TEXT PRIMARY KEY,  -- <company_id>:<first 12 hex of sha1(url)>
    company_id          TEXT NOT NULL REFERENCES companies(company_id),
    title               TEXT,
    outlet              TEXT,
    published_at        TEXT,
    url                 TEXT,
    summary             TEXT,              -- GNews's description of the article
    -- VADER on title + description, labelled by jmsa.sentiment.label()
    sentiment_compound  REAL,
    sentiment_label     TEXT CHECK (sentiment_label IN ('positive', 'neutral', 'negative'))
);

CREATE TABLE IF NOT EXISTS news_fetches (
    -- One row per company: its last GNews fetch, written by ingest.load_news
    -- in the same transaction as its articles. It is what lets a rerun skip
    -- companies fetched in the last 24 hours, and lets the page say when news
    -- was fetched even when no article was kept. response_json caches the API
    -- response, with every article's content field removed, so articles can
    -- be re-selected (--from-cache) without spending quota.
    company_id          TEXT PRIMARY KEY REFERENCES companies(company_id),
    fetched_at          TEXT NOT NULL,     -- ISO 8601, UTC
    query               TEXT NOT NULL,     -- as sent, from data/news_queries.csv
    window_from         TEXT NOT NULL,     -- fetched_at minus 30 days, the free tier's archive
    returned            INTEGER NOT NULL,  -- articles in the response
    dropped_irrelevant  INTEGER NOT NULL,  -- not naming the company in title or description
    dropped_duplicate   INTEGER NOT NULL,  -- same URL or a near-identical title
    kept                INTEGER NOT NULL,  -- rows in articles, at most 10
    response_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    -- Indian data-role postings from data/raw/naukri_jobs_merged.csv, loaded
    -- by ingest.load_jobs: only postings whose title is a data role and whose
    -- employer matched a library company. There is no posted date column
    -- because the source has no dates, only relative strings.
    --
    -- The source's columns are misaligned row by row: title and employer
    -- belong together, but the link, post time, locations and skills often
    -- come from another posting. So url, posted_relative and city are kept
    -- only when the link's slug names this row's title and employer, and are
    -- NULL otherwise.
    job_id           TEXT PRIMARY KEY,  -- nk-<job_row_id>
    company_id       TEXT NOT NULL REFERENCES companies(company_id),
    employer_name    TEXT,              -- company_name as posted, e.g. "KPMG Global Services Private Limited"
    title            TEXT,
    city             TEXT,              -- read from the verified link; semicolon-separated if several
    posted_relative  TEXT,              -- "1 Day Ago", "30+ Days Ago" as given; never converted to a date
    url              TEXT,
    skills_raw       TEXT,              -- always NULL: the source's skills belong to other postings
    source           TEXT,              -- naukri
    loaded_at        TEXT               -- when the snapshot was loaded, ISO 8601
);

CREATE TABLE IF NOT EXISTS job_skills (
    -- Reaches companies through jobs, not directly. Always empty: the
    -- postings' skills belong to other rows, so no skill can be tied to a
    -- posting (jobs.skills_raw is always NULL too). Market-wide counts are in
    -- skill_counts instead.
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

CREATE TABLE IF NOT EXISTS skill_counts (
    -- Derived, not a source: market-wide data-role skills (F7), counted by
    -- process.skill_counts from naukri_jobs_merged.csv's skills_raw. Not keyed
    -- on company_id, because the source doesn't tie skills to an employer.
    -- Each distinct skills_raw string counts once (rows were copied when the
    -- listings were scraped repeatedly), so counts are a lower bound.
    scope           TEXT NOT NULL,     -- 'data-science' (the two data-science exports pooled) or one export's source_file
    skill           TEXT NOT NULL,     -- display name from data/skills.csv
    type            TEXT NOT NULL CHECK (type IN ('tool', 'method')),
    postings        INTEGER NOT NULL,  -- distinct skill lists in the scope that list the skill
    share           REAL NOT NULL,     -- postings / scope_postings
    scope_postings  INTEGER NOT NULL,  -- distinct non-empty skill lists scored in the scope
    PRIMARY KEY (scope, skill)
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
