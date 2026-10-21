# Job Market Analyser — PRD

Oct 21, 2026 · Arjun

## Overview

The Job Market Analyser is a Streamlit dashboard where a student picks a company and sees, on one page, what it is like to work there and what it hires for. It covers a curated library of large global companies that also hire in India.

**Problem.** Information about employers is scattered across review sites, news, job boards and annual reports. A student comparing ten companies has to open forty tabs and still gets no consistent picture.

**Goal.** For each company in the library, show employee sentiment, turnover, recent coverage, sector, in-demand skills and open roles, and let the user sort and filter across companies.

**Primary user.** A final-year engineering student in India shortlisting employers before placements or off-campus applications.

**Context.** Mini-project for the Web and Social Media Analytics course. The analytics core is web data collection plus sentiment analysis with spaCy, VADER and TextBlob.

## Scope and non-goals

Version 1 covers about 80 companies, with data refreshed by batch scripts before each demo.

**In scope**

- Company library loaded from a CSV (name, sector, HQ, India presence, size band)
- Employee review sentiment per company, overall and by theme (pay, culture, work-life balance, management)
- Turnover: published attrition where available, otherwise a clearly labelled proxy
- Recent news articles per company with article sentiment
- Top skills demanded, extracted from job descriptions
- Count and list of open roles in India
- Sort and filter across companies; a single company detail page

**Non-goals**

- No live scraping of LinkedIn or Glassdoor, which prohibit it and block bots
- No user accounts, login or saved shortlists
- No real-time updates; data is as fresh as the last pipeline run
- No salary prediction or ML models beyond sentiment and skill extraction
- No job application flow; listings link out to the source

## Features and acceptance criteria

Each feature is done when its acceptance criteria pass against the loaded database.

| # | Feature | User story | Acceptance criteria |
| --- | --- | --- | --- |
| F1 | Company library | As a student, I can browse all tracked companies in one table | Table lists every company in the CSV with sector, HQ country, India cities and size band; loads in under 3 s |
| F2 | Sort and filter | I can narrow the list to what matters to me | Filter by sector, HQ country, has open India roles, minimum sentiment, and a required skill; sort by sentiment, open roles or attrition |
| F3 | Company page | I can open one company and see everything about it | Page shows sector, HQ, India locations, sentiment summary, turnover, top skills, open roles and recent articles |
| F4 | Review sentiment | I can see how employees feel | Average VADER compound score, share positive/neutral/negative, and sentiment by theme; review count shown; hidden if fewer than 20 reviews |
| F5 | Turnover | I can see how often people leave | Published attrition % with period and source link, or a proxy labelled "proxy" with its definition; "not available" otherwise |
| F6 | News coverage | I can see what has been written about working there | Up to 10 articles from the last 12 months with title, outlet, date, link and sentiment label |
| F7 | Skills demanded | I can see what skills they hire for | Top 10 skills by frequency across that company's job descriptions, as a bar chart |
| F8 | Open roles | I can see if they are hiring in India now | Count of open India roles plus a list with title, city, posted date and link; shows last refresh date |
| F9 | Compare | I can compare companies side by side | Pick 2–4 companies; one table of their key metrics |

F9 is a stretch goal; F1–F8 are the minimum for submission.

## Data sources

Every field comes from a source we are allowed to use; anything else is shown as unavailable rather than guessed.

| Field | Source | Method | Notes |
| --- | --- | --- | --- |
| Company, sector, HQ, India presence | Our company library CSV (data/companies.csv) | Hand-curated, loaded at start | Sector uses a fixed list of about 15 values |
| Employee reviews | Kaggle Glassdoor reviews datasets | Download once, match to companies by name | Historical snapshot; state the dataset and its date range in the report |
| Review sentiment | Computed | VADER on pros/cons/headline; TextBlob as a cross-check | Themes via keyword lists (pay, culture, WLB, management) |
| Turnover | Company quarterly results and annual reports | Entered by hand with period and link | Indian IT majors publish attrition; others use a review-based proxy |
| News articles | GNews or NewsAPI, or Google News RSS | Query "<company> employees OR layoffs OR workplace" | Free tiers have daily limits; cache results |
| Open roles | Adzuna API (India), Greenhouse and Lever public job boards | Pull by company name or board ID | Only some companies use Greenhouse or Lever; record which in the CSV |
| Skills | Computed from job descriptions | spaCy PhraseMatcher against a skills list | Skills list kept in skills.csv, editable |

**Turnover proxy.** Share of a company's reviews from the last two years that mention leaving, layoffs or attrition. Always labelled "proxy" next to the number.

**Missing data rule.** If a source returns nothing for a company, the dashboard shows "not available" for that field. No field is ever estimated or filled with a default.

## Architecture and stack

The system is a batch pipeline in Python: scripts collect and process data into SQLite, and a Streamlit app reads from it.

Flow: five sources (company CSV, Kaggle reviews, jobs APIs, news API, annual reports) → ingest scripts (one loader per source, run on demand, raw results cached) → process (VADER and TextBlob sentiment, spaCy skill extraction, turnover proxy) → SQLite database → Streamlit dashboard.

Because the dashboard never calls a live source, the demo works even if an API is down or rate-limited.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11 or 3.12 | Same language as the NLP libraries |
| Collection | requests, feedparser, pandas | Simple API calls, RSS and CSV loading |
| NLP | vaderSentiment, TextBlob, spaCy (en_core_web_sm) | Course-specified tools |
| Storage | SQLite via sqlite3 or SQLAlchemy | Single file, no server; switch to Postgres only if teammates need shared access |
| Dashboard | Streamlit + Plotly | Tables, filters and charts with no separate frontend |
| Config | .env with python-dotenv | API keys never committed |

**Repo layout:** `data/` (CSV inputs, SQLite file, `raw/` cache), `ingest/` (one script per source), `process/` (sentiment, skills, proxy), `app/` (Streamlit pages), `jmsa/` (shared config, database helper and schema, imported by the other three), `tests/`, `CLAUDE.md` (rules for the AI tool).

## Data dictionary

Six tables in one SQLite database, all keyed on company_id.

| Table | Columns | Filled by |
| --- | --- | --- |
| companies | company_id (PK, slug), name, sector, hq_country, india_cities, size_band, ats_type, ats_board_id, careers_url, publishes_attrition | Library CSV loader |
| reviews | review_id (PK), company_id, review_date, rating, headline, pros, cons, job_title, location, sentiment_compound, sentiment_label, themes | Kaggle loader + sentiment step |
| turnover | company_id, period, attrition_pct, is_proxy, source_url, method_note | Manual entry + proxy step |
| articles | article_id (PK), company_id, title, outlet, published_at, url, summary, sentiment_compound, sentiment_label | News loader + sentiment step |
| jobs | job_id (PK), company_id, title, city, posted_at, url, description, source, fetched_at | Jobs loaders |
| job_skills | job_id, skill | Skill extraction step |

**Conventions.** company_id is a lowercase slug such as `tata-consultancy-services`. Dates are ISO 8601. sentiment_label is positive when compound ≥ 0.05, negative when ≤ −0.05, otherwise neutral (the standard VADER cut-offs). india_cities is a semicolon-separated list.

## Build order

Build one milestone at a time, run it, and commit before starting the next. A working dashboard exists from milestone 3 onward.

1. **Skeleton.** Repo, folders, requirements.txt, .env template, empty SQLite schema, a Streamlit page that says hello.
2. **Company library.** Load companies.csv into the companies table; F1 table renders.
3. **Reviews and sentiment.** Load the Kaggle dataset, match company names, run VADER; F3 page shows sentiment (F4).
4. **Filters.** Sector, country and sentiment filters and sorting (F2).
5. **Open roles.** Adzuna loader, then Greenhouse/Lever for companies that use them (F8).
6. **Skills.** Build skills.csv, run PhraseMatcher over job descriptions, chart top 10 (F7).
7. **News.** News loader with caching and article sentiment (F6).
8. **Turnover.** Manual attrition entries plus the review-based proxy (F5).
9. **Polish.** Missing-data states, last-refresh dates, compare view if time allows (F9).
10. **Report and demo.** Freeze the database, write up sources and method, rehearse the demo.

## Risks and open questions

The main risk is thin data for some companies; the missing-data rule keeps the dashboard honest when that happens.

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Kaggle reviews don't cover every company | Empty sentiment for some rows | Hide sentiment below 20 reviews; say so in the report |
| Reviews are a historical snapshot | Sentiment may be out of date | Show the review date range on each company page |
| News API free-tier limits | Fetches fail mid-run | Cache to the database; run news once a day at most |
| Company name mismatches across sources | Data attached to the wrong company or lost | Match on company_id with an aliases column if needed; spot-check |
| Few companies publish attrition | Turnover mostly proxy | Label the proxy clearly; don't rank by turnover without the label |
| VADER misreads sarcasm and Indian English | Noisy sentiment | Cross-check with TextBlob; report agreement rate |

**Ethics and terms.** Use only sources whose terms permit this use. Store no reviewer names or personal data. Cite every dataset and API in the report.

**Open questions**

- [ ] Does the course require a separate frontend, or is Streamlit acceptable?
- [ ] Which Kaggle Glassdoor dataset gives the best coverage of the library?
- [ ] Team split: who owns which loaders?
