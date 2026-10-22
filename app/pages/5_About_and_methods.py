"""About and methods: every source with its licence and dates, how companies
are matched, and what the figures can't tell you.

Reads only from SQLite, for the sources table and the dates in the text
(jmsa.freshness). The method text restates PRD.md, the specification of
record; change it there first.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE  # noqa: E402
from jmsa.freshness import (  # noqa: E402
    REVIEWS_URL, freshness_table, proxy_window, read_freshness, review_end, review_range,
)
from jmsa.sentiment import MIN_REVIEWS  # noqa: E402

init_state()


# Cached results, not connections, for the reason given on the Library page.
@st.cache_data
def sources() -> tuple[dict, str, str, str]:
    conn = get_conn()
    try:
        return read_freshness(conn), review_range(conn), review_end(conn), proxy_window(conn)
    finally:
        conn.close()


st.title("About and methods")
st.markdown(
    "A mini-project for the Web and Social Media Analytics course. For each of 82 large employers that "
    "also hire in India, the dashboard shows employee review sentiment, turnover, recent news, and the "
    "data roles and skills in a postings snapshot. Every figure comes from a source below; where a "
    "source has nothing for a company, the dashboard says **not available** rather than estimating."
)

# The one page that opens without a database (app/app.py lets it through):
# the methods text below needs none, so only the dates read "not available".
# Checked before connecting, because get_conn would create an empty file.
if DB_PATH.exists():
    freshness, reviews, reviews_end, window = sources()
else:
    freshness, reviews, reviews_end, window = None, NOT_AVAILABLE, NOT_AVAILABLE, NOT_AVAILABLE

st.header("Sources")
if freshness:
    st.dataframe(freshness_table(freshness), hide_index=True)
else:
    st.warning(f"No database at `{DB_PATH}`, so each source's dates can't be shown.")
st.markdown(
    f"- **Review text**: [davidgauthier/glassdoor-job-reviews-2]({REVIEWS_URL}) on Kaggle, "
    "licensed CC BY-NC-SA 4.0 (attribution, non-commercial, share-alike). 9.9M Glassdoor reviews, "
    f"of which 1,799,628 match 78 of the 82 companies, {reviews}.\n"
    "- **Glassdoor ratings** and **Naukri postings**: Kaggle datasets, downloaded October 2026; the "
    "exact dataset pages were not recorded and their licences are unknown. Original files: "
    "Glassdoor_Dataset.csv; NaukriData_Data_Science, NaukriData_data_analytics and "
    "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data. Used only for non-commercial coursework.\n"
    "- **News**: the GNews API free tier, for non-commercial use only. Only each article's headline "
    "and GNews's short description are stored, never the article text.\n"
    "- **Published attrition**: the companies' own primary documents only (annual reports, BRSR, "
    "quarterly results or fact sheets, official ESG reports), copied as printed with a source link "
    "and page reference. Never news, Glassdoor or aggregators.\n"
    "- **Company library**: data/companies.csv, curated by hand for this project.\n\n"
    "LinkedIn and Glassdoor are never scraped: their terms forbid it. No reviewer names or personal "
    "data are stored. The dashboard reads only its own database and never calls a live source."
)

st.header("How companies are matched")
st.markdown(
    "Every source names employers its own way (8,009 distinct employer names in the postings alone). "
    "Each source is matched to the library **once, when it is loaded**, never by fuzzy-matching names "
    "on the page. Names that differ from the library's are listed in one committed file, "
    "data/raw/company_aliases.csv (company_id, alias_in_dataset, source), and each alias applies only "
    "to the dataset it was found in. When several ratings rows share a name, the one with the most "
    "reviews wins. For the postings, a company's own India operations and service centres count for "
    "it; recruitment agencies, namesakes and majority-owned businesses in a different line of work "
    "(e.g. ICICI Prudential, HDFC Life, Tata Motors Finance, Siemens Healthcare) don't."
)

st.header("How the figures are made")
st.markdown(
    "- **Review sentiment**: VADER scores each review's headline, pros and cons separately, and a "
    "review's score is mean(headline, mean(pros, cons)), from −1 to +1: positive at ≥ 0.05, negative "
    "at ≤ −0.05. Themes (pay, culture, work-life balance, management) come from keyword lists; a "
    "theme's score is the VADER score of the section that mentions it. TextBlob is run on a 50k "
    f"sample as a cross-check. Figures based on fewer than {MIN_REVIEWS} reviews are hidden, and the "
    "review count is always shown beside a score.\n"
    "- **Data roles**: a posting is kept only if its title names a data role (editable include and "
    "exclude keywords), then matched to a company and deduplicated into distinct listings.\n"
    "- **Skills**: 75 known skills are matched against each posting's skills text with spaCy's "
    "PhraseMatcher; each distinct skill list counts once.\n"
    "- **News**: one GNews query per company; an article is kept only if its title or description "
    "names the company; duplicates are dropped and the 10 newest kept. VADER labels each headline.\n"
    f"- **Turnover proxy**: the share of a company's reviews ({window}) whose headline or cons mention "
    "people leaving, attrition or layoffs, shown per 100 reviews with its split. Pros aren't "
    "searched (\"good leave policy\" and \"no layoffs\" are praise). A hand check found 43 of 50 "
    "random matches (86%) were about people leaving, attrition or layoffs."
)

st.header("What the figures can't tell you")
st.markdown(
    f"- **Reviews end {reviews_end}.** The review text runs {reviews}, so sentiment is a couple of "
    "years behind. Reviews thin out from April 2023, from about 21,000 a month to a few hundred. The "
    "source has no location, so nothing India-specific can be said from review text.\n"
    "- **LTM (formerly LTIMindtree)'s reviews are of Mindtree before the 2022 merger.** All 10,545 "
    "of them are flagged pre-merger and labelled wherever they are shown. **Intuit** clears the "
    f"{MIN_REVIEWS}-review threshold with only 22 reviews, all from 2022–23.\n"
    "- **Glassdoor ratings and review text are different sources** with different coverage, so a "
    "company can have a rating and no sentiment, or the reverse.\n"
    "- **The postings' columns are misaligned row by row.** Only the job title and employer reliably "
    "belong together; a posting's link, city and post time often describe another posting. So a "
    "city is shown only where the posting's own link names its title and employer (265 of 976 "
    "listings), and links and relative post times (\"1 Day Ago\") are never shown.\n"
    "- **Data-role counts are a lower bound.** The same title and employer were copied onto many "
    "rows, so listings are deduplicated, and same-title listings without a verified link count once. "
    "They are listings in a 2023 snapshot, not roles open now.\n"
    "- **Skills are market-wide only.** The skills column describes other rows' postings, so no "
    "skill can be tied to a company. The Company page says \"not available\" and points to the "
    "Market skills page.\n"
    "- **News covers only 30 days.** The free tier searches the 30 days before the fetch and returns "
    "at most 10 articles a request, so a company's news is up to 10 articles from those 30 days, "
    "never \"the last 12 months\". Headline sentiment is approximate.\n"
    "- **The turnover proxy is not an attrition rate.** It counts reviews, not people. For the 12 "
    "companies with both a proxy and a published figure overlapping April 2021 to March 2023, the "
    "Spearman rank correlation between them is −0.08 (−0.19 for the 8 IT companies): about zero. "
    "The proxy reflects what reviewers write about, not how many people leave. It is never sorted "
    "or ranked.\n"
    "- **Published attrition definitions differ.** Some count voluntary exits only, some all exits, "
    "some don't say; some cover one segment or the listed India subsidiary. Each figure is shown "
    "with its basis, scope and period, and only each company's latest figure is shown."
)

st.header("Companies left out, and why")
st.markdown(
    "- **No review text**: atlassian and workday have no reviews in the dataset. jpmorgan-chase and "
    "hdfc-bank were rejected rather than guessed: the dataset's \"Chase\" and \"Hdfc\" are different "
    "companies.\n"
    "- **No Glassdoor rating (16)**: the ratings file has only a subsidiary or regional page for "
    "tata-consultancy-services, infosys, accenture, capgemini, ibm, deloitte, amazon and walmart, and "
    "no row at all for cognizant, linkedin, blackrock and visa. The exact matches for wipro, ey and "
    "tata-motors were rejected: low review counts and a foreign head office mark them as regional "
    "pages. mercedes-benz's only candidate is a sales arm, not the group.\n"
    "- **Published attrition**: shown for 19 companies. A listed India subsidiary counts only if it "
    "is the group's main India operating company in its core business, so pfizer (a one-off rate "
    "from a business arrangement), novartis (57 permanent employees) and oracle (a niche arm) are "
    "excluded. For siemens, Siemens AG's group figure is used, because Siemens Ltd's covers an "
    "18-month period. SAP, Capgemini, Schneider Electric and ICICI Bank couldn't be confirmed from "
    "their documents; the remaining companies weren't researched.\n"
    "- **No data roles (29)**: most have no postings in the file under any name; airbus, icici-bank, "
    "samsung and texas-instruments have only non-data titles."
)
