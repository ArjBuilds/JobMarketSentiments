"""One loader per source, each run on demand as `python -m ingest.<loader>`.

Loaders cache raw responses under data/raw/ and write normalised rows to
SQLite. Planned: companies (M2), reviews (M3), jobs (M5), news (M7).
"""
