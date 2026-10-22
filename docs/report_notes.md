# Report notes

Source material for the written report. These are notes, not prose. Every number carries a tag in square brackets saying where it comes from:
- `PRD` means PRD.md, followed by the section.
- `raw/…` means a report in data/raw/ written by a loader. These files are gitignored; rerun the loader to regenerate them.
- `analysis/…` means docs/analysis/, written by `python -m process.analysis`.
- `db` means a count read from data/jmsa.db; docs/freeze.md records it at freeze time.

If a number in the report has no tag here, check it before using it.

## 1. Problem and goal

- **Problem.** Employer information is scattered across review sites, news, job boards and annual reports. A student comparing ten companies opens forty tabs and still gets no consistent picture. [PRD Overview]
- **Goal.** For each company in a curated library, show employee sentiment, turnover, recent coverage, sector, and the data-role skills and postings it advertises in India, with sort and filter across companies. [PRD Overview]
- **User.** A final-year engineering student in India shortlisting employers before placements. [PRD Overview]
- **Course context.** Web and Social Media Analytics mini-project. The core is web data collection plus sentiment analysis with spaCy, VADER and TextBlob. [PRD Overview]
- **Scope.** 82 companies [db: companies], features F1–F9. F9 (compare) was a stretch goal and was built. [README Status]
- **Non-goals.** No live scraping, no live job APIs, no roles outside data science and analytics, no accounts, no real-time updates, no ML beyond sentiment and skill extraction. [PRD Scope and non-goals]

## 2. Data sources and licences

| Source | Size / coverage | Licence | Tag |
|---|---|---|---|
| Company library, data/companies.csv | 82 companies, 15 fixed sectors | own, hand-curated | [PRD Data sources; db] |
| Glassdoor ratings, glassdoor_company_ratings.csv (originally Glassdoor_Dataset.csv) | 3,029 rows; 66 of 82 companies matched (60 exact, 6 alias); no snapshot date | Kaggle, dataset page not recorded, licence unknown; non-commercial coursework only | [PRD Data sources; PRD Matching] |
| Glassdoor review text, all_reviews.csv (davidgauthier/glassdoor-job-reviews-2) | 9,901,889 rows scanned, 1,799,628 matched to 78 companies, 2008 to mid-2023 | CC BY-NC-SA 4.0 | [raw/glassdoor_match_report.txt] |
| Naukri postings, naukri_jobs_merged.csv | 43,630 rows in 3 exports (11,465 / 12,686 / 19,479), 8,009 employer names | Kaggle, dataset page not recorded, licence unknown | [PRD The postings snapshot] |
| GNews API, free tier | 82 companies fetched 21–22 Oct 2026; 357 articles returned, 320 kept | non-commercial use only | [db: news_fetches, articles] |
| Published attrition, data/turnover.csv | 25 companies with a figure, retrieved 22 Oct 2026 | public company documents, cited per figure | [PRD Published attrition; raw/turnover_load_report.txt] |

- **Postings date.** Collected in or after late October 2023. The newest Naukri job-ID date in the links is 28 Oct 2023, and the third export is undated. [PRD Dates]
- **Naukri merge cannot be reproduced.** The three exports now on disk appear to be a later version than the ones merged:
  - They hold 47,191 / 20,064 / 19,649 rows, against 11,465 / 12,686 / 19,479 in the merged file.
  - 522 merged rows (230 Data_Science, 292 third export) appear in no export.
  - The closest variant (trim spaces, dedup within each export) finds 43,108 of the 43,630 merged rows.
  - So the pinned merged file is the input of record. [raw/naukri_merge_check.txt, from `python -m ingest.merge_naukri`]
- **Ratings conversion.** Renaming Glassdoor_Dataset.csv was a one-off. The original isn't available, so no conversion can be checked. [README Get the data]

## 3. Architecture

- **Pipeline.** Batch: 5 local CSVs + GNews → ingest/ (one loader per source, raw results cached) → process/ (VADER + TextBlob, spaCy PhraseMatcher, turnover proxy) → SQLite → Streamlit (reads only SQLite). [PRD Architecture]
- **Why.** The dashboard never calls a live source, so the demo survives a dead or rate-limited API. [PRD Architecture]
- **Database.** 9 tables:
  - 6 source tables: companies, reviews, turnover, articles, jobs, job_skills
  - 2 derived tables: review_summary, skill_counts
  - news_fetches

  job_skills is always empty, by design. [PRD Data dictionary]
- **Shared code.** `jmsa/` holds the shared code: connection, sentiment cut-offs, freshness dates, statistics. [CLAUDE.md Architecture]
- **Stack.** Python 3.11, pandas, requests, vaderSentiment, TextBlob, spaCy, sqlite3, Streamlit + Plotly, python-dotenv. Versions are pinned in requirements.txt.
- **Speed.** Every page is timed against the target of under 3 s, with `python scripts/time_pages.py`. [PRD F1]

## 4. Methods

### Matching
- Each source is matched to company_id once, at load time, through one committed alias file. The `source` column scopes each alias to one dataset. No fuzzy matching at query time. [PRD Matching companies to sources]
- **Ratings.** When several rows share a name, the highest review_count wins. Wipro, EY and Tata Motors exact matches were rejected as regional pages (low review counts, foreign head office: Dresden, Riyadh, Coventry). [PRD Matching]
- **Naukri.** A company's own India operations count; agencies, namesakes and majority-owned businesses in another line of work don't (`REJECTED_NAMES`). 43 companies match by exact name, 24 aliases add the rest, and 53 companies have data-role postings. [PRD Matching]
- **Reviews.** Chase and Hdfc were rejected as different legal entities, so jpmorgan-chase and hdfc-bank show no sentiment. [PRD The review snapshot]

### Sentiment (method F)
- VADER scores the headline, pros and cons separately. A review's score is mean(headline, mean(pros, cons)). A review with no text gets NULL. [PRD Data sources]
- Labels use the standard cut-offs: positive ≥ 0.05, negative ≤ −0.05. [PRD Conventions]
- **Choosing the method.** Six methods were compared on a seed-42 sample of 20,000 rated reviews. F had the highest Pearson r with the star rating, 0.471 (Spearman 0.423, label agreement with stars 66.3%). On a held-out seed-7 sample: r 0.477. Pros minus cons (C): r 0.012. [analysis/b_star_validation.md; raw/sentiment_checks.txt]
- **TextBlob cross-check** (seed 42, 50,000 reviews): VADER and TextBlob agree on 80.5% of labels (raw agreement); Cohen's kappa 0.40, on the fair/moderate boundary (Landis-Koch). Chance agreement is 67.5%, because both tools call about 81% of reviews positive. [analysis/a_kappa.md]
- **20-review rule.** Sentiment is hidden below 20 reviews, and the count is always shown. intuit clears it with 22. [PRD F4; PRD The review snapshot]

### Themes
- Pay, culture, work-life balance and management use keyword lists in data/themes.csv. A theme's score is the VADER score of the section (headline, pros or cons) that mentions it. [PRD Data sources]
- **Validation against Glassdoor's own sub-ratings.** Spearman across 77 companies with ≥100 mentions: pay vs compensation_and_benefits +0.95; work-life balance +0.92; culture vs culture_and_values +0.84; management vs senior_management +0.83. [analysis/c_themes_vs_subratings.md]
- **Largest rank gaps** (rank by theme score vs rank by sub-rating, out of 77):
  - culture: tata-motors 9 vs 56; tata-consultancy-services 12 vs 49
  - work-life balance: google 37 vs 74
  - management: flipkart 23 vs 62

  Possible readings, not tested: star ratings and the words in a review can diverge by company, and theme keywords pick up mixed sections. [analysis/c_themes_vs_subratings.md]

### Postings deduplication
- **Title filter.** 18,904 rows aren't data roles. Business analyst is excluded unless the title also has a data keyword. [raw/naukri_match_report.txt; PRD Not every posting is a data role]
- **Link verification.** Columns are misaligned, so a row keeps its url, city and post time only when its link's slug starts with its title and then names its employer. 265 of the 2,471 matched rows verify. [PRD The postings snapshot]
- **Dedup.**
  - One verified row per Naukri job ID.
  - One unverified row per (employer as posted, title).
  - An unverified row is dropped when a verified row has the same pair.
  - Result: 2,471 rows → 976 listings (265 verified, 711 not), so counts are a lower bound.
  - Example: American Express 432 rows → 26 listings. [raw/naukri_match_report.txt]

### Skills extraction
- skills_raw concatenates tags with no separator, so 75 known skills (48 tools, 27 methods) are matched with spaCy's PhraseMatcher on spacy.blank("en"), after splitting glued tags. [PRD Skill extraction; raw/skill_counts_report.txt]
- Each distinct skill list counts once. The two data-science exports are pooled: 30,762 rows → 14,097 distinct lists. One 187-copy list would lift Machine Learning from 12.4% to 17.3%. [PRD Repeated skill lists; raw/skill_counts_report.txt]
- **Hand check** of 50 lists: precision 98.7% (1 wrong of 79), recall 91% (8 missed). [PRD Skill extraction]
- **Top results** (distinct lists, data-science scope):
  - tools: SQL 14.9%, Python 7.8%, Excel 6.9%, Power BI 4.9%
  - methods: Data Analysis 27.1%, Machine Learning 12.4%

  [raw/skill_counts_report.txt]

### News relevance
- **Query.** One GNews query per company: the quoted name AND a group of workplace terms; at most 200 characters. Ambiguous names get narrower quoted phrases. `jobs` is never a term (Steve Jobs). [CLAUDE.md News; PRD Data sources]
- **Filtering.** Keep an article only if its title or description names the company or a gnews alias as a whole, case-matched word; dedupe by URL and near-identical title; keep the 10 newest.
- **Result.** 357 returned, 4 dropped as irrelevant, 33 as duplicates, 320 kept; 60 companies have at least one article. [db: news_fetches]
- **Window.** The free tier searches only 30 days, so F6 is labelled "up to 10 most recent articles published in the 30 days before the fetch date". [PRD F6]

### Turnover proxy
- **Definition.** Reviews dated Apr 2021 – Mar 2023 whose headline or cons match keywords in data/turnover_keywords.csv, shown per 100 reviews and split into leaving/attrition and layoffs. [PRD Turnover proxy]
- **Size.** 718,723 reviews in the window, 13,153 matched (1.8 per 100). [raw/turnover_proxy_report.txt]
- **Why that window.** Reviews fall from about 21,000 in March 2023 to 4,311 in April. [PRD Turnover proxy]
- **Hand check.** 43 of 50 matches (86%) were about leaving, attrition or layoffs. "restructuring" (7 of 25) and "fired" (20 of 25, mostly "should be fired") were dropped. Pros are never searched. [PRD Turnover proxy]

### Published attrition rules
- **Sources.** Primary documents only: annual reports (including SEC 10-K and 20-F filings), BRSR, quarterly results or fact sheets, ESG reports, SEC proxy statements. Copied as printed, with a page reference; never news, Glassdoor or aggregators. [PRD Published attrition]
- **Labels.** `basis` (voluntary / total / not-stated) is taken from the document, never inferred. Only the latest figure per company is shown. [PRD Published attrition]
- **Subsidiaries.**
  - A listed India subsidiary counts only if it is the group's main India operating company in its core business.
  - pfizer is excluded (a one-off 37%), as are novartis (57 permanent employees) and oracle (a niche arm).
  - siemens uses Siemens AG, because Siemens Ltd's covers 18 months.

  [PRD India subsidiaries]
- **Coverage.** 25 companies. The latest figures are 9 voluntary, 5 total and 11 not-stated; by scope, 7 segment, 11 group and 7 india-subsidiary. [raw/turnover_load_report.txt]

## 5. Results

- **Coverage.**
  - review sentiment: 78 of 82 companies [raw/glassdoor_match_report.txt]
  - rating: 66 [db]
  - data roles: 53 [PRD Matching]
  - published attrition: 19
  - proxy: 78 [db: turnover]
  - news: 60 companies with at least one article [db]
- **Reviews.** 1,799,628 reviews, of which 1,459,094 positive, 172,658 neutral, 167,842 negative and 34 unscored (empty). [db: reviews]
- **Method validation.** F, r 0.471 / held-out 0.477. [analysis/b]
- **Tool agreement.** κ 0.40 next to 80.5%. [analysis/a]
- **Themes.** They track the sub-ratings, ρ 0.83–0.95. [analysis/c]
- **Trend.** For the 10 companies with the most reviews, yearly average sentiment is fairly flat, between about +0.12 and +0.37, with no sharp 2021–22 change. Walmart is the lowest in every year from 2010 (+0.12 to +0.21 overall). 2023 covers only Jan – Apr for these companies and is sparse after Mar 2023. [analysis/d_yearly_sentiment.md]
- **Proxy vs published attrition.** Spearman −0.19 for the 8 IT majors and −0.28 for all 13; −0.10 and −0.21 for the leaving part only. Weak and, if anything, negative. Caveats: n = 13, periods and definitions differ (Boeing's 2023 figure overlaps the window by three months), and ltimindtree's proxy is pre-merger Mindtree reviews. [analysis/e_proxy_vs_attrition.md]
- **Skills.** SQL, Python and Excel are the top tools; Data Analysis and Machine Learning are the top methods. [raw/skill_counts_report.txt]

## 6. Data-quality lessons

- **Naukri misalignment.** Only job_title and company_name belong together.
  - In the Data_Science export, links agree with the row for rows 1–200 and almost never after (3%); 9,731 links belong to other employers' postings.
  - skills_raw is unrelated to the title: a "Python" title lists Python 7–10% of the time, the same as the base rate.

  So link, city and post time are kept only on verification, and skills are market-wide only. [PRD The postings snapshot]
- **Scraped duplicates.**
  - American Express's "Senior Manager - Data Science" appears 394 times with 52 locations and 167 links, 2 of which verify.
  - Skill lists were copied too: 2,438 / 1,145 / 6,443 copies per export.
  - 86% of the Data_Science export's distinct lists recur in the third export.

  [PRD Repeated listings; PRD Repeated skill lists]
- **Regional Glassdoor pages.**
  - Exact-name rows can be a regional page, e.g. Wipro: 2,700 reviews, head office Dresden. [raw/glassdoor_company_ratings.csv line 1418; PRD Matching]
  - Infosys's only row is a subsidiary, Infosys BPM. [ratings CSV line 233]
  - Employer size is unreliable, so it isn't used to reject. The loader flags big companies with under 5,000 reviews. [CLAUDE.md]
- **Subsidiary rules.** Different per source, because the questions differ:
  - Naukri counts India service centres (KPMG Global Services, Hindustan Unilever for Unilever).
  - Attrition counts only the main India operating company.
  - Ratings take no subsidiary at all.

  [PRD Matching; PRD India subsidiaries]
- **The "India" in Indianapolis (a data-selection lesson).**
  - While scouting review datasets, a "contains India" location check on davidgauthier/glassdoor-job-reviews (the smaller dataset, never loaded) matched Indianapolis and Indian Wells.
  - The fix was a list of Indian cities, not a substring test.
  - Illustration on disk: data/raw/employee_reviews.csv (the retired review file) has amazon reviews located "Indianapolis, IN", e.g. line 8776.
  - The loaded review source has no location at all, so no India-only sentiment is possible. [project owner's scouting notes; PRD The review snapshot]
- **The proxy's weak, negative correlation.**
  - An intuitive measure (reviews that mention leaving) doesn't rank companies the way their published attrition does (ρ = −0.28, n = 13).
  - Lesson: validate a proxy before ranking on it. It is labelled "proxy" and never sorted. [analysis/e]
- **Unreproducible upstream merge.** The exports re-downloaded today don't rebuild the merged file. Pin and hash inputs at the time of use, as docs/freeze.md now does. [raw/naukri_merge_check.txt]
- **Empty and coded cells.** 34 reviews with no parseable date are completely empty. Sub-rating cells such as `10u0eun` are stored as NULL. [PRD The review snapshot]

## 7. Limitations

- Reviews end mid-2023 and are sparse after Mar 2023, so sentiment is more than three years behind the Oct 2026 demo. [PRD Risks; analysis/d]
- No location in the review source, so no India-specific sentiment. [PRD The review snapshot]
- Thin or stand-in coverage: intuit 22 reviews; ltimindtree is 10,545 pre-merger Mindtree reviews. [PRD The review snapshot]
- 16 companies have no rating, 4 have no review text and 29 have no data roles. [PRD Matching]
- Postings are a late-2023 snapshot of data roles only. Counts are a lower bound, not open vacancies. [PRD F8]
- Skills are market-wide, not per company. [PRD F7]
- News covers 30 days, at most 10 articles, with headline sentiment only. [PRD F6]
- Published attrition covers 25 companies, with mixed bases, scopes and periods. [raw/turnover_load_report.txt]
- VADER misreads sarcasm and Indian English. The TextBlob agreement is fair to moderate (κ 0.40), and no human-labelled sample exists. [PRD Risks; analysis/a]
- The review letter codes (recommend, ceo_approval, business_outlook) are unverified and not used. [PRD The review snapshot]
- Two Kaggle datasets have unrecorded pages and unknown licences. [PRD Data sources]

## 8. Ethics and terms

- No scraping of LinkedIn or Glassdoor, whose terms forbid it; review text comes from a CC BY-NC-SA 4.0 snapshot. [PRD Non-goals; PRD Data sources]
- No reviewer names or personal data are stored. reviews.location is always empty. [PRD Ethics and terms]
- **GNews.**
  - Non-commercial free tier, at most one run a day, every response cached.
  - Article text is never stored, not even in the cache.
  - The API key lives only in .env and is never printed, logged or stored. [CLAUDE.md]
- **Missing-data rule.** Never estimate or backfill; show "not available". [PRD Missing data rule]
- **Use and citation.** Non-commercial coursework only; every dataset and API is cited (see section 2 and the About page). [PRD Ethics and terms]
