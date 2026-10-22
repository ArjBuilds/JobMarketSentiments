# JobMarketSentiments

**Job Market Analyser** is a Streamlit dashboard where a student picks a company and sees, on one page, what it is like to work there and what it hires for: employee review sentiment, turnover, recent news coverage, the data-role skills Indian postings ask for, and the India data roles the company posted. It covers a curated library of 82 large global employers that also hire in India.

Built as a mini-project for the Web and Social Media Analytics course. The analytics core is web data collection plus sentiment analysis with spaCy, VADER and TextBlob.

[PRD.md](PRD.md) is the specification: features, data sources, schema and build order.

## Status

**All 10 milestones are done.** Milestone 10 added the report's analysis tables (docs/analysis/), report notes, a demo script, a Naukri merge check and a freeze record.

| Feature | What it does | Works |
| --- | --- | --- |
| F1 Company library | Every company in one table | yes |
| F2 Sort and filter | Sector, country, rating, sentiment, reviews, data roles, attrition basis/scope | yes |
| F3 Company page | Everything about one company, plus a link to its careers site | yes |
| F4 Review sentiment | VADER over 1.8M Glassdoor reviews, overall and by theme | yes (78 of 82 companies) |
| F5 Turnover | Published attrition from primary documents, and a review-based proxy | yes (19 published, 78 proxy) |
| F6 News coverage | Up to 10 recent GNews articles with headline sentiment | yes |
| F7 Data-role skills | Market-wide top skills from Naukri postings | yes |
| F8 Data roles posted | A company's India data-role listings in the snapshot | yes (53 companies) |
| F9 Compare | 2–4 companies side by side | yes |

Milestone 9 added a source and date line under every section (read from the database), the Compare page, and an About and methods page.

## How it works

Data collection is a batch pipeline, kept separate from the dashboard so a demo survives a dead or rate-limited API:

```
sources → ingest/   one loader per source, raw responses cached
        → process/  sentiment, skill extraction, turnover proxy
        → SQLite    data/jmsa.db
        → app/      Streamlit reads only from SQLite, never a live source
```

## Setup

Git Bash on Windows, Python 3.11:

```bash
py -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
cp .env.example .env     # then set GNEWS_API_KEY (free key from https://gnews.io)
```

## Get the data

Most source files are too large or not ours to commit, so `data/raw/` (except `company_aliases.csv`) is gitignored. Download these into `data/raw/` yourself:

| Save as | Where from | Licence |
| --- | --- | --- |
| `data/raw/all_reviews.csv` (3.8 GB) | Kaggle dataset [davidgauthier/glassdoor-job-reviews-2](https://www.kaggle.com/datasets/davidgauthier/glassdoor-job-reviews-2), file `all_reviews.csv` | CC BY-NC-SA 4.0 |
| `data/raw/glassdoor_company_ratings.csv` | A Kaggle dataset, downloaded October 2026; the exact dataset page was not recorded. Originally `Glassdoor_Dataset.csv` | unknown; non-commercial coursework only |
| `data/raw/naukri_jobs_merged.csv` | A Kaggle dataset, downloaded October 2026; the exact dataset page was not recorded. Three exports merged and deduplicated: `NaukriData_Data_Science`, `NaukriData_data_analytics`, `Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data` | unknown; non-commercial coursework only |

The ratings file was renamed by hand before the project began, and the three Naukri exports were merged by hand. The merge can't be reproduced: the exports re-downloaded in October 2026 appear to be a later version (about twice the rows, and 522 merged rows are in no export). So use the pinned `naukri_jobs_merged.csv`, whose SHA-256 is in docs/freeze.md. `python -m ingest.merge_naukri --src <folder>` repeats the check without touching the merged file. The loaders check the columns they need: the ratings file needs `company_name, overall_rating, employer_size, industry, review_count`, and the postings file's columns are listed in PRD.md under "The postings snapshot".

Already in the repo: `data/companies.csv` (the library), `data/raw/company_aliases.csv` (name matching), `data/turnover.csv` (published attrition, hand-copied from company reports), and the editable keyword lists `data/themes.csv`, `data/data_role_keywords.csv`, `data/skills.csv`, `data/turnover_keywords.csv` and `data/news_queries.csv`.

## Build the database

Run these once, in this order, from the repo root with the venv active. Each step reads what the one before it wrote.

```bash
python -m jmsa.db init                    # empty database at data/jmsa.db
python -m ingest.load_companies           # the 82 companies
python -m ingest.load_glassdoor_ratings   # ratings for 66 of them
python -m ingest.load_glassdoor_reviews   # streams all_reviews.csv, writes the matched reviews (slow: 3.8 GB)
python -m ingest.load_reviews             # 1.8M matched reviews into the database
python -m process.review_sentiment        # VADER scores and per-company summaries
python -m process.sentiment_checks        # optional: method comparison and TextBlob agreement report
python -m ingest.load_jobs                # Naukri data-role listings
python -m process.skill_counts            # market-wide skill counts
python -m process.turnover_proxy          # review-based turnover proxy
python -m ingest.load_turnover            # published attrition (after the proxy, for its comparison)
python -m ingest.load_news                # GNews, one request per company (needs GNEWS_API_KEY)
python -m process.analysis               # report tables in docs/analysis/ (a few minutes: re-runs TextBlob on 50k)
```

Before a demo, commit, then freeze: `python scripts/freeze.py` writes docs/freeze.md (commit, row counts, source dates, input hashes).

`load_news` uses up to 82 of the free tier's 100 daily requests. If it exits with code 3, the daily quota is used up: rerun it after 00:00 UTC and it resumes where it stopped. It skips companies fetched in the last 24 hours.

Each loader writes a report to `data/raw/` (e.g. `naukri_match_report.txt`). To test a loader without touching `data/jmsa.db`, point `JMSA_DB_PATH` at a throwaway file.

## Run the dashboard

```bash
streamlit run app/app.py    # http://localhost:8501
```

Pages, in the sidebar: Explore (the company library, where the app opens), Company, Market skills, Compare, and About the data, which lists every source with its dates. After reloading the database, restart Streamlit (or press C in the browser) to clear its cache.

## Tests and checks

```bash
pytest                          # all tests; they use in-memory databases, never data/jmsa.db
python scripts/time_pages.py    # each page's load time against the real database (target: under 3 s)
```

Report material: docs/report_notes.md (every number traced to its source), docs/demo_script.md (5-minute walkthrough and viva questions), docs/analysis/ (tables).

## Data and ethics

Only sources whose terms permit this use: a Glassdoor company-ratings snapshot, a Glassdoor review-text snapshot, a Naukri snapshot of Indian data-science and analytics postings, the GNews API (free tier, non-commercial), and companies' own annual reports and filings. No scraping of LinkedIn or Glassdoor. No reviewer names or personal data are stored. Where a source has nothing for a company, the dashboard shows "not available" rather than an estimate. The review dataset is CC BY-NC-SA 4.0, and this project is non-commercial coursework.
