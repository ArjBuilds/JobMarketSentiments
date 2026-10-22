# Database freeze

Frozen on **2026-10-22** at git commit `f299844cbc03ad04c839ea3b0504207ac1a06adb`.

Written by `python scripts/freeze.py`. Rerun it after any reload; don't edit by hand.

## Database

| file | bytes | SHA-256 |
|---|---|---|
| jmsa.db | 769,093,632 | `8103c4c668de473101043f34a7bed9d7ad520d25cd8d266241f0b862d9207e13` |

## Rows per table

| table | rows |
|---|---|
| articles | 320 |
| companies | 82 |
| job_skills | 0 |
| jobs | 976 |
| news_fetches | 82 |
| review_summary | 156 |
| reviews | 1,799,628 |
| skill_counts | 296 |
| turnover | 109 |

## Sources and dates

As the dashboard shows them (jmsa/freshness.py, read from the database).

| source | used for | dates | licence |
|---|---|---|---|
| Glassdoor company ratings snapshot, data/raw/glassdoor_company_ratings.csv (originally Glassdoor_Dataset.csv) | Glassdoor rating and number of ratings | Not available: the file records no snapshot date | Kaggle dataset, downloaded October 2026; exact dataset page not recorded; licence unknown. Used only for non-commercial coursework |
| Glassdoor reviews, Kaggle dataset davidgauthier/glassdoor-job-reviews-2 (all_reviews.csv) | Review sentiment and themes | reviews dated Jan 2008 – Jul 2023 (sparse after Mar 2023) | CC BY-NC-SA 4.0: non-commercial, share-alike; this project is non-commercial coursework |
| Naukri postings, data/raw/naukri_jobs_merged.csv: three exports merged (NaukriData_Data_Science, NaukriData_data_analytics, Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data) | Data-role listings | collected in or after 27 Oct 2023 (the newest Naukri job-ID date among the stored links; the third export has no links and is undated); loaded 21 Oct 2026 | Kaggle dataset, downloaded October 2026; exact dataset page not recorded; licence unknown. Used only for non-commercial coursework |
| The same Naukri snapshot as the data-role listings | Market-wide data-role skills | collected in or after 27 Oct 2023 (the newest Naukri job-ID date among the stored links; the third export has no links and is undated); loaded 21 Oct 2026 | Kaggle dataset, downloaded October 2026; exact dataset page not recorded; licence unknown. Used only for non-commercial coursework |
| GNews API (https://gnews.io), free tier | News coverage and headline sentiment | fetched 21 Oct 2026 – 22 Oct 2026 for 82 of 82 companies; each article published in the 30 days before its company's fetch | GNews free tier: non-commercial use only |
| Companies' own annual reports, BRSR, quarterly results or fact sheets and official ESG reports, copied by hand into data/turnover.csv | Published attrition | periods vary by company (shown with each figure); retrieved 22 Oct 2026 | Public company documents, cited per figure with a source link and page reference |
| The Glassdoor review dataset above | Turnover proxy | reviews dated Apr 2021 – Mar 2023 | CC BY-NC-SA 4.0: non-commercial, share-alike; this project is non-commercial coursework |

## Input files

The raw inputs the loaders read, then the committed CSVs in data/. data/raw/all_reviews.csv (3.8 GB) isn't hashed: only ingest.load_glassdoor_reviews reads it, to write glassdoor_reviews_matched.csv, which is.

| file | bytes | SHA-256 |
|---|---|---|
| data/raw/glassdoor_reviews_matched.csv | 485,756,958 | `41c1ff2fc83e33009c0e72f4d4bfa7a121e3e60291c768880b36bc5b8b7afab8` |
| data/raw/glassdoor_company_ratings.csv | 308,174 | `f26ddba4eae1ed8ab8d5075ed127a6fda2f556ed641caa367bd815f3d0ee0436` |
| data/raw/naukri_jobs_merged.csv | 13,150,975 | `658e53883e3ee78756bc5bb32ccf030f8b069d5ba15e23bbc88db5b46a860309` |
| data/raw/company_aliases.csv | 5,089 | `03eccb185da72b4fbbabd3d7365c2411d1e4f825512817af284916de8041d17c` |
| data/companies.csv | 9,816 | `023d189c1d44d80382eb0afef0769a4a802ad9bc07292c990ea7d36d7bce5919` |
| data/data_role_keywords.csv | 970 | `83a3b6900b9b92f6ca86a1e3267b46c9c4e5198b50ab66ae9dcb15970e11c9c8` |
| data/news_queries.csv | 13,789 | `a753a740128a3fe88e370cbf761a593a88ac393f97d6175acfc2f3dd7ab9f1a4` |
| data/skills.csv | 3,603 | `aeb16f393337f8e8416fe4d23456e92c59344726a135fce49437c7476cb49c54` |
| data/themes.csv | 706 | `79491c42fd1debbf837661ae20a9c9fc3e8a12ed6ed4a880065849b51e5832ee` |
| data/turnover.csv | 10,402 | `2c2012be560d31e41e17a6aebdc8165f54b1fc62747a222dd5337524ca50db8c` |
| data/turnover_keywords.csv | 740 | `4b509e1c0f1500fdd16a21b41e93df4a220166839b0ebd09688a69fd357d5bf3` |
