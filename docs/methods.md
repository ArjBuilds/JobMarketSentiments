# Methods, sources and caveats

The method and caveat text that used to sit on the dashboard's pages, kept here for the report. The dashboard itself now shows only labels, one-line tooltips and a source-and-date line under each block. Exact dates (review range, snapshot, fetch, retrieval) are read from the database: see the About the data page or docs/freeze.md, not this file.

## Overview

For each of 82 large employers that also hire in India, the dashboard shows employee review sentiment, turnover, recent news, and the data roles and skills in a postings snapshot. Every figure comes from a source below; where a source has nothing for a company, the dashboard says "Not available" rather than estimating.

LinkedIn and Glassdoor are never scraped: their terms forbid it. No reviewer names or personal data are stored. The dashboard reads only its own database and never calls a live source.

## Sources and licences

| Source | Used for | Licence / terms |
|---|---|---|
| Glassdoor reviews: Kaggle dataset [davidgauthier/glassdoor-job-reviews-2](https://www.kaggle.com/datasets/davidgauthier/glassdoor-job-reviews-2) (all_reviews.csv) | Review sentiment and themes; turnover proxy | CC BY-NC-SA 4.0 (attribution, non-commercial, share-alike); this project is non-commercial coursework |
| Glassdoor company ratings snapshot: data/raw/glassdoor_company_ratings.csv (originally Glassdoor_Dataset.csv) | Glassdoor rating and number of ratings | Kaggle dataset, downloaded October 2026; exact dataset page not recorded; licence unknown. Used only for non-commercial coursework |
| Naukri postings: data/raw/naukri_jobs_merged.csv, three exports merged (NaukriData_Data_Science, NaukriData_data_analytics, Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data) | Data-role listings; market-wide skills | As for the ratings file |
| GNews API (https://gnews.io), free tier | News coverage and headline sentiment | Non-commercial use only. Only each article's headline and GNews's short description are stored, never the article text |
| Companies' own annual reports, BRSR, quarterly results or fact sheets and official ESG reports, copied by hand into data/turnover.csv | Published attrition | Public company documents, cited per figure with a source link and page reference. Never news, Glassdoor or aggregators |
| data/companies.csv | The company library | Curated by hand for this project |

## How companies are matched

Every source names employers its own way (8,009 distinct employer names in the postings alone). Each source is matched to the library once, when it is loaded, never by fuzzy-matching names on the page. Names that differ from the library's are listed in one committed file, data/raw/company_aliases.csv (company_id, alias_in_dataset, source), and each alias applies only to the dataset it was found in. When several ratings rows share a name, the one with the most reviews wins. For the postings, a company's own India operations and service centres count for it; recruitment agencies, namesakes and majority-owned businesses in a different line of work (e.g. ICICI Prudential, HDFC Life, Tata Motors Finance, Siemens Healthcare) don't.

## Glassdoor ratings

- The ratings file records no snapshot date, so the dashboard says so rather than supplying one.
- Glassdoor ratings and review text are different sources with different coverage, so a company can have a rating and no sentiment, or the reverse.
- No Glassdoor rating (16 companies): the ratings file has only a subsidiary or regional page for tata-consultancy-services, infosys, accenture, capgemini, ibm, deloitte, amazon and walmart, and no row at all for cognizant, linkedin, blackrock and visa. The exact matches for wipro, ey and tata-motors were rejected: low review counts and a foreign head office mark them as regional pages. mercedes-benz's only candidate is a sales arm, not the group.

## Glassdoor reviews and sentiment

- VADER scores each review's headline, pros and cons separately. A review's score is mean(headline, mean(pros, cons)), from −1 (negative) to +1 (positive), labelled positive at ≥ 0.05 and negative at ≤ −0.05. Cons aren't subtracted: VADER already scores them negative.
- Themes (pay, culture, work-life balance, management) come from keyword lists in data/themes.csv. A theme's score is the VADER score of the section that mentions it, so praise in the pros and complaints in the cons both count.
- TextBlob is run on a 50k sample as a cross-check.
- Figures based on fewer than 20 reviews are hidden, and the review count is always shown beside a score.
- The review text runs from 2008 to mid-2023, so sentiment is a couple of years behind. Reviews thin out from April 2023, from about 21,000 a month to a few hundred, so a range ending after March 2023 is sparse at its end.
- The source has no location, so nothing India-specific can be said from review text.
- LTM (formerly LTIMindtree)'s 10,545 reviews are of Mindtree before the 2022 merger; they are flagged pre-merger and labelled wherever they are shown. Intuit clears the 20-review threshold with only 22 reviews, all from 2022–23.
- No review text: atlassian and workday have no reviews in the dataset. jpmorgan-chase and hdfc-bank were rejected rather than guessed: the dataset's "Chase" and "Hdfc" are different companies.

## Turnover: published attrition

- Published attrition is copied from the company's own report, with its period, definition and entity. Definitions differ: some count only voluntary exits, some all exits, and some don't say. Some cover one segment (e.g. IT services) or the listed India subsidiary rather than the group. The dashboard shows each figure with its basis, scope and period, and only each company's latest figure.
- Shown for 19 companies. A listed India subsidiary counts only if it is the group's main India operating company in its core business, so pfizer (a one-off rate from a business arrangement), novartis (57 permanent employees) and oracle (a niche arm) are excluded. For siemens, Siemens AG's group figure is used, because Siemens Ltd's covers an 18-month period. SAP, Capgemini, Schneider Electric and ICICI Bank couldn't be confirmed from their documents; the remaining companies weren't researched.
- On the Explore page, published attrition figures use different definitions and cover different entities; the basis and scope filters let a ranking compare like with like.

## Turnover: review-based proxy

- The proxy is the share of a company's reviews dated Apr 2021 – Mar 2023 whose headline or cons mention people leaving, attrition or layoffs (keywords in data/turnover_keywords.csv), shown per 100 reviews with its split (leaving/attrition, layoffs). That window is the last two years with full coverage in the review dataset.
- Pros aren't searched: "good leave policy" and "no layoffs" are praise.
- The proxy counts reviews, not people: a review can mention colleagues leaving or layoffs elsewhere, and reviewers aren't a representative sample of staff. Don't read it as an attrition rate. A review can mention both kinds, so the two parts can add up to more than the total.
- A hand check found 43 of 50 random matches (86%) were about people leaving, attrition or layoffs.
- Checked against published attrition: for the 12 companies with both a proxy and a published figure overlapping April 2021 to March 2023, the Spearman rank correlation between them is −0.08 (−0.19 for the 8 IT companies): about zero. The proxy reflects what reviewers write about, not how many people leave. It is never sorted or ranked.

## Naukri postings: data roles

- Naukri postings in India for data-science and analytics roles only, kept when the job title names a data role (editable include and exclude keywords in data/data_role_keywords.csv), then matched to a company and deduplicated into distinct listings.
- The postings' columns are misaligned row by row. Only the job title and employer reliably belong together; a posting's link, city and post time often describe another posting. So a city is shown only where the posting's own link names its title and employer (265 of 976 listings), and links and relative post times ("1 Day Ago") are never shown.
- Data-role counts are a lower bound: the same title and employer were copied onto many rows, so listings are deduplicated, and same-title listings without a verified link are counted once.
- The listings are historical, from a dataset snapshot collected in or after late October 2023 (bounded by the newest Naukri job-ID date among the stored links; the third export has no links and is undated). They are not current openings; the Company page links to each company's own careers site for those.
- No data roles (29 companies): most have no postings in the file under any name; airbus, icici-bank, samsung and texas-instruments have only non-data titles.

## Naukri postings: market-wide skills

- 75 known skills (data/skills.csv) are matched against each posting's skills text with spaCy's PhraseMatcher.
- Skills are market-wide only: the source's skills column is misaligned row by row and describes other postings, so no skill can be tied to an employer. The Company page shows "Not available" for skills and points to the Market skills page.
- Listings were scraped repeatedly and their skill lists copied, so each distinct skill list counts once and counts are a lower bound. Shares in every view (tools, methods, all) are of the same base: all distinct skill lists scored.
- The headline pools the two data-science exports, whose titles are 87–91% data roles, and counts a list found in both once. The data_analytics export is left out of it: only 38% of its titles are data roles. Each export's distinct skill lists, counted on their own, can be read with `read_export_comparison()` and `read_scope_sizes()` in jmsa/skills.py (previously shown in an expander on the Market skills page), and `python -m process.skill_counts` writes them to data/raw/skill_counts_report.txt.

## News

- One GNews query per company (data/news_queries.csv). An article is kept only if its title or description names the company; duplicates are dropped and the 10 newest kept.
- The free tier searches only the 30 days before the fetch and returns at most 10 articles a request, so a company's news is up to 10 articles from those 30 days (GNews runs up to 12 hours behind), never "the last 12 months".
- Headline sentiment is approximate: VADER scores only the headline and GNews's short description, not the article, and a neutral-sounding headline can report bad news.
