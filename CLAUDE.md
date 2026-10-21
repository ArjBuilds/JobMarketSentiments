# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

This repo is pre-implementation: it currently holds only [PRD.md](PRD.md), [README.md](README.md) and [data/companies.csv](data/companies.csv) (82 curated companies). There is no `requirements.txt`, package code, database or test suite yet.

[PRD.md](PRD.md) is the specification of record. Read it before building anything — it fixes the feature list (F1–F9), data sources, SQLite schema, naming conventions and the milestone order. When something here and the PRD disagree, the PRD wins; update both.

## Architecture

A batch pipeline, deliberately split so the dashboard never calls a live source (the demo must survive a dead or rate-limited API):

```
sources → ingest/ (one loader per source, raw results cached)
        → process/ (VADER + TextBlob sentiment, spaCy skill extraction, turnover proxy)
        → SQLite in data/
        → app/ (Streamlit pages read only from SQLite)
```

Planned layout per the PRD: `data/` (CSV inputs + the SQLite file), `ingest/` (one script per source), `process/`, `app/`.

Six tables, all keyed on `company_id`: `companies`, `reviews`, `turnover`, `articles`, `jobs`, `job_skills`. Column lists are in the PRD's data dictionary.

Stack: Python 3.11/3.12, requests + feedparser + pandas for collection, vaderSentiment + TextBlob + spaCy (`en_core_web_sm`) for NLP, sqlite3/SQLAlchemy, Streamlit + Plotly, python-dotenv for API keys.

## Commands

Nothing is wired up yet. The intended setup, once `requirements.txt` exists (milestone 1):

```bash
python -m venv .venv && .venv\Scripts\activate   # Windows; this is a win32 checkout
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m ingest.<loader>      # ingest scripts are run on demand, not on app start
python -m process.<step>
streamlit run app/app.py
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
