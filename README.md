# JobMarketSentiments

**Job Market Analyser** — a Streamlit dashboard where a student picks a company and sees, on one page, what it is like to work there and what it hires for: employee review sentiment, turnover, recent news coverage, the data-role skills it hires for, and the India data roles it has posted. It covers a curated library of 82 large global employers that also hire in India.

Built as a mini-project for the Web and Social Media Analytics course. The analytics core is web data collection plus sentiment analysis with spaCy, VADER and TextBlob.

[PRD.md](PRD.md) is the specification: features, data sources, schema and build order.

## How it works

Data collection is a batch pipeline, kept separate from the dashboard so a demo survives a dead or rate-limited API:

```
sources → ingest/   one loader per source, raw responses cached in data/raw/
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
cp .env.example .env     # then fill in the API keys
```

## Running

```bash
python -m jmsa.db init      # create the empty database
streamlit run app/app.py    # dashboard at http://localhost:8501
```

The loaders and process steps are run on demand, not when the app starts:

```bash
python -m ingest.<loader>
python -m process.<step>
```

## Tests

```bash
pytest
```

## Status

Milestone 1 of 10 (skeleton) is complete: schema, database helper, Streamlit scaffold and test harness. No data is loaded yet — the company library (F1) is milestone 2. See the build order in [PRD.md](PRD.md).

## Data and ethics

Only sources whose terms permit this use: a Glassdoor company-ratings snapshot, a Glassdoor review-text snapshot, a Naukri snapshot of Indian data-science and analytics postings, the GNews API, and company annual reports. No scraping of LinkedIn or Glassdoor. No reviewer names or personal data are stored. Where a source has nothing for a company, the dashboard shows "not available" rather than an estimate.
