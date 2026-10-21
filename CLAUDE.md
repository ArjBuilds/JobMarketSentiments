# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Milestones 1 (skeleton), 2 (company library), 3 (Glassdoor ratings), 4 (reviews and sentiment) and 5 (filters) are done:
- `python -m ingest.load_companies` loads companies.csv into `companies`, and `python -m ingest.load_glassdoor_ratings` fills its `glassdoor_*` columns. The Library page renders the F1 table with a rating per company.
- `python -m ingest.load_reviews` loads the 1.8M matched reviews. `python -m process.review_sentiment` scores them and fills `review_summary`. The Company page shows F4 sentiment for a selected company.
- `python -m process.sentiment_checks` writes the method comparison and the TextBlob agreement rate for the report.
- The Library page filters and sorts (F2) through [jmsa/library.py](jmsa/library.py), which has no Streamlit code so the tests call it directly. Add the M6 roles/skill filters as `Filters` fields and the M8 attrition sort as a `SORT_KEYS` entry there.

Milestone 6 (data roles and skills) is next.

Five files are on disk, and none of them is a live job API:

- [data/companies.csv](data/companies.csv) — 82 curated companies, the spine everything joins to.
- `data/raw/glassdoor_company_ratings.csv` — 3,029 rows of overall rating, review count, employer size and industry. No review text.
- `data/raw/all_reviews.csv` — 9.9M Glassdoor reviews with text (davidgauthier/glassdoor-job-reviews-2, CC BY-NC-SA 4.0). 1,799,628 of them match 78 of our 82 companies, 2008 to mid-2023. This replaced employee_reviews.csv, which is still on disk but no longer used.
- `data/raw/company_aliases.csv` — the name mappings that matching depends on (`company_id,alias_in_dataset,source`): 80 for review text, 5 for ratings. Committed, unlike everything else in `raw/`.
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

Seven tables:
- Six source tables: `companies`, `reviews`, `turnover`, `articles`, `jobs` and `job_skills`. All are keyed on `company_id` except `job_skills`, which reaches companies through `jobs`.
- One derived table, `review_summary`, with per-company review figures for `all` and `2020-2023`. Pages read sentiment from it, never by aggregating `reviews` live.

The Glassdoor ratings are columns on `companies`, not a table of their own. Column lists are in the PRD's data dictionary; the DDL is [jmsa/schema.sql](jmsa/schema.sql).

Stack: Python 3.11, requests + pandas for collection, vaderSentiment + TextBlob + spaCy (`en_core_web_sm`) for NLP, stdlib `sqlite3` (no SQLAlchemy), Streamlit + Plotly, python-dotenv for API keys.

## Commands

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

pytest
pytest tests/test_schema.py::test_six_tables_created   # a single test
```

## Conventions that cross files

- `company_id` is a lowercase slug (`tata-consultancy-services`) and is the join key everywhere. Every source must be matched back to it; add a row to `data/raw/company_aliases.csv` rather than fuzzy-matching names at query time.
- `india_cities` and other multi-value CSV fields are semicolon-separated.
- All dates are ISO 8601.
- `sentiment_label` uses the standard VADER cut-offs: positive at compound ≥ 0.05, negative at ≤ −0.05, neutral otherwise. These live in one shared helper, [jmsa/sentiment.py](jmsa/sentiment.py), with `label()`, `combine()` and the 20-review rule; don't re-derive them per loader.
- A review's score is `mean(headline, mean(pros, cons))`, each part scored by VADER on its own. Don't subtract cons: VADER already scores them negative, and pros − cons had zero correlation with star ratings. A review with no text gets NULL, not 0.
- Theme keywords live in [data/themes.csv](data/themes.csv). The four theme names are fixed, and the keywords are editable. A theme's score is the VADER score of the section (headline, pros or cons) that mentions it.
- The meanings of the review letter codes (`recommend`, `ceo_approval`, `business_outlook`: v, r, o, x) are unverified; check them against the Kaggle dataset card before interpreting them.
- `sector` comes from a fixed list of 15 values already present in companies.csv — don't introduce new ones ad hoc.
- Each source is matched to the library once, at load time, never by fuzzy-matching at query time. Every source uses the committed `data/raw/company_aliases.csv`, the only alias store (`companies` has no aliases column). Its `source` column (`glassdoor_reviews`, `glassdoor_ratings`; Naukri gets its own in milestone 6) keeps each alias to the dataset it was found in. Read it through [jmsa/aliases.py](jmsa/aliases.py), which also holds the shared `normalise()`. 43 companies match a Naukri name exactly, so aliases carry the rest.
- When several `glassdoor_company_ratings.csv` rows match one company — the same name is used by different employers — take the row with the highest `review_count`.
- Ratings coverage: 66 of 82 companies (61 by exact name, 5 by alias). 16 show "not available": the file has only subsidiaries or regional arms for tata-consultancy-services, infosys, accenture, capgemini, ibm, deloitte, amazon and walmart; no row at all for cognizant, linkedin, blackrock and visa; **wipro**, **ey** and **tata-motors** are exact matches deliberately rejected (`REJECTED` in the ratings loader) because the rows have low review counts and a foreign head office, i.e. regional pages; and **mercedes-benz** has no ratings alias because its only row, Mercedes-Benz International (Motor Vehicle Dealers, 3 offices), is a sales arm, not the group. Its glassdoor_reviews alias is unaffected. Employer size is not a reason to reject — that column is unreliable across the file. The loader's report flags, without changing, big companies (size band 50k-200k or 200k+) with under 5,000 ratings reviews as "check: possibly a regional page".
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