"""How a company's data roles (F8) are read and shown.

One definition for the Company and Library pages. Every value comes back as
display text, with the missing-data rule already applied, so the pages only
lay it out. The roles come from ingest.load_jobs.
"""

from __future__ import annotations

import sqlite3

from jmsa.display import NOT_AVAILABLE, show

# The postings are a fixed Naukri snapshot, never a live count. Its links
# have expired and its relative post times ("1 Day Ago") were relative to
# 2023, so neither is shown; both stay in jobs for verification and dedup.
ROLES_INTRO = ("Data-role listings this company posted in the dataset snapshot (late 2023). "
               "Historical, not current openings.")

# ingest.load_jobs deduplicates rows without a verified link by employer and
# title, so two genuine listings with the same title count as one.
LOWER_BOUND_NOTE = ("This is a lower bound: same-title listings without a verified link "
                    "are counted once.")

DATA_ROLES_NOTE = (
    "Naukri postings in India for data-science and analytics roles only, kept when the job title "
    "names a data role. Collected in or after late October 2023 (dated from two of three exports; "
    "the third is undated). The source's columns are misaligned row by row, so a city is shown "
    "only where the posting's link names its own title and employer."
)


def cities_text(cities: str | None) -> str | None:
    """'Mumbai;Delhi' -> 'Mumbai, Delhi'."""
    return ", ".join(cities.split(";")) if cities else None


def read_roles(conn: sqlite3.Connection, company_id: str) -> dict:
    """A company's data roles, ready to display.

    available is False when the company has no postings; rows is then empty
    and the page shows "not available" rather than 0.
    """
    rows = [
        {
            "Title": show(row["title"]),
            "Employer (as posted)": show(row["employer_name"]),
            "City": show(cities_text(row["city"])),
        }
        # Verified rows (the ones with a city) first.
        for row in conn.execute(
            "SELECT title, employer_name, city FROM jobs WHERE company_id = ?"
            " ORDER BY url IS NULL, title COLLATE NOCASE, job_id",
            (company_id,),
        )
    ]
    return {
        "available": bool(rows),
        "count": f"{len(rows):,}" if rows else NOT_AVAILABLE,
        "rows": rows,
    }
