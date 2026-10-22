# Project state: what is built, and every command

Moved out of CLAUDE.md.

## Milestones

Milestones 1 (skeleton), 2 (company library), 3 (Glassdoor ratings), 4 (reviews and sentiment) and 5 (filters) are done:
- `python -m ingest.load_companies` loads companies.csv into `companies`, and `python -m ingest.load_glassdoor_ratings` fills its `glassdoor_*` columns. The Library page renders the F1 table with a rating per company.
- `python -m ingest.load_reviews` loads the 1.8M matched reviews. `python -m process.review_sentiment` scores them and fills `review_summary`. The Company page shows F4 sentiment for a selected company.
- `python -m process.sentiment_checks` writes the method comparison and the TextBlob agreement rate for the report.
- The Library page filters and sorts (F2) through [jmsa/library.py](../../jmsa/library.py), which has no Streamlit code so the tests call it directly. Add the M8 attrition sort as a `SORT_KEYS` entry there.

Milestone 6 is split in two. Stage A (data roles, F8) is built:
- `python -m ingest.load_jobs` filters titles, matches employers, verifies links and replaces `jobs`; it writes `data/raw/naukri_match_report.txt`. The Company page shows F8 through [jmsa/jobs.py](../../jmsa/jobs.py), and the Library page has the data-roles column, filter and sort.

Stage B (market-wide skills, F7) is built:
- `python -m process.skill_counts` matches data/skills.csv against skills_raw and replaces `skill_counts`; it writes `data/raw/skill_counts_report.txt`, and `--check N` writes a hand-check sample instead. The Market skills page shows F7 through [jmsa/skills.py](../../jmsa/skills.py); the Company page shows "not available" with a pointer.

Milestone 8 (turnover, F5) is built in two stages. Stage A, the review-based proxy:
- `python -m process.turnover_proxy` counts reviews whose headline or cons match [data/turnover_keywords.csv](../../data/turnover_keywords.csv) in the window and replaces the proxy rows of `turnover`; it writes `data/raw/turnover_proxy_report.txt`, and `--check N` writes a hand-check sample instead. The Company page shows F5 and the Library page two proxy columns through [jmsa/turnover.py](../../jmsa/turnover.py).

Stage B, published attrition:
- `python -m ingest.load_turnover` validates [data/turnover.csv](../../data/turnover.csv) (any bad row: nothing written) and replaces the published rows of `turnover`; it writes `data/raw/turnover_load_report.txt` with the proxy comparison. The Company page shows each company's latest figure; the Library page has the published-attrition column, sort and basis/scope filters.

Milestone 7 (news, F6) is built:
- `python -m ingest.load_news` sends one GNews request per company, using its query in [data/news_queries.csv](../../data/news_queries.csv), keeps the articles that name the company, dedupes them, keeps the 10 newest and scores them; it writes `data/raw/news_fetch_report.txt`. The Company page shows F6 through [jmsa/news.py](../../jmsa/news.py).

Milestone 9 (polish, F9) is built:
- [jmsa/freshness.py](../../jmsa/freshness.py) reads every source's dates from the database (review range, Naukri snapshot and load date, news fetch date, attrition retrieval date, proxy window) and holds the source citations and licences. Every page's source lines, the About page's sources table and the sidebar's "Data last refreshed" date (`last_refreshed()`) come from it.
- The Compare page (F9) builds its table in [jmsa/compare.py](../../jmsa/compare.py) from the Library's records and `display_row`, plus `read_news`, so labels and "not available" match. The About the data page is a sources table and a collapsed "How scores work" expander explaining every calculation; the method, licences and caveats are in [docs/methods.md](../../docs/methods.md), not on any page.
- `python scripts/time_pages.py` times every page against the real database; tests/test_pages.py runs every page twice headlessly.

Milestone 10 (report and demo) is built:
- `python -m process.analysis` reads only the database and writes the report's tables (markdown + CSV) to docs/analysis/. It reuses process.sentiment_checks' samples and helpers and load_turnover's `comparison_pairs`. Spearman, ranks and Cohen's kappa live in [jmsa/stats.py](../../jmsa/stats.py).
- `python -m ingest.merge_naukri --src <folder>` tries to rebuild the Naukri merge into `data/raw/naukri_jobs_merged.rebuilt.csv` and writes `data/raw/naukri_merge_check.txt`. It can't be reproduced, so the pinned merged file is the input of record. Never write over it.
- `python scripts/freeze.py` writes docs/freeze.md; run it after the final commit. docs/report_notes.md and docs/demo_script.md are the report and demo material.

## Layout and stack

Layout: `data/` (CSV inputs, the SQLite file, and `raw/` for the source CSVs and cached API responses), `ingest/` (one script per source), `process/`, `app/` (Streamlit entry + `pages/`; [app/app.py](../../app/app.py) routes every page with `st.navigation`, sets up shared session state through [app/state.py](../../app/state.py) and checks the database once; [DESIGN.md](../../DESIGN.md) is the UI contract), `scripts/` (developer checks, e.g. page timing), `jmsa/` (shared code: [config.py](../../jmsa/config.py), [db.py](../../jmsa/db.py), [schema.sql](../../jmsa/schema.sql)), `tests/`.

`jmsa/` is not in the PRD's original four-directory sketch. It exists because the loaders, the process steps and the app all need the same connection and the same sentiment cut-offs; put anything cross-cutting there rather than duplicating it.

Stack: Python 3.11, requests + pandas for collection, vaderSentiment + TextBlob + spaCy (`en_core_web_sm`) for NLP, stdlib `sqlite3` (no SQLAlchemy), Streamlit + Plotly, python-dotenv for API keys.

## Tables

Nine tables:
- Six source tables: `companies`, `reviews`, `turnover`, `articles`, `jobs` and `job_skills`. All are keyed on `company_id` except `job_skills`, which reaches companies through `jobs`.
- Two derived tables: `review_summary`, with per-company review figures for `all` and `2020-2023` (pages read sentiment from it, never by aggregating `reviews` live), and `skill_counts`, market-wide skill counts per scope, keyed on no company.
- `news_fetches`, one row per company: its last GNews fetch (`fetched_at`, query, counts) and the cached response with every article's `content` removed. It drives the 24-hour skip and "news fetched on".
- `job_skills` is always empty: no skill can be tied to a posting.

The Glassdoor ratings are columns on `companies`, not a table of their own. Column lists are in the PRD's data dictionary; the DDL is [jmsa/schema.sql](../../jmsa/schema.sql).

## Every command

The shell for this project is Git Bash, not PowerShell.

```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm   # not a requirements.txt entry

python -m jmsa.db init         # create missing tables; it can't add columns to an
                               # existing table, so after a column change delete
                               # data/jmsa.db and rerun the loaders
streamlit run app/app.py       # dashboard at http://localhost:8501
python -m ingest.<loader>      # run on demand, never on app start
python -m process.<step>

# Reviews: --company ID and --limit N for test runs. Point JMSA_DB_PATH at a
# throwaway file to keep test runs out of data/jmsa.db.
python -m ingest.load_reviews [--resume]       # ~1.8M rows, 50k per transaction
python -m process.review_sentiment [--rescore] # --rescore after editing themes.csv
python -m ingest.load_jobs                     # full replace of jobs; rerun after editing
                                               # data_role_keywords.csv or naukri aliases
python -m process.skill_counts [--check 50]    # full replace of skill_counts; rerun after
                                               # editing skills.csv. --check writes a sample only
python -m ingest.load_news [--company ID] [--limit N] [--refresh]
                                               # GNews; skips companies fetched in the last 24 h.
                                               # Exit code 3 = daily quota reached; rerun to resume
python -m ingest.load_turnover                 # replaces only the published rows of turnover; rerun
                                               # after editing turnover.csv (run turnover_proxy first)
python -m process.turnover_proxy [--check 50]  # replaces only the proxy rows of turnover; rerun
                                               # after editing turnover_keywords.csv. --check writes a sample only
python -m ingest.load_news --from-cache        # re-select from cached responses, 0 requests;
                                               # rerun after editing gnews aliases
python scripts/time_pages.py                   # each page's first-load and rerun time (target < 3 s)
python scripts/scan_ui.py                      # every page and company: no raw values leak (exit 1 if any)
python -m process.analysis                     # report tables in docs/analysis/ (re-runs TextBlob on 50k)
python -m ingest.merge_naukri --src "<folder>" # Naukri merge check; never overwrites the merged file
python scripts/make_demo_db.py                 # data/demo.db: jmsa.db minus review text, committed; app/app.py
                                               # falls back to it when data/jmsa.db is missing (fresh clone)
python scripts/freeze.py                       # docs/freeze.md; after the final commit, before the demo

pytest
pytest tests/test_schema.py::test_six_tables_created   # a single test

## Build order

Work one PRD milestone at a time, run it, and commit before starting the next. With every milestone commit, update the README status line and feature list. F1–F8 are the submission minimum; F9 (compare view) is a stretch goal.
