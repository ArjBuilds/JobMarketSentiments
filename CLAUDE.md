# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Milestone 1 (skeleton) is done: the package layout, schema, Streamlit scaffold and a pytest harness exist. No data is loaded yet — [data/companies.csv](data/companies.csv) (82 curated companies) is the only input, and loading it is milestone 2.

[PRD.md](PRD.md) is the specification of record. Read it before building anything — it fixes the feature list (F1–F9), data sources, SQLite schema, naming conventions and the milestone order. When something here and the PRD disagree, the PRD wins; update both.

## Architecture

A batch pipeline, deliberately split so the dashboard never calls a live source (the demo must survive a dead or rate-limited API):

```
sources → ingest/ (one loader per source, raw results cached)
        → process/ (VADER + TextBlob sentiment, spaCy skill extraction, turnover proxy)
        → SQLite in data/
        → app/ (Streamlit pages read only from SQLite)
```

Layout: `data/` (CSV inputs, the SQLite file, and `raw/` for cached API responses), `ingest/` (one script per source), `process/`, `app/` (Streamlit entry + `pages/`), `jmsa/` (shared code: [config.py](jmsa/config.py), [db.py](jmsa/db.py), [schema.sql](jmsa/schema.sql)), `tests/`.

`jmsa/` is not in the PRD's original four-directory sketch. It exists because the loaders, the process steps and the app all need the same connection and the same sentiment cut-offs; put anything cross-cutting there rather than duplicating it.

Six tables: `companies`, `reviews`, `turnover`, `articles`, `jobs`, `job_skills`. All are keyed on `company_id` except `job_skills`, which reaches companies through `jobs`. Column lists are in the PRD's data dictionary; the DDL is [jmsa/schema.sql](jmsa/schema.sql).

Stack: Python 3.11, requests + feedparser + pandas for collection, vaderSentiment + TextBlob + spaCy (`en_core_web_sm`) for NLP, stdlib `sqlite3` (no SQLAlchemy), Streamlit + Plotly, python-dotenv for API keys.

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
- `ats_type` / `ats_board_id` are empty for every company today; the Greenhouse/Lever loaders fill them in and only apply to companies that have them.

## Rules the data layer must hold to

- **Missing-data rule.** If a source returns nothing for a company, the field shows "not available". Never estimate, default or backfill a value.
- Hide review sentiment for a company with fewer than 20 reviews.
- Turnover is either published attrition (with period and source URL) or the review-based proxy, and a proxy is always labelled `is_proxy` and surfaced as "proxy" in the UI.
- No live scraping of LinkedIn or Glassdoor — their terms forbid it. Reviews come from a Kaggle snapshot.
- Store no reviewer names or personal data.
- Cache every API response into SQLite; news runs at most once a day against free-tier limits.

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
- API keys live only in .env. Keep .env.example with empty placeholders.
- .gitignore must include .env, .venv/, __pycache__/, data/raw/ and data/*.db.
- Stack is fixed per PRD.md; ask before adding a library.