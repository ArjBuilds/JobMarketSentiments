# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Milestones 1 (skeleton), 2 (company library), 3 (Glassdoor ratings), 4 (reviews and sentiment) and 5 (filters) are done:
- `python -m ingest.load_companies` loads companies.csv into `companies`, and `python -m ingest.load_glassdoor_ratings` fills its `glassdoor_*` columns. The Library page renders the F1 table with a rating per company.
- `python -m ingest.load_reviews` loads the 1.8M matched reviews. `python -m process.review_sentiment` scores them and fills `review_summary`. The Company page shows F4 sentiment for a selected company.
- `python -m process.sentiment_checks` writes the method comparison and the TextBlob agreement rate for the report.
- The Library page filters and sorts (F2) through [jmsa/library.py](jmsa/library.py), which has no Streamlit code so the tests call it directly. Add the M8 attrition sort as a `SORT_KEYS` entry there.

Milestone 6 is split in two. Stage A (data roles, F8) is built:
- `python -m ingest.load_jobs` filters titles, matches employers, verifies links and replaces `jobs`; it writes `data/raw/naukri_match_report.txt`. The Company page shows F8 through [jmsa/jobs.py](jmsa/jobs.py), and the Library page has the data-roles column, filter and sort.

Stage B (market-wide skills, F7) is built:
- `python -m process.skill_counts` matches data/skills.csv against skills_raw and replaces `skill_counts`; it writes `data/raw/skill_counts_report.txt`, and `--check N` writes a hand-check sample instead. The Market skills page shows F7 through [jmsa/skills.py](jmsa/skills.py); the Company page shows "not available" with a pointer.

Milestone 8 (turnover, F5) is split in two. Stage A (the review-based proxy) is built:
- `python -m process.turnover_proxy` counts reviews whose headline or cons match [data/turnover_keywords.csv](data/turnover_keywords.csv) in the window and replaces the proxy rows of `turnover`; it writes `data/raw/turnover_proxy_report.txt`, and `--check N` writes a hand-check sample instead. The Company page shows F5 and the Library page two proxy columns through [jmsa/turnover.py](jmsa/turnover.py). Stage B (published attrition from data/turnover.csv, and the Library attrition sort) is next.

Milestone 7 (news, F6) is built:
- `python -m ingest.load_news` sends one GNews request per company, using its query in [data/news_queries.csv](data/news_queries.csv), keeps the articles that name the company, dedupes them, keeps the 10 newest and scores them; it writes `data/raw/news_fetch_report.txt`. The Company page shows F6 through [jmsa/news.py](jmsa/news.py).

Five files are on disk, and none of them is a live job API:

- [data/companies.csv](data/companies.csv) — 82 curated companies, the spine everything joins to.
- `data/raw/glassdoor_company_ratings.csv` — 3,029 rows of overall rating, review count, employer size and industry. No review text.
- `data/raw/all_reviews.csv` — 9.9M Glassdoor reviews with text (davidgauthier/glassdoor-job-reviews-2, CC BY-NC-SA 4.0). 1,799,628 of them match 78 of our 82 companies, 2008 to mid-2023. This replaced employee_reviews.csv, which is still on disk but no longer used.
- `data/raw/company_aliases.csv` — the name mappings that matching depends on (`company_id,alias_in_dataset,source`): 80 for review text, 6 for ratings. Committed, unlike everything else in `raw/`.
- `data/raw/naukri_jobs_merged.csv` — 43,630 Indian Naukri postings in three exports, already deduplicated. Its columns are misaligned row by row, and many titles aren't data roles; see the PRD's "The postings snapshot" before using any column.

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

Nine tables:
- Six source tables: `companies`, `reviews`, `turnover`, `articles`, `jobs` and `job_skills`. All are keyed on `company_id` except `job_skills`, which reaches companies through `jobs`.
- Two derived tables: `review_summary`, with per-company review figures for `all` and `2020-2023` (pages read sentiment from it, never by aggregating `reviews` live), and `skill_counts`, market-wide skill counts per scope, keyed on no company.
- `news_fetches`, one row per company: its last GNews fetch (`fetched_at`, query, counts) and the cached response with every article's `content` removed. It drives the 24-hour skip and "news fetched on".
- `job_skills` is always empty: no skill can be tied to a posting.

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
python -m ingest.load_jobs                     # full replace of jobs; rerun after editing
                                               # data_role_keywords.csv or naukri aliases
python -m process.skill_counts [--check 50]    # full replace of skill_counts; rerun after
                                               # editing skills.csv. --check writes a sample only
python -m ingest.load_news [--company ID] [--limit N] [--refresh]
                                               # GNews; skips companies fetched in the last 24 h.
                                               # Exit code 3 = daily quota reached; rerun to resume
python -m process.turnover_proxy [--check 50]  # replaces only the proxy rows of turnover; rerun
                                               # after editing turnover_keywords.csv. --check writes a sample only
python -m ingest.load_news --from-cache        # re-select from cached responses, 0 requests;
                                               # rerun after editing gnews aliases

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
- `careers_url` in companies.csv is the company's official, company-run careers site (own domain or its official careers domain), https only, never a third-party job board (e.g. pgcareers.com, wellsfargojobs.com fit); the India page where one exists, else global. load_companies rejects a value not starting with `https://`. The Company page shows it as "Current openings", separate from the historical F8 section.
- `sector` comes from a fixed list of 15 values already present in companies.csv — don't introduce new ones ad hoc.
- Each source is matched to the library once, at load time, never by fuzzy-matching at query time. Every source uses the committed `data/raw/company_aliases.csv`, the only alias store (`companies` has no aliases column). Its `source` column (`glassdoor_reviews`, `glassdoor_ratings`, `naukri`) keeps each alias to the dataset it was found in. Read it through [jmsa/aliases.py](jmsa/aliases.py), which also holds the shared `normalise()`. 43 companies match a Naukri name exactly, so aliases carry the rest.
- Naukri alias rule: a company's own India operations and service centres count for it; recruitment agencies, namesakes and majority-owned businesses in a different line of work (ICICI Prudential, HDFC Life, Tata Motors Finance, Siemens Healthcare) don't. Checked rejections live in `REJECTED_NAMES` in [ingest/load_jobs.py](ingest/load_jobs.py) and can never match.
- When several `glassdoor_company_ratings.csv` rows match one company — the same name is used by different employers — take the row with the highest `review_count`.
- Ratings coverage: 66 of 82 companies (60 by exact name, 6 by alias). 16 show "not available": the file has only subsidiaries or regional arms for tata-consultancy-services, infosys, accenture, capgemini, ibm, deloitte, amazon and walmart; no row at all for cognizant, linkedin, blackrock and visa; **wipro**, **ey** and **tata-motors** are exact matches deliberately rejected (`REJECTED` in the ratings loader) because the rows have low review counts and a foreign head office, i.e. regional pages; and **mercedes-benz** has no ratings alias because its only row, Mercedes-Benz International (Motor Vehicle Dealers, 3 offices), is a sales arm, not the group. Its glassdoor_reviews alias is unaffected. Employer size is not a reason to reject — that column is unreliable across the file. The loader's report flags, without changing, big companies (size band 50k-200k or 200k+) with under 5,000 ratings reviews as "check: possibly a regional page".
- `jobs` holds no posted date: the Naukri file has only relative strings (`posted_relative`, e.g. "1 Day Ago"). Never convert these into dates.
- Naukri columns: only `job_title` and `company_name` reliably belong together. A row's `url`, `posted_relative` and `city` are kept only when its link's slug starts with the title and then names the employer; `city` is read from that slug. `url` and `posted_relative` drive verification and dedup but are never displayed: the 2023 links have expired and "1 Day Ago" would read as current. F8 shows title, employer (as posted) and city only. Never store `locations`, `experience_required`, `package` or `skills_raw` against a posting.
- A posting is a data role only if its title passes the include/exclude keywords in [data/data_role_keywords.csv](data/data_role_keywords.csv). "business analyst" is excluded unless the title also has a data-specific include keyword (`OVERRIDABLE_EXCLUDES` and `GENERIC_INCLUDES` in the loader).
- `jobs` holds distinct listings, not rows: matched rows are deduplicated at load time, verified rows by Naukri job ID and unverified rows by (employer as posted, title), with an unverified row dropped when a verified row has the same pair. Same-title listings without a verified link count once, so every count is a lower bound and is shown with that note.
- `skills_raw` concatenates skills with no separator (`Text miningCareer developmentdata science`), so it cannot be split on a delimiter. Match known skills from skills.csv against the string with the spaCy PhraseMatcher on `spacy.blank("en")`. Its skills belong to other rows' postings, so count them only per export, never per company; the headline pools the two data-science exports. Count each distinct skills_raw string once: lists were copied when listings were rescraped, and the two data-science exports overlap (86%).
- News: [data/news_queries.csv](data/news_queries.csv) (`company_id,query`) holds one GNews query per company, at most 200 characters: the quoted name, `AND (employees OR workers OR staff OR layoffs OR "job cuts" OR hiring OR headcount OR workplace OR culture OR "return to office")`. Never add `jobs` (Steve Jobs). A name the press capitalises unambiguously (Intel, SAP, Intuit, EY) goes in bare and relies on the case-sensitive relevance check; a name that title-case headlines or a common phrase make ambiguous even capitalised (Target, Shell, Visa, LinkedIn, Apple, Meta, Oracle, Uber, LTM, TCS) keeps a group of narrower quoted phrases. The terms take 125 characters, so a name group has at most 70. Always use parentheses: GNews binds OR tighter than AND. An article is kept only if its title or description names the company, its library name or a `gnews` alias, as a whole word with matching case. Never add bare `LTM` as an alias: it also means "last twelve months". The free tier searches only 30 days and returns 10 articles a request, so F6 is labelled "up to 10 most recent articles published in the 30 days before the fetch date", never "last 12 months". Article `content` is stored nowhere, not even in the cached response.
- data/skills.csv is `skill,type,synonym`; only the synonym is matched. Every skill has exactly one type, `tool` (a named product or language) or `method` (a technique). Never list `go` or `bi` as a synonym: they match ordinary words.

## Rules the data layer must hold to

- **Missing-data rule.** If a source returns nothing for a company, the field shows "not available". Never estimate, default or backfill a value.
- Hide review sentiment for a company with fewer than 20 reviews.
- Review-text sentiment (F4) covers 78 of the 82 companies. **atlassian**, **workday**, **jpmorgan-chase** and **hdfc-bank** have no reviews and must show "not available" — the last two because the dataset's `Chase` and `Hdfc` are different companies and were rejected rather than guessed.
- **ltimindtree**'s 10,545 reviews are pre-merger **Mindtree** rows, flagged `is_pre_merger`. Say so wherever they are shown. Its display name is "LTM (formerly LTIMindtree)"; its company_id stays `ltimindtree`, and its ratings row is reached by the `LTIMindtree` alias, not by name.
- **intuit** clears the 20-review threshold with only 22 reviews, all 2022–23. Always show the review count beside a sentiment score.
- The review source has no location column, so `reviews.location` stays empty and nothing India-specific can be derived from review text.
- Glassdoor **ratings** and review **text** are different sources with different coverage. A company can have a rating and no sentiment; don't present one as the other.
- Turnover is published attrition (with period, definition, entity and source URL) and/or the review-based proxy, each under its own heading. A proxy row has `is_proxy = 1`, stores `proxy_share`, never `attrition_pct` (a CHECK enforces it), and is surfaced as "proxy" in the UI.
- The proxy is reviews dated 2021-04-01 to 2023-03-31 (`WINDOW_*` in [jmsa/turnover.py](jmsa/turnover.py)) whose headline or cons match a keyword, shown "per 100 reviews", never with a % sign, with its split (leaving/attrition, layoffs). Never search pros: there "leave" is time off and "no layoffs" is praise. Never sort or rank by the proxy, and never add bare `leave`, `left`, `job security`, `switch`, `exit`, `notice period`, `restructuring` (28% precision, mostly reorgs) or `fired` (80%, mostly "should be fired"/"hard to get fired" and attendance-point dismissals) as keywords. Re-run `--check 50` and read it after editing the keywords.
- No live scraping of LinkedIn or Glassdoor — their terms forbid it. Reviews come from the CSV snapshots above.
- There are no live job APIs. Roles and skills (F7, F8) come only from `naukri_jobs_merged.csv`, which is Indian data-science and analytics postings. Label these views as data roles, and label counts as distinct data-role listings in the dataset snapshot (collected in or after late October 2023), never "open now", with the lower-bound note beside them.
- Store no reviewer names or personal data.
- GNews is the only API in the project. Cache every response into SQLite (`news_fetches.response_json`); news runs at most once a day against free-tier limits (100 requests a day, reset at 00:00 UTC; 1 a second). The key goes only in request parameters and is never printed, logged or stored: requests puts it in the URL, so exception text is never shown, and messages go through `redact()`.

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