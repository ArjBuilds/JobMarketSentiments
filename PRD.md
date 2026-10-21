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
| F2 | Sort and filter | I can narrow the list to what matters to me | Filter by sector, HQ country, has India data roles in the dataset, minimum rating, minimum sentiment and minimum reviews scored; sort by name, rating, sentiment, reviews scored, data roles posted or attrition, with missing values last in either direction. Sentiment and review counts use one review period (all time or 2020–2023), chosen on the page. A minimum excludes companies with no value for it unless the user includes them. No required-skill filter: the postings' skills can't be tied to an employer (see "The postings snapshot") |
| F3 | Company page | I can open one company and see everything about it | Page shows sector, HQ, India locations, Glassdoor rating, sentiment summary, turnover, top data-role skills, data roles posted and recent articles, plus a "Current openings" link to the company's careers site, kept apart from the historical F8 section |
| F4 | Review sentiment | I can see how employees feel | Average VADER compound score, share positive/neutral/negative, and sentiment by theme; review count and the review date range shown; hidden if fewer than 20 reviews; "not available" for the four companies with no reviews |
| F5 | Turnover | I can see how often people leave | Published attrition % with period and source link, or a proxy labelled "proxy" with its definition; "not available" otherwise |
| F6 | News coverage | I can see what has been written about working there | Up to 10 articles from the last 12 months with title, outlet, date, link and sentiment label |
| F7 | Data-role skills | I can see what skills data people are hired for | Top 10 skills by frequency across Indian data-science postings in the snapshot, as a bar chart, labelled as market-wide rather than the company's own; per-company skills show "not available" because the source doesn't tie skills to an employer |
| F8 | Data roles posted | I can see which data roles they advertised in India | Count of that company's India data roles in the dataset, plus a list with title, employer (as posted) and city, the city only where the row's link is verified; "not available" for a company with none; introduced as "Data-role listings this company posted in the dataset snapshot (late 2023). Historical, not current openings.", with a note that the count is a lower bound. Links and relative post times are stored but not shown: the 2023 links have expired and "1 Day Ago" would read as current |
| F9 | Compare | I can compare companies side by side | Pick 2–4 companies; one table of their key metrics |

F9 is a stretch goal; F1–F8 are the minimum for submission.

## Data sources

Every field comes from a source we are allowed to use; anything else is shown as unavailable rather than guessed.

| Field | Source | Method | Notes |
| --- | --- | --- | --- |
| Company, sector, HQ, India presence | Our company library CSV (data/companies.csv) | Hand-curated, loaded at start | Sector uses a fixed list of about 15 values |
| Company rating, employer size, industry | data/raw/glassdoor_company_ratings.csv | Match to companies by name; no review text in this file | 3,029 rows. A name can appear for more than one employer, so when several rows match, take the one with the highest review_count |
| Employee review text | data/raw/all_reviews.csv, from the Kaggle dataset davidgauthier/glassdoor-job-reviews-2 (CC BY-NC-SA 4.0) | Match to companies through data/raw/company_aliases.csv, then VADER | 9.9M Glassdoor reviews, of which 1,799,628 match 78 of our 82 companies, 2008 to mid-2023. Cite the licence in the report; it is non-commercial, which this project is |
| Review sentiment | Computed | VADER on pros/cons/summary; TextBlob as a cross-check | Each part is scored separately and combined as mean(headline, mean(pros, cons)), the method that tracked star ratings best on a 20k sample. Themes (pay, culture, WLB, management) via keyword lists in data/themes.csv; a theme's score is the VADER score of the section that mentions it. TextBlob runs on a seeded 50k sample, and the label agreement rate goes in the report |
| Turnover | Company quarterly results and annual reports | Entered by hand with period and link | Indian IT majors publish attrition; others use a review-based proxy |
| News articles | GNews (https://gnews.io) | Query "<company> employees OR layoffs OR workplace" | The only API in the project. Free tier has a daily limit, so run it once a day at most and cache every response |
| Data roles posted | data/raw/naukri_jobs_merged.csv | Title filter (data/data_role_keywords.csv), then match to companies by name through data/raw/company_aliases.csv | Indian Naukri postings, deduplicated row by row but not by listing. 43,630 rows across 8,009 employer names; 24,726 have a data-role title; 2,471 of those match 53 library companies and collapse to 976 distinct listings |
| Skills | Computed from the postings’ skills_raw column, market-wide | spaCy PhraseMatcher against a skills list | skills_raw concatenates skills with no separator ("Text miningCareer developmentdata science"), so known skills are matched against the string. Skills list kept in data/skills.csv, editable. skills_raw belongs to other rows' postings, so counts are market-wide only, scoped by export (below) |

**The postings snapshot.** naukri_jobs_merged.csv is three merged Naukri exports (source_file): NaukriData_Data_Science (11,465 rows), NaukriData_data_analytics (12,686) and Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data (19,479). Its columns are job_row_id, job_title, company_name, experience_required, package, locations, skills_raw, post_url, post_time_relative and source_file.

*Its columns don't line up row by row.* job_title and company_name belong together in all three exports. The other columns often come from a different posting. A Naukri link's slug reads `<title>-<employer>-<cities>-<x>-to-<y>-years-<job id>`, which allows a check. In the analytics export the slug agrees with company_name 97% of the time and with job_title 90%. In the Data_Science export it agrees for rows 1–200 and almost never after (3%): 9,731 links there belong to other employers' postings. locations and experience_required agree with the slug no more than chance allows. skills_raw is unrelated to the title in every export: a title containing "Python" lists Python in its skills 7–10% of the time, the same as the base rate, and no row offset fixes it. So:

- The loader keeps a row's url, post time and city only when its link is **verified**: the slug starts with the row's title and then names its employer (as posted, by its library name, or by a legal name the loader lists, e.g. PwC → Pricewaterhouse Coopers). The city is read from the slug after the employer. 265 of the 2,471 matched postings verify; the rest show "not available" for city. The url and post time are stored for verification and dedup but never displayed. A title-only check would not do, because "Data Analyst" starts thousands of other employers' slugs.
- locations, experience_required, package and skills_raw are not stored against a posting.
- Skills (F7) can't be attributed to a company. Counting them over a whole export is still valid, because shuffling rows within an export doesn't change which skills it contains. The count is scoped to the two data-science exports, with per-export counts reported first. The title filter doesn't help here: the skills on a kept row belong to some other posting, which may not be a data role.

*Not every posting is a data role.* Only 38% of the analytics export's titles name a data role ("Telecaller", "SEO Expert" and "Sales trainee" are in it), against 87–91% in the other two. ingest/load_jobs.py keeps a posting only if its title has an include keyword and no exclude keyword from data/data_role_keywords.csv (editable; e.g. "data" is included and "data entry" excluded). That drops 18,904 rows. "Business analyst" is excluded, because most such titles are requirements roles, unless the title also has a data-specific include keyword (any but analyst, analysts, analysis, analytical and science), so "Business Analyst - Data Science" and "Senior Business Analyst - BI" are kept and plain "Senior Business Analyst" is not. snowflake, databricks and spark are include keywords. Bare "model" and "reporting" are not keywords: they mostly add "Hybrid Model" and HR or field-reporting titles, and the analyst and modelling titles they would add are caught by other keywords.

*Repeated listings.* The file was deduplicated on whole rows, but the same title and employer were copied onto many rows whose other columns differ: American Express's "Senior Manager - Data Science" appears 394 times with 52 locations and 167 links, of which 2 verify. The loader deduplicates the matched rows: one verified row per Naukri job ID (two same-title rows with different IDs are two listings, as with IBM's 13 "Process Analyst" IDs); one unverified row per employer as posted and normalised title, keeping the lowest job_row_id; and an unverified row is dropped when a verified row has the same employer and title. 2,471 matched rows become 976 listings (265 verified, 711 not). Because same-title listings without a verified link count once, the count is a lower bound and is labelled as such. The match report shows each company's rows before and after dedup.

*Dates.* Post times are relative ("1 Day Ago", "30+ Days Ago") and stored as given, never converted to dates. "Starts in 1-3 months"-style values are internship start dates, so they are stored as empty. The file records no collection date. But the 12-digit Naukri job ID in each link starts with a DDMMYY date, and none is later than 28 Oct 2023, so F8 is described as the late-2023 snapshot, and its caption says it was collected in or after late October 2023 (dated from two of three exports; the third is undated). The IDs don't date individual postings, because reposted listings keep IDs going back to 2015. 21,014 rows have no link (all 19,479 of the third export plus 1,535 others) and 19,481 have no post time. What F8 reports is roles posted in the dataset period, not vacancies open today.

**The review snapshot.** all_reviews.csv has no company column and no location column: the employer is embedded in `firm_link` in two different shapes (`Reviews/Oracle-Reviews-E1737.htm` and the full `https://www.glassdoor.com/Reviews/Oracle-Reviews-E1737.htm`), and dates arrive as `Nov 19, 2022`. [ingest/load_glassdoor_reviews.py](ingest/load_glassdoor_reviews.py) streams the 3.8 GB file, matches employers through company_aliases.csv, converts dates to ISO and writes data/raw/glassdoor_reviews_matched.csv. Four companies get no reviews at all and must show "not available": **atlassian**, **workday**, **jpmorgan-chase** and **hdfc-bank**. The last two are deliberate: the dataset's `Chase` and `Hdfc` are different legal entities, so they were rejected rather than guessed. **ltimindtree** is carried by 10,545 pre-merger **Mindtree** reviews, flagged `is_pre_merger` so the page can say so. **intuit** scrapes past the 20-review threshold with just 22 reviews, all from 2022–23, so treat its sentiment as indicative only. Because the source carries no location, reviews.location is always empty and no India-only sentiment is possible from it. ingest/load_reviews.py copies the matched CSV into the reviews table, and process/review_sentiment.py scores it and fills review_summary. The 34 reviews with no parseable date are completely empty (no rating or text), so they are kept with review_date and sentiment NULL and count in no figure. The sub-ratings are stored too. Cells holding scraped codes such as `10u0eun` instead of 1–5 are stored as NULL. recommend, ceo_approval and business_outlook keep Glassdoor's letter codes v, r, o and x. Their meanings (positive, mild, no opinion, negative) are unverified; check them against the Kaggle dataset card.

**Matching companies to sources.** Employer names are raw in both snapshots. Of the 82 library companies, 63 match a glassdoor_company_ratings.csv name exactly once lowercased, and 43 match a naukri_jobs_merged.csv name; the rest need aliases. Matching happens once at load time, never by fuzzy-matching names at query time. Every source matches through the one committed alias file, data/raw/company_aliases.csv (company_id, alias_in_dataset, source). There is no aliases column on companies. The source column (glassdoor_reviews, glassdoor_ratings, and naukri once the jobs loader is written) makes each alias apply only to the dataset it was found in. The ratings loader matches 66 of the 82 companies, 60 by exact name and 6 through aliases. ltimindtree is one of the six: its display name is "LTM (formerly LTIMindtree)" after the 2025 rebrand, so its ratings row, LTIMindtree, is reached by alias. The other 16 show "not available": eight have only a subsidiary or regional-arm row (tata-consultancy-services, infosys, accenture, capgemini, ibm, deloitte, amazon, walmart); four have no row (cognizant, linkedin, blackrock, visa); the exact matches for **wipro**, **ey** and **tata-motors** are rejected because those rows have low review counts and a foreign head office (Dresden, Riyadh and Coventry), which marks a regional page; and **mercedes-benz** has no ratings alias because the file's only candidate, Mercedes-Benz International (industry Motor Vehicle Dealers, 3 office locations), is a sales arm rather than the Mercedes-Benz Group. Its review-text alias is a separate row and still applies.

For the Naukri postings the rule is different, because F8 is about hiring in India: a company's own India operations and service centres count for it (KPMG Global Services, PwC Service Delivery Center, Amazon Web Services, Google Operations Center, Pepsi Foods for PepsiCo, Hindustan Unilever for Unilever, Citicorp Finance for Citi, Reliance Retail and Jio for the Reliance conglomerate). Recruitment agencies, namesakes and majority-owned businesses in a different line of work do not (ICICI Prudential Life and ICICI Securities, HDFC Life, HDFC ERGO and HDFC Securities, Tata Motors Finance, Siemens Healthcare). These and other checked rejections are listed in `REJECTED_NAMES` in the loader, with a reason, and can never match. 43 companies match by exact name and 24 aliases add the rest. 53 companies have data-role postings. The other 29 show "not available": most have no postings in the file under any name, and airbus, icici-bank, samsung and texas-instruments have only non-data titles. The loader writes a match report with difflib suggestions for the unmatched; none are accepted automatically.

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

Seven tables in one SQLite database: six source tables, all keyed on company_id, plus review_summary, which is derived from reviews.

| Table | Columns | Filled by |
| --- | --- | --- |
| companies | company_id (PK, slug), name, sector, hq_country, india_cities, size_band, careers_url, publishes_attrition, glassdoor_rating, glassdoor_review_count, glassdoor_employer_size, glassdoor_industry | Library CSV loader; the glassdoor_* columns by the ratings loader. careers_url is the company's official, company-run careers site (own domain or its official careers domain), https only, never a third-party job board; the India page where one exists, else global. The loader rejects a value that doesn't start with https:// |
| reviews | review_id (PK, `gd-0000001`), company_id, review_date, rating, headline, pros, cons, job_title, location, is_pre_merger, recommend, ceo_approval, business_outlook, career_opportunities, compensation_and_benefits, senior_management, work_life_balance, culture_and_values, diversity_and_inclusion, sentiment_compound, sentiment_label, themes, theme_pay, theme_culture, theme_wlb, theme_management | Review-text loader + sentiment step |
| review_summary | company_id, period (`all` or `2020-2023`), review_count, first_date, last_date, avg_compound, share_positive, share_neutral, share_negative, pay/culture/wlb/management _count and _compound, pre_merger_count | Sentiment step, so a company page reads one row instead of aggregating up to 163k reviews |
| turnover | company_id, period, attrition_pct, is_proxy, source_url, method_note | Manual entry + proxy step |
| articles | article_id (PK), company_id, title, outlet, published_at, url, summary, sentiment_compound, sentiment_label | News loader + sentiment step |
| jobs | job_id (PK, `nk-<job_row_id>`), company_id, employer_name, title, city, posted_relative, url, skills_raw (always empty, see "The postings snapshot"), source, loaded_at | Naukri loader |
| job_skills | job_id, skill | Skill extraction step |

**Conventions.** company_id is a lowercase slug such as `tata-consultancy-services`. Dates are ISO 8601. sentiment_label is positive when compound ≥ 0.05, negative when ≤ −0.05, otherwise neutral (the standard VADER cut-offs). india_cities and jobs.city are semicolon-separated lists; jobs.city is read from the verified link.

**Why jobs has no posted date.** The postings source has none. posted_relative holds the Naukri string as given ("1 Day Ago"), or is empty when the row has none or its link isn't verified, and loaded_at records when the snapshot was loaded. skills_raw is left empty, because the source's skills belong to other rows; market-wide skill counts are read from the CSV.

## Build order

Build one milestone at a time, run it, and commit before starting the next. A working dashboard exists from milestone 3 onward.

1. **Skeleton.** Repo, folders, requirements.txt, .env template, empty SQLite schema, a Streamlit page that says hello.
2. **Company library.** Load companies.csv into the companies table; F1 table renders.
3. **Company ratings.** Load glassdoor_company_ratings.csv, match names (highest review_count wins), fill the glassdoor_* columns; F1 shows a rating per company.
4. **Reviews and sentiment.** Load glassdoor_reviews_matched.csv into the reviews table, run VADER; F3 page shows sentiment (F4), and "not available" for the four companies without reviews.
5. **Filters.** Sector, country, rating and sentiment filters and sorting (F2).
6. **Data roles and skills.** Naukri loader with title filter, aliases and link verification (F8, and the F2 data-role filter and sort), then skills.csv and PhraseMatcher over skills_raw, a market-wide top-10 chart (F7).
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
| Employer names are raw in both snapshots (8,009 distinct in Naukri) | Data attached to the wrong company or lost | Match once at load time against data/raw/company_aliases.csv; prefer the highest review_count when a ratings name is ambiguous; spot-check. The ratings loader flags large companies with under 5,000 ratings reviews as possible regional pages |
| Glassdoor ratings are missing for several large employers | TCS, Infosys, Wipro, Cognizant, Accenture, Capgemini, Tata Motors and Mercedes-Benz show no rating | The snapshot has no trustworthy parent-company row for them; show "not available" rather than a subsidiary's or regional page's rating |
| Postings carry relative post times, and 19,481 rows carry none | No absolute posted date, and no link for those rows | Report roles posted in the dataset period rather than open now; don't display links or post times at all |
| The postings' columns are misaligned row by row | Links, cities, post times and skills describe other postings | Keep link, city and post time only where the link verifies against the row's title and employer, and display only the city; skills market-wide only; never store locations or skills against a posting |
| Many postings are not data roles | "Data roles" would overstate | Title filter with editable include/exclude keywords; the match report prints the 30 most common titles kept and dropped |
| Few companies publish attrition | Turnover mostly proxy | Label the proxy clearly; don't rank by turnover without the label |
| VADER misreads sarcasm and Indian English | Noisy sentiment | Cross-check with TextBlob; report agreement rate |

**Ethics and terms.** Use only sources whose terms permit this use. Store no reviewer names or personal data. Cite every dataset and API in the report.

**Open questions**

- [ ] Does the course require a separate frontend, or is Streamlit acceptable?
- [ ] Team split: who owns which loaders?
