"""How the market-wide data-role skills (F7) are read and shown.

One definition for the Market skills and Company pages, with no Streamlit or
spaCy code, so the tests call it directly. The counts come from
process.skill_counts. They are market-wide: the postings source doesn't tie
skills to an employer, so no company has skills of its own.
"""

from __future__ import annotations

import sqlite3

from jmsa.display import NOT_AVAILABLE

# The three Naukri exports in naukri_jobs_merged.csv (its source_file column).
EXPORTS = (
    "NaukriData_Data_Science",
    "NaukriData_data_analytics",
    "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data",
)
# 87-91% of these two exports' titles name a data role, against 38% of the
# analytics export, so only these two make the headline.
DATA_SCIENCE_EXPORTS = (EXPORTS[0], EXPORTS[2])
HEADLINE_SCOPE = "data-science"

SCOPE_LABELS = {
    HEADLINE_SCOPE: "Both data-science exports (headline)",
    EXPORTS[0]: "Data_Science export",
    EXPORTS[2]: "Data_Scientist_and_Data_Analytics export",
    EXPORTS[1]: "data_analytics export (not in headline)",
}

TYPES = ("tool", "method")
# The toggle on the Market skills page -> the type it shows. The first is the default.
VIEWS = {"Tools": "tool", "Methods": "method", "All": None}

TOP_N = 10

# Fewer distinct skill lists than this and the chart is hidden, as with the
# 20-review rule for sentiment.
MIN_SCORED_POSTINGS = 20

MARKET_SKILLS_NOTE = (
    "Market-wide: Indian data-role postings on Naukri, from the same dataset snapshot as the "
    "data-role listings. Not specific to any company: the source's skills column is misaligned row by row "
    "and describes other postings, so skills can't be tied to an employer. Listings were scraped "
    "repeatedly and their skill lists copied, so each distinct skill list counts once and counts are "
    "a lower bound. Shares in every view are of the same base: all distinct skill lists scored."
)

COMPANY_SKILLS_NOTE = (
    f"Data-role skills for this company: **{NOT_AVAILABLE}**. The postings source doesn't tie skills "
    "to an employer. See the **Market skills** page for market-wide data-role skills."
)


def scored(conn: sqlite3.Connection, scope: str) -> int:
    """Distinct skill lists scored in a scope; 0 if the scope has no counts."""
    row = conn.execute("SELECT MAX(scope_postings) FROM skill_counts WHERE scope = ?", (scope,)).fetchone()
    return row[0] or 0


def read_market_skills(conn: sqlite3.Connection, view: str = "Tools", scope: str = HEADLINE_SCOPE) -> dict:
    """A scope's top skills for one view of the toggle, ready to chart.

    available is False, with no rows, when fewer than MIN_SCORED_POSTINGS
    lists were scored or nothing matched; the page then hides the chart.
    """
    if view not in VIEWS:
        raise ValueError(f"view must be one of {list(VIEWS)}, not {view!r}")
    kind = VIEWS[view]
    n = scored(conn, scope)
    rows = [
        {"Skill": row["skill"], "Postings": row["postings"], "Share": row["share"]}
        for row in conn.execute(
            "SELECT skill, postings, share FROM skill_counts WHERE scope = ? AND (? IS NULL OR type = ?)"
            " ORDER BY postings DESC, skill LIMIT ?",
            (scope, kind, kind, TOP_N),
        )
    ]
    available = n >= MIN_SCORED_POSTINGS and bool(rows)
    return {"available": available, "scored": n, "rows": rows if available else []}


def read_export_comparison(conn: sqlite3.Connection, view: str = "Tools") -> list[dict]:
    """The headline top skills for a view, with their share in every scope, as display text.

    A scope with too few lists scored reads "not available". A skill an
    export's lists never mention reads 0.0%: the export was scored, so
    that's a count, not a gap.
    """
    headline = read_market_skills(conn, view)
    if not headline["available"]:
        return []
    shares = {scope: {} for scope in SCOPE_LABELS}
    for row in conn.execute("SELECT scope, skill, share FROM skill_counts"):
        if row["scope"] in shares:
            shares[row["scope"]][row["skill"]] = row["share"]
    enough = {scope: scored(conn, scope) >= MIN_SCORED_POSTINGS for scope in SCOPE_LABELS}
    return [
        {"Skill": row["Skill"], **{
            label: f"{shares[scope].get(row['Skill'], 0):.1%}" if enough[scope] else NOT_AVAILABLE
            for scope, label in SCOPE_LABELS.items()
        }}
        for row in headline["rows"]
    ]


def read_scope_sizes(conn: sqlite3.Connection) -> list[dict]:
    """Distinct skill lists scored per scope, for the comparison's caption table."""
    sizes = []
    for scope, label in SCOPE_LABELS.items():
        n = scored(conn, scope)
        sizes.append({"Scope": label, "Distinct skill lists": f"{n:,}" if n else NOT_AVAILABLE})
    return sizes
