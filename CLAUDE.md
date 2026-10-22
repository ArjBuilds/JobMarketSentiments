# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Job Market Analyser: a Streamlit dashboard of 82 large employers that hire in India (review sentiment, turnover, news, data roles and skills). All 10 PRD milestones are built.

## Read before you start

- [PRD.md](PRD.md): the specification of record (features F1–F9, sources, schema, milestones). When it and this file disagree, the PRD wins; update both.
- [DESIGN.md](DESIGN.md): the UI contract. Read it before changing anything in `app/`.
- [docs/dev/data_sources.md](docs/dev/data_sources.md): the rules for each source (ratings, reviews, Naukri postings and skills, GNews, published attrition, the proxy). Read the section for any source you touch.
- [docs/dev/project_state.md](docs/dev/project_state.md): what each milestone built, which module does what, and every loader's flags.
- [docs/methods.md](docs/methods.md): method, licences and caveats for the report. None of it goes on a page.

## Architecture

A batch pipeline, split so the dashboard never calls a live source (the demo must survive a dead or rate-limited API):

```
local CSVs + GNews → ingest/ (one loader per source) → process/ (sentiment, skills, proxy)
                   → SQLite data/jmsa.db → app/ (Streamlit, reads only SQLite)
```

- `jmsa/` holds the shared code (config, connection, schema, sentiment cut-offs, display text, freshness dates). Put anything cross-cutting there rather than duplicating it. Modules there have no Streamlit code, so tests call them directly.
- [app/app.py](app/app.py) routes every page with `st.navigation`, sets up shared state through [app/state.py](app/state.py) and checks the database once.
- Pages read sentiment from `review_summary`, never by aggregating `reviews` live. The DDL is [jmsa/schema.sql](jmsa/schema.sql).
- Stack (fixed; ask before adding a library): Python 3.11, requests + pandas, vaderSentiment + TextBlob + spaCy, stdlib `sqlite3` (no SQLAlchemy), Streamlit + Plotly, python-dotenv.

## Commands

The shell is Git Bash, not PowerShell.

```bash
source .venv/Scripts/activate
streamlit run app/app.py         # http://localhost:8501
pytest                           # in-memory databases, never data/jmsa.db
pytest tests/test_schema.py::test_six_tables_created   # a single test
python scripts/scan_ui.py        # every page and company: no raw values leak (exit 1 if any)
python scripts/time_pages.py     # each page's load time (target < 3 s)
python -m jmsa.db init           # creates missing tables only; after a column change,
                                 # delete data/jmsa.db and rerun the loaders
python scripts/make_demo_db.py   # refresh the committed data/demo.db after a rebuild
python scripts/freeze.py         # docs/freeze.md; after the final commit
```

Loaders and process steps run on demand (`python -m ingest.<loader>`, `python -m process.<step>`), never on app start. Their order and flags are in docs/dev/project_state.md. Point `JMSA_DB_PATH` at a throwaway file to keep test runs out of data/jmsa.db.

## Rules for every change

- **Join key.** `company_id` is a lowercase slug (`tata-consultancy-services`). Each source is matched to it once, at load time, through `data/raw/company_aliases.csv` (read via [jmsa/aliases.py](jmsa/aliases.py)); never fuzzy-match names at query time.
- **Formats.** Dates are ISO 8601 in the database; multi-value CSV fields are semicolon-separated.
- **Sentiment.** Cut-offs (positive ≥ 0.05, negative ≤ −0.05), the 20-review rule and all score text live in [jmsa/sentiment.py](jmsa/sentiment.py) (`label()`, `score_text()` for `+0.31 · Positive`, `hidden()` for `Fewer than 20 reviews (n = 12)`). Don't re-derive them. Hide a score under 20 reviews and always show the review count beside it.
- **Missing data.** A source with nothing for a company shows "Not available" (`NOT_AVAILABLE` in [jmsa/display.py](jmsa/display.py)). Never estimate, default or backfill. Glassdoor ratings and review sentiment are different sources; never present one as the other.
- **Text on pages.** Labels, one-sentence tooltips and one source-and-date line per block, from `freshness_notes()` in [jmsa/freshness.py](jmsa/freshness.py) (dates are read from the database, never typed). No method or caveat paragraphs, except About's collapsed "How scores work" expander, and no mention of the course. Count-plus-noun text goes through `plural()`.
- **Proxy and roles wording.** Every proxy figure has the "Proxy" tag (`PROXY_HELP` in [jmsa/turnover.py](jmsa/turnover.py)), reads "per 100 reviews", never %, and is never sorted or ranked. Data-role counts are "Data-role listings (2023 snapshot)" with "From a 2023 dataset, not live openings." (`ROLES_LABEL`/`ROLES_HELP` in [jmsa/jobs.py](jmsa/jobs.py)), never "open now".
- **Streamlit.** Cache results with `st.cache_data`, never a sqlite connection: reruns happen on other threads.
- **Sources and privacy.** No live scraping of LinkedIn or Glassdoor. No live job APIs. GNews is the only API. Store no reviewer names or personal data. Published attrition comes only from primary company documents (details in docs/dev/data_sources.md).
- **Secrets.** `GNEWS_API_KEY` lives only in .env (.env.example keeps an empty placeholder). Never print, log or store it; messages go through `redact()`.

## How to work with me

- I'm new to coding. Work one change or milestone at a time, and only touch the files it needs.
- Plan first: list the files you'll create or change and why, then wait for my go-ahead.
- After each change, tell me exactly what command to run to test it and what I should see.
- Explain any non-obvious code in plain English, briefly. I need to be able to explain it in my viva.
- When something fails, find the cause before changing code. Don't paper over errors with try/except.
- Suggest a git commit message when something works. With every milestone commit, update the README status line and feature list.

## Environment

- Windows, Git Bash. Run Python with `py`; venv in `.venv`. Pin versions in requirements.txt; `en_core_web_sm` is installed with `python -m spacy download en_core_web_sm`.
- .gitignore must cover .env, .venv/, `__pycache__/`, data/raw/ and data/*.db. The one exception is data/demo.db (about 1 MB, from scripts/make_demo_db.py), committed so a clone runs without the pipeline. Only the dashboard falls back to it; loaders never write to it.
