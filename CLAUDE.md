# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Milestone 1 (skeleton) is done: the package layout, schema, Streamlit scaffold and a pytest harness exist. No data is loaded yet; loading the company library is milestone 2.

Five files are on disk, and none of them is a live job API:

- [data/companies.csv](data/companies.csv) — 82 curated companies, the spine everything joins to.
- `data/raw/glassdoor_company_ratings.csv` — 3,029 rows of overall rating, review count, employer size and industry. No review text.
- `data/raw/all_reviews.csv` — 9.9M Glassdoor reviews with text (davidgauthier/glassdoor-job-reviews-2, CC BY-NC-SA 4.0). 1,799,628 of them match 78 of our 82 companies, 2008 to mid-2023. This replaced employee_reviews.csv, which is still on disk but no longer used.
- `data/raw/company_aliases.csv` — the 80 name mappings that matching depends on. Committed, unlike everything else in `raw/`.
- `data/raw/naukri_jobs_merged.csv` — 43,630 Indian Naukri data-science and analytics postings, already deduplicated.

[PRD.md](PRD.md) is the specification of record. Read it before building anything — it fixes the feature list (F1–F9), data sources, SQLite schema, naming conventions and the milestone order. When something here and the PRD disagree, the PRD wins; update both.

## Architecture

A batch pipeline, deliberately split so the dashboard never calls a live source (the demo must survive a dead or rate-limited API):

```
5 local CSVs + GNews
        → ingest/ (one loader per source, raw results cached)
        → process/ (VADER + TextBlob sentiment, spaCy skill extraction, turnover proxy)
        → SQLite in data/
        → app/ (Streamlit pages read only from SQLite)
```

Layout: `data/` (CSV inputs, the SQLite file, and `raw/` for the source CSVs and cached API responses), `ingest/` (one script per source), `process/`, `app/` (Streamlit entry + `pages/`), `jmsa/` (shared code: [config.py](jmsa/config.py), [db.py](jmsa/db.py), [schema.sql](jmsa/schema.sql)), `tests/`.

`jmsa/` is not in the PRD's original four-directory sketch. It exists because the loaders, the process steps and the app all need the same connection and the same sentiment cut-offs; put anything cross-cutting there rather than duplicating it.

Six tables: `companies`, `reviews`, `turnover`, `articles`, `jobs`, `job_skills`. All are keyed on `company_id` except `job_skills`, which reaches companies through `jobs`. The Glassdoor ratings are columns on `companies`, not a seventh table. Column lists are in the PRD's data dictionary; the DDL is [jmsa/schema.sql](jmsa/schema.sql).

Stack: Python 3.11, requests + pandas for collection, vaderSentiment + TextBlob + spaCy (`en_core_web_sm`) for NLP, stdlib `sqlite3` (no SQLAlchemy), Streamlit + Plotly, python-dotenv for API keys.

## Commands

The shell for this project is Git Bash, not PowerShell.

```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm   # not a requirements.txt entry

python -m jmsa.db init         # create/upgrade the empty database
streamlit run app/app.py       # dashboard at http://localhost:8501
python -m ingest.<loader>      # run on demand, never on app start
python -m process.<step>

pytest
pytest tests/test_schema.py::test_six_tables_created   # a single test
```

## Conventions that cross files

- `company_id` is a lowercase slug (`tata-consultancy-services`) and is the join key everywhere. Every source must be matched back to it; add an aliases column rather than fuzzy-matching names at query time.
- `india_cities` and other multi-value CSV fields are semicolon-separated.
- All dates are ISO 8601.
- `sentiment_label` uses the standard VADER cut-offs: positive at compound ≥ 0.05, negative at ≤ −0.05, neutral otherwise. Keep this in one shared helper rather than re-deriving it per loader.
- `sector` comes from a fixed list of 15 values already present in companies.csv — don't introduce new ones ad hoc.
- Each source is matched to the library once, at load time, never by fuzzy-matching at query time. Reviews use the committed `data/raw/company_aliases.csv`; the ratings and postings loaders use the `aliases` column on `companies`. 64 of the 82 companies match a Glassdoor ratings name exactly and 43 match a Naukri name, so aliases carry the rest.
- When several `glassdoor_company_ratings.csv` rows match one company — the same name is used by different employers — take the row with the highest `review_count`.
- `jobs` holds no posted date: the Naukri file has only relative strings (`posted_relative`, e.g. "1 Day Ago"), empty for 19,479 of its rows. Never convert these into dates.
- `skills_raw` concatenates skills with no separator (`Text miningCareer developmentdata science`), so it cannot be split on a delimiter. Match known skills from skills.csv against the string with the spaCy PhraseMatcher.

## Rules the data layer must hold to

- **Missing-data rule.** If a source returns nothing for a company, the field shows "not available". Never estimate, default or backfill a value.
- Hide review sentiment for a company with fewer than 20 reviews.
- Review-text sentiment (F4) covers 78 of the 82 companies. **atlassian**, **workday**, **jpmorgan-chase** and **hdfc-bank** have no reviews and must show "not available" — the last two because the dataset's `Chase` and `Hdfc` are different companies and were rejected rather than guessed.
- **ltimindtree**'s 10,545 reviews are pre-merger **Mindtree** rows, flagged `is_pre_merger`. Say so wherever they are shown.
- **intuit** clears the 20-review threshold with only 22 reviews, all 2022–23. Always show the review count beside a sentiment score.
- The review source has no location column, so `reviews.location` stays empty and nothing India-specific can be derived from review text.
- Glassdoor **ratings** and review **text** are different sources with different coverage. A company can have a rating and no sentiment; don't present one as the other.
- Turnover is either published attrition (with period and source URL) or the review-based proxy, and a proxy is always labelled `is_proxy` and surfaced as "proxy" in the UI.
- No live scraping of LinkedIn or Glassdoor — their terms forbid it. Reviews come from the CSV snapshots above.
- There are no live job APIs. Roles and skills (F7, F8) come only from `naukri_jobs_merged.csv`, which is Indian data-science and analytics postings. Label these views as data roles, and label counts as "roles posted in the dataset period", never "open now".
- Store no reviewer names or personal data.
- GNews is the only API in the project. Cache every response into SQLite; news runs at most once a day against free-tier limits.

## Build order

Work one PRD milestone at a time, run it, and commit before starting the next. F1–F8 are the submission minimum; F9 (compare view) is a stretch goal.

## How to work with me
- I'm new to coding. Build one milestone from the PRD's build order at a time, and only touch files that milestone needs.
- Plan first: list the files you'll create or change and why, then wait for my go-ahead.
- After each change, tell me exactly what command to run to test it and what I should see.
- Explain any non-obvious code in plain English, briefly. I need to be able to explain it in my viva.
- When something fails, find the cause before changing code. Don't paper over errors with try/except.
- Suggest a git commit message when a milestone works.

## Environment and secrets
- Windows, Git Bash terminal. Run Python with `py`; venv in `.venv`, activated with `source .venv/Scripts/activate`.
- Pin versions in requirements.txt.
- `GNEWS_API_KEY` is the only key the project needs. It lives only in .env; .env.example keeps it as an empty placeholder.
- .gitignore must include .env, .venv/, __pycache__/, data/raw/ and data/*.db.
- Stack is fixed per PRD.md; ask before adding a library.