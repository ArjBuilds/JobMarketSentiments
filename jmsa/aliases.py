"""Company name matching shared by every loader that joins a source to the library.

data/raw/company_aliases.csv is the only alias store. Its source column says
which dataset each alias was found in, so an alias for one source never
matches rows in another:

    glassdoor_reviews   firm names in all_reviews.csv
    glassdoor_ratings   company_name in glassdoor_company_ratings.csv
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from jmsa.config import RAW_DIR

ALIASES_CSV = RAW_DIR / "company_aliases.csv"

SOURCES = ("glassdoor_reviews", "glassdoor_ratings")


def normalise(name: str) -> str:
    """Fold a company name to a comparable key.

    The dataset writes 'Tata-Consultancy-Services' where our library writes
    'Tata Consultancy Services', so hyphens and other punctuation collapse to
    single spaces before anything is compared.
    """
    text = (name or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def read_aliases(source: str, path: str | Path = ALIASES_CSV) -> list[tuple[str, str]]:
    """(company_id, alias_in_dataset) for every alias row of one source."""
    if source not in SOURCES:
        raise ValueError(f"unknown alias source {source!r}; expected one of {SOURCES}")
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [
            (row["company_id"], row["alias_in_dataset"])
            for row in csv.DictReader(handle)
            if row["source"] == source
        ]
