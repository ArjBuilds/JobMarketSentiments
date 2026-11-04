"""The portfolio backend: Greenhouse ingestion, ClickHouse storage and a live stream.

Separate from the Shortlist pipeline (ingest/, process/, jmsa/): nothing here
reads or writes data/jmsa.db, and the Kaggle loaders don't depend on it.
"""
