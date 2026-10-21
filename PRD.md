# Job Market Analyser — PRD

Oct 21, 2026 · Arjun

## Overview

The Job Market Analyser is a Streamlit dashboard where a student picks a company and sees, on one page, what it is like to work there and what it hires for. It covers a curated library of large global companies that also hire in India.

**Problem.** Information about employers is scattered across review sites, news, job boards and annual reports. A student comparing ten companies has to open forty tabs and still gets no consistent picture.

**Goal.** For each company in the library, show employee sentiment, turnover, recent coverage, sector, and the data-role skills and postings it advertises in India, and let the user sort and filter across companies.

**Primary user.** A final-year engineering student in India shortlisting employers before placements or off-campus applications.

**Context.** Mini-project for the Web and Social Media Analytics course. The analytics core is web data collection plus sentiment analysis with spaCy, VADER and TextBlob.

## Scope and non-goals

Version 1 covers about 80 companies, with data refreshed by batch scripts before each demo.

**In scope**

- Company library loaded from a CSV (name, sector, HQ, India presence, size band)
- A company rating for every matched company (overall score, review count, employer size, industry) from a Glassdoor ratings snapshot
- Employee review sentiment per company, overall and by theme (pay, culture, work-life balance, management), for the 78 of 82 companies the review dataset covers
- Turnover: published attrition where available, otherwise a clearly labelled proxy
- Recent news articles per company with article sentiment
- Top skills demanded, extracted from a snapshot of Indian data-science and analytics postings
- Count and list of the India data roles posted in that snapshot's period
- Sort and filter across companies; a single company detail page

**Non-goals**

- No live scraping of LinkedIn or Glassdoor, which prohibit it and block bots
- No live job-board APIs. Roles come from a fixed Naukri snapshot, so the dashboard reports roles posted in the snapshot period, never roles open now
- No roles outside data science and analytics; the postings dataset covers only those
- No user accounts, login or saved shortlists
- No real-time updates; data is as fresh as the last pipeline run
- No salary prediction or ML models beyond sentiment and skill extraction
- No job application flow; listings link out to the source

## Features and acceptance criteria

Each feature is done when its acceptance criteria pass against the loaded database.

| # | Feature | User story | Acceptance criteria |
| --- | --- | --- | --- |
| F1 | Company library | As a student, I can browse all tracked companies in one table | Table lists every company in the CSV with sector, HQ country, India cities and size band; loads in under 3 s |
| F2 | Sort and filter | I can narrow the list to what matters to me | Filter by sector, HQ country, has India data roles in the dataset, minimum rating, minimum sentiment, and a required skill; sort by rating, sentiment, data roles posted or attrition |
| F3 | Company page | I can open one company and see everything about it | Page shows sector, HQ, India locations, Glassdoor rating, sentiment summary, turnover, top data-role skills, data roles posted and recent articles |
| F4 | Review sentiment | I can see how employees feel | Average VADER compound score, share positive/neutral/negative, and sentiment by theme; review count and the review date range shown; hidden if fewer than 20 reviews; "not available" for the four companies with no reviews |
| F5 | Turnover | I can see how often people leave | Published attrition % with period and source link, or a proxy labelled "proxy" with its definition; "not available" otherwise |
| F6 | News coverage | I can see what has been written about working there | Up to 10 articles from the last 12 months with title, outlet, date, link and sentiment label |
| F7 | Data-role skills | I can see what skills they hire data people for | Top 10 skills by frequency across that company's data-role postings, as a bar chart; labelled as data-science and analytics roles |
| F8 | Data roles posted | I can see which data roles they advertised in India | Count of that company's India data roles in the dataset, plus a list with title, city, relative post time and link where the row has them; shows the dataset period, not a live refresh date |
| F9 | Compare | I can compare companies side by side | Pick 2–4 companies; one table of their key metrics |

F9 is a stretch goal; F1–F8 are the minimum for submission.

## Data sources

Every field comes from a source we are allowed to use; anything else is shown as unavailable rather than guessed.

| Field | Source | Method | Notes |
| --- | --- | --- | --- |
| Company, sector, HQ, India presence | Our company library CSV (data/companies.csv) | Hand-curated, loaded at start | Sector uses a fixed list of about 15 values |
| Company rating, employer size, industry | data/raw/glassdoor_company_ratings.csv | Match to companies by name; no review text in this file | 3,029 rows. A name can appear for more than one employer, so when several rows match, take the one with the highest review_count |
| Employee review text | data/raw/all_reviews.csv, from the Kaggle dataset davidgauthier/glassdoor-job-reviews-2 (CC BY-NC-SA 4.0) | Match to companies through data/raw/company_aliases.csv, then VADER | 9.9M Glassdoor reviews, of which 1,799,628 match 78 of our 82 companies, 2008 to mid-2023. Cite the licence in the report; it is non-commercial, which this project is |
| Review sentiment | Computed | VADER on pros/cons/summary; TextBlob as a cross-check | Themes via keyword lists (pay, culture, WLB, management) |
| Turnover | Company quarterly results and annual reports | Entered by hand with period and link | Indian IT majors publish attrition; others use a review-based proxy |
| News articles | GNews (https://gnews.io) | Query "<company> employees OR layoffs OR workplace" | The only API in the project. Free tier has a daily limit, so run it once a day at most and cache every response |
| Data roles posted | data/raw/naukri_jobs_merged.csv | Match to companies by name | Indian Naukri postings, data science and analytics only, already deduplicated. 43,630 rows across 8,009 employer names |
| Skills | Computed from the postings’ skills_raw column | spaCy PhraseMatcher against a skills list | skills_raw concatenates skills with no separator ("Text miningCareer developmentdata science"), so it cannot be split on a delimiter — known skills are matched against the string instead. Skills list kept in skills.csv, editable |

**The postings snapshot.** naukri_jobs_merged.csv is three merged Naukri exports. Its columns are job_row_id, job_title, company_name, experience_required, package, locations, skills_raw, post_url, post_time_relative and source_file. Two consequences the loader must respect: post times are relative ("1 Day Ago", "30+ Days Ago") rather than dates, so the file holds no absolute posted date anywhere; and 19,479 of the 43,630 rows — the whole Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data export — have neither post_url nor post_time_relative, so those rows show "not available" for link and post time. What F8 reports is therefore roles posted in the dataset period, not vacancies open today.

**The review snapshot.** all_reviews.csv has no company column and no location column: the employer is embedded in `firm_link` in two different shapes (`Reviews/Oracle-Reviews-E1737.htm` and the full `https://www.glassdoor.com/Reviews/Oracle-Reviews-E1737.htm`), and dates arrive as `Nov 19, 2022`. [ingest/load_glassdoor_reviews.py](ingest/load_glassdoor_reviews.py) streams the 3.8 GB file, matches employers through company_aliases.csv, converts dates to ISO and writes data/raw/glassdoor_reviews_matched.csv. Four companies get no reviews at all and must show "not available": **atlassian**, **workday**, **jpmorgan-chase** and **hdfc-bank**. The last two are deliberate: the dataset's `Chase` and `Hdfc` are different legal entities, so they were rejected rather than guessed. **ltimindtree** is carried by 10,545 pre-merger **Mindtree** reviews, flagged `is_pre_merger` so the page can say so. **intuit** scrapes past the 20-review threshold with just 22 reviews, all from 2022–23, so treat its sentiment as indicative only. Because the source carries no location, reviews.location is always empty and no India-only sentiment is possible from it.

**Matching companies to sources.** Employer names are raw in both snapshots. Of the 82 library companies, 64 match a glassdoor_company_ratings.csv name exactly once lowercased, and 43 match a naukri_jobs_merged.csv name; the rest need aliases. Matching happens once at load time, never by fuzzy-matching names at query time. Every source matches through the one committed alias file, data/raw/company_aliases.csv (company_id, alias_in_dataset). There is no aliases column on companies. When the ratings loader is written, the file gains a source column so each alias applies only to the dataset it was found in.

**Turnover proxy.** Share of a company's reviews that mention leaving, layoffs or attrition. Always labelled "proxy" next to the number. It can be computed for the 78 companies that have review text; the other four show published attrition or "not available".

**Missing data rule.** If a source returns nothing for a company, the dashboard shows "not available" for that field. No field is ever estimated or filled with a default.

## Architecture and stack

The system is a batch pipeline in Python: scripts collect and process data into SQLite, and a Streamlit app reads from it.

Flow: six inputs (the company library CSV, the Glassdoor ratings CSV, the review-text CSV, the Naukri postings CSV, the GNews API and company annual reports) → ingest scripts (one loader per source, run on demand, raw results cached) → process (VADER and TextBlob sentiment, spaCy skill extraction, turnover proxy) → SQLite database → Streamlit dashboard.

Five of the six inputs are local files; GNews is the only live API. Because the dashboard never calls a live source, the demo works even if it is down or rate-limited.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11 or 3.12 | Same language as the NLP libraries |
| Collection | requests, pandas | One REST API and four CSVs; no RSS, so no feedparser |
| NLP | vaderSentiment, TextBlob, spaCy (en_core_web_sm) | Course-specified tools |
| Storage | SQLite via sqlite3 or SQLAlchemy | Single file, no server; switch to Postgres only if teammates need shared access |
| Dashboard | Streamlit + Plotly | Tables, filters and charts with no separate frontend |
| Config | .env with python-dotenv | API keys never committed |

**Repo layout:** `data/` (CSV inputs, SQLite file, `raw/` cache), `ingest/` (one script per source), `process/` (sentiment, skills, proxy), `app/` (Streamlit pages), `jmsa/` (shared config, database helper and schema, imported by the other three), `tests/`, `CLAUDE.md` (rules for the AI tool).

## Data dictionary

Six tables in one SQLite database, all keyed on company_id.

| Table | Columns | Filled by |
| --- | --- | --- |
| companies | company_id (PK, slug), name, sector, hq_country, india_cities, size_band, careers_url, publishes_attrition, glassdoor_rating, glassdoor_review_count, glassdoor_employer_size, glassdoor_industry | Library CSV loader; the glassdoor_* columns by the ratings loader |
| reviews | review_id (PK), company_id, review_date, rating, headline, pros, cons, job_title, location, sentiment_compound, sentiment_label, themes | Review-text loader + sentiment step |
| turnover | company_id, period, attrition_pct, is_proxy, source_url, method_note | Manual entry + proxy step |
| articles | article_id (PK), company_id, title, outlet, published_at, url, summary, sentiment_compound, sentiment_label | News loader + sentiment step |
| jobs | job_id (PK), company_id, title, city, posted_relative, url, skills_raw, source, loaded_at | Naukri loader |
| job_skills | job_id, skill | Skill extraction step |

**Conventions.** company_id is a lowercase slug such as `tata-consultancy-services`. Dates are ISO 8601. sentiment_label is positive when compound ≥ 0.05, negative when ≤ −0.05, otherwise neutral (the standard VADER cut-offs). india_cities and jobs.city are semicolon-separated lists.

**Why jobs has no posted date.** The postings source has none. posted_relative holds the Naukri string as given ("1 Day Ago"), or is empty for the 19,479 rows that lack it, and loaded_at records when the snapshot was loaded. skills_raw keeps the unsplit source string; the skills matched out of it live in job_skills.

## Build order

Build one milestone at a time, run it, and commit before starting the next. A working dashboard exists from milestone 3 onward.

1. **Skeleton.** Repo, folders, requirements.txt, .env template, empty SQLite schema, a Streamlit page that says hello.
2. **Company library.** Load companies.csv into the companies table; F1 table renders.
3. **Company ratings.** Load glassdoor_company_ratings.csv, match names (highest review_count wins), fill the glassdoor_* columns; F1 shows a rating per company.
4. **Reviews and sentiment.** Load glassdoor_reviews_matched.csv into the reviews table, run VADER; F3 page shows sentiment (F4), and "not available" for the four companies without reviews.
5. **Filters.** Sector, country, rating and sentiment filters and sorting (F2).
6. **Data roles and skills.** Naukri loader, then skills.csv and PhraseMatcher over skills_raw, chart top 10 (F8 then F7).
7. **News.** News loader with caching and article sentiment (F6).
8. **Turnover.** Manual attrition entries plus the review-based proxy (F5).
9. **Polish.** Missing-data states, last-refresh dates, compare view if time allows (F9).
10. **Report and demo.** Freeze the database, write up sources and method, rehearse the demo.

## Risks and open questions

The main risk is thin data for some companies; the missing-data rule keeps the dashboard honest when that happens.

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Four companies have no reviews at all | atlassian, workday, jpmorgan-chase and hdfc-bank show no sentiment | Show "not available" per the missing-data rule; the Glassdoor rating still covers some of them |
| Review text stops in mid-2023 | Sentiment is a couple of years behind | Show the review date range on each company page and state the snapshot date in the report |
| Thin or stand-in coverage for a few companies | intuit has 22 reviews (2022–23); ltimindtree is pre-merger Mindtree | Keep the 20-review cut-off, surface the review count next to the score, and label pre-merger rows |
| GNews free-tier limit | Fetches fail mid-run | Cache to the database; run news once a day at most |
| Employer names are raw in both snapshots (8,009 distinct in Naukri) | Data attached to the wrong company or lost | Match once at load time against data/raw/company_aliases.csv; prefer the highest review_count when a ratings name is ambiguous; spot-check |
| Postings carry relative post times, and 19,479 rows carry none | No absolute posted date, and no link for those rows | Report roles posted in the dataset period rather than open now; show "not available" for a missing link or post time |
| Few companies publish attrition | Turnover mostly proxy | Label the proxy clearly; don't rank by turnover without the label |
| VADER misreads sarcasm and Indian English | Noisy sentiment | Cross-check with TextBlob; report agreement rate |

**Ethics and terms.** Use only sources whose terms permit this use. Store no reviewer names or personal data. Cite every dataset and API in the report.

**Open questions**

- [ ] Does the course require a separate frontend, or is Streamlit acceptable?
- [ ] Team split: who owns which loaders?
