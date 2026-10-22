"""Report-ready analysis tables (milestone 10). Writes nothing to the database.

Run with:  python -m process.analysis

Reads only data/jmsa.db, after every loader and process step has run, and
writes a markdown table and the CSVs behind it to docs/analysis/ for each of:

    a. Cohen's kappa for VADER against TextBlob labels, on the TextBlob
       check's own seeded 50k sample, next to the raw agreement
    b. the star-rating validation: sentiment methods A-F on the seed-42
       sample, and method F on the held-out sample
    c. theme sentiment against the matching Glassdoor sub-rating, per company
    d. yearly average sentiment for the 10 companies with the most reviews
    e. the turnover proxy against published attrition

a and b re-run process.sentiment_checks' own samples and helpers, so their
numbers are the ones in data/raw/sentiment_checks.txt; a re-runs TextBlob on
50,000 reviews, which takes a few minutes. No chart is drawn: the report's
charts are screenshots of the dashboard's own Plotly charts.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pandas as pd

from ingest.load_turnover import comparison_pairs
from jmsa.config import DB_PATH, REPO_ROOT
from jmsa.db import get_conn
from jmsa.display import NOT_AVAILABLE
from jmsa.freshness import sparse_note
from jmsa.sentiment import MIN_REVIEWS, THEME_NAMES, month_year
from jmsa.stats import MIN_PAIRS, cohens_kappa, landis_koch, ranks, spearman
from jmsa.turnover import WINDOW_TITLE
from process.sentiment_checks import (
    HELD_OUT_SEED, METHOD_SEED, fetch, method_scores, method_stats, rated_samples,
    textblob_crosstab, textblob_sample,
)

OUT_DIR = REPO_ROOT / "docs" / "analysis"

LABELS = ["negative", "neutral", "positive"]

# Each theme against the Glassdoor sub-rating that asks about the same thing.
THEME_SUBRATINGS = {
    "pay": "compensation_and_benefits",
    "culture": "culture_and_values",
    "wlb": "work_life_balance",
    "management": "senior_management",
}
MIN_MENTIONS = 100
DISAGREEMENTS = 3

TOP_COMPANIES = 10
FIRST_YEAR, LAST_YEAR = 2008, 2023


def md_table(headers: list[str], rows: list[list]) -> str:
    """A GitHub-flavoured markdown table; pandas' to_markdown needs tabulate."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def signed(value: float | None, places: int = 2) -> str:
    return NOT_AVAILABLE if value is None else f"{value:+.{places}f}"


# --- a. kappa ---------------------------------------------------------------

def kappa_from_crosstab(table: pd.DataFrame) -> tuple[list[list[int]], dict[str, float]]:
    """The 3x3 table in negative/neutral/positive order (a label neither tool
    used becomes a row and column of zeros) and its kappa figures."""
    table = table.reindex(index=LABELS, columns=LABELS, fill_value=0)
    counts = [[int(v) for v in row] for row in table.to_numpy()]
    return counts, cohens_kappa(counts)


def kappa_note(figures: dict[str, float]) -> str:
    return (f"VADER and TextBlob agree on {figures['p_o']:.1%} of labels (raw agreement); "
            f"Cohen's kappa {figures['kappa']:.2f}, {landis_koch(figures['kappa'])} (Landis-Koch).")


def section_kappa(conn: sqlite3.Connection) -> tuple[str, dict[str, pd.DataFrame]]:
    ids = textblob_sample(conn)
    crosstab, _ = textblob_crosstab(fetch(conn, ids))
    counts, figures = kappa_from_crosstab(crosstab)
    total = sum(map(sum, counts))
    rows = [[f"VADER {label}", *[f"{n:,}" for n in counts[i]], f"{sum(counts[i]):,}"]
            for i, label in enumerate(LABELS)]
    rows.append(["TextBlob total", *[f"{sum(r[j] for r in counts):,}" for j in range(3)], f"{total:,}"])
    text = "\n\n".join([
        "# a. VADER against TextBlob: raw agreement and Cohen's kappa",
        f"Sample: seed {METHOD_SEED}, {total:,} scored reviews (the TextBlob check in "
        "process/sentiment_checks.py). Both tools score headline, pros and cons separately, combined as "
        "mean(headline, mean(pros, cons)), with the same cut-offs (positive >= 0.05, negative <= -0.05).",
        md_table(["", "TextBlob negative", "TextBlob neutral", "TextBlob positive", "total"], rows),
        md_table(["measure", "value"], [
            ["raw agreement (p_o)", f"{figures['p_o']:.1%}"],
            ["chance agreement (p_e)", f"{figures['p_e']:.1%}"],
            ["Cohen's kappa", f"{figures['kappa']:.2f}"],
        ]),
        f"**{kappa_note(figures)}** Raw agreement is high mostly because both tools call most reviews "
        f"positive (VADER {sum(counts[2]) / total:.0%}, TextBlob {sum(r[2] for r in counts) / total:.0%}), "
        "so two tools labelling at random with those shares would already agree "
        f"{figures['p_e']:.0%} of the time. Kappa measures agreement beyond that.",
    ])
    matrix = pd.DataFrame(counts, index=pd.Index(LABELS, name="vader_label"),
                          columns=[f"textblob_{label}" for label in LABELS]).reset_index()
    summary = pd.DataFrame([{"reviews": total, "seed": METHOD_SEED, **figures}])
    return text, {"a_kappa_matrix.csv": matrix, "a_kappa.csv": summary}


# --- b. star-rating validation ----------------------------------------------

def section_star_validation(conn: sqlite3.Connection) -> tuple[str, dict[str, pd.DataFrame]]:
    method_ids, held_out_ids = rated_samples(conn)
    sample = fetch(conn, method_ids)
    records = [{"sample": f"seed {METHOD_SEED}", "reviews": len(sample), "method": name,
                **method_stats(scores, sample["rating"])}
               for name, scores in method_scores(sample).items()]
    if held_out_ids:
        held_out = fetch(conn, held_out_ids)
        records.append({"sample": f"seed {HELD_OUT_SEED} (held out)", "reviews": len(held_out),
                        "method": "F held-out", **method_stats(held_out["sentiment_compound"], held_out["rating"])})
    frame = pd.DataFrame(records)
    rows = [[r["method"], r["sample"], f"{r['reviews']:,}", f"{r['pearson']:.3f}", f"{r['spearman']:.3f}",
             f"{r['positive']:.0%} / {r['neutral']:.0%} / {r['negative']:.0%}", f"{r['agree_with_stars']:.1%}"]
            for r in records]
    text = "\n\n".join([
        "# b. Star-rating validation of the sentiment method",
        "Each method's review score against the review's star rating. Stars are labelled 4-5 positive, "
        "3 neutral, 1-2 negative for the agreement column. Method F is the one the pipeline uses; it was "
        f"chosen on the seed-{METHOD_SEED} sample, so it is re-checked on a separate held-out sample with "
        "no review in common.",
        md_table(["method", "sample", "reviews", "Pearson r", "Spearman", "pos / neu / neg",
                  "label agrees with stars"], rows),
        "C, pros minus cons, has no correlation with the stars: VADER already scores cons negative, so "
        "subtracting them cancels the signal.",
    ])
    return text, {"b_star_validation.csv": frame}


# --- c. themes against sub-ratings ------------------------------------------

def theme_subrating_rows(conn: sqlite3.Connection, theme: str) -> list[dict]:
    """Per company: the theme's compound and mention count (review_summary,
    all time) and the mean of the matching sub-rating over all its reviews.

    A company is kept when it has MIN_MENTIONS+ theme mentions and
    MIN_REVIEWS+ sub-ratings; a missing value is never filled in.
    """
    column = THEME_SUBRATINGS[theme]
    subratings = {row[0]: (row[1], row[2]) for row in conn.execute(
        f"SELECT company_id, AVG({column}), COUNT({column}) FROM reviews "
        f"WHERE {column} IS NOT NULL GROUP BY company_id")}
    rows = []
    for company_id, mentions, compound in conn.execute(
            f"SELECT company_id, {theme}_count, {theme}_compound FROM review_summary "
            f"WHERE period = 'all' AND {theme}_count >= ? AND {theme}_compound IS NOT NULL "
            "ORDER BY company_id", (MIN_MENTIONS,)):
        mean_rating, rated = subratings.get(company_id, (None, 0))
        if rated >= MIN_REVIEWS:
            rows.append({"company_id": company_id, "theme": theme, "mentions": mentions,
                         "theme_compound": compound, "subrating": column,
                         "subrating_mean": mean_rating, "subratings": rated})
    return rows


def theme_comparison(rows: list[dict]) -> dict:
    """Spearman across companies, and the companies whose ranks differ most.

    Ranks run from lowest to highest on each side, so a rank gap of 10 means
    the company sits 10 places apart in the two orderings.
    """
    compounds = [r["theme_compound"] for r in rows]
    means = [r["subrating_mean"] for r in rows]
    rank_theme, rank_rating = ranks(compounds), ranks(means)
    ranked = [r | {"rank_theme": a, "rank_subrating": b, "rank_gap": abs(a - b)}
              for r, a, b in zip(rows, rank_theme, rank_rating)]
    worst = sorted(ranked, key=lambda r: (-r["rank_gap"], r["company_id"]))[:DISAGREEMENTS]
    return {"n": len(rows), "spearman": spearman(compounds, means), "rows": ranked, "disagree": worst}


def section_themes(conn: sqlite3.Connection) -> tuple[str, dict[str, pd.DataFrame]]:
    results = {theme: theme_comparison(theme_subrating_rows(conn, theme)) for theme in THEME_SUBRATINGS}
    summary = [[THEME_NAMES[t], THEME_SUBRATINGS[t], r["n"],
                signed(r["spearman"]) if r["spearman"] is not None else f"{NOT_AVAILABLE} (needs {MIN_PAIRS}+)"]
               for t, r in results.items()]
    parts = [
        "# c. Theme sentiment against Glassdoor sub-ratings",
        "Per company: the theme's average VADER score over the reviews that mention it (review_summary, "
        "all time) against the company's mean sub-rating (1-5 stars) over all its reviews that have one. "
        f"Companies with at least {MIN_MENTIONS} theme mentions and {MIN_REVIEWS} sub-ratings. Spearman "
        "rank correlation across companies.",
        md_table(["theme", "sub-rating", "companies", "Spearman"], summary),
        f"## Where they disagree most\n\nThe {DISAGREEMENTS} companies per theme whose rank by theme "
        "sentiment and rank by sub-rating are furthest apart (rank 1 = lowest).",
    ]
    for theme, result in results.items():
        parts.append(f"### {THEME_NAMES[theme]} vs {THEME_SUBRATINGS[theme]}")
        parts.append(md_table(
            ["company", "mentions", "theme score", "rank", "sub-rating", "rank", "rank gap"],
            [[r["company_id"], f"{r['mentions']:,}", signed(r["theme_compound"], 3), f"{r['rank_theme']:g}",
              f"{r['subrating_mean']:.2f}", f"{r['rank_subrating']:g}", f"{r['rank_gap']:g}"]
             for r in result["disagree"]]))
    detail = pd.DataFrame([row for result in results.values() for row in result["rows"]])
    totals = pd.DataFrame([{"theme": t, "subrating": THEME_SUBRATINGS[t], "companies": r["n"],
                            "spearman": r["spearman"]} for t, r in results.items()])
    return "\n\n".join(parts), {"c_themes_vs_subratings.csv": totals,
                                "c_themes_vs_subratings_by_company.csv": detail}


# --- d. yearly sentiment ----------------------------------------------------

def top_companies(conn: sqlite3.Connection, limit: int = TOP_COMPANIES) -> list[str]:
    return [row[0] for row in conn.execute(
        "SELECT company_id FROM review_summary WHERE period = 'all' "
        "ORDER BY review_count DESC, company_id LIMIT ?", (limit,))]


def yearly_sentiment(conn: sqlite3.Connection, company_ids: list[str]) -> pd.DataFrame:
    """One row per company and year from FIRST_YEAR to LAST_YEAR: reviews scored and the
    average compound, None where fewer than MIN_REVIEWS (the 20-review rule)."""
    marks = ", ".join("?" for _ in company_ids)
    counts = {(c, int(y)): (n, avg) for c, y, n, avg in conn.execute(
        "SELECT company_id, substr(review_date, 1, 4), COUNT(*), AVG(sentiment_compound) FROM reviews "
        f"WHERE company_id IN ({marks}) AND sentiment_compound IS NOT NULL "
        "AND review_date >= ? AND review_date < ? GROUP BY 1, 2",
        [*company_ids, f"{FIRST_YEAR}-01-01", f"{LAST_YEAR + 1}-01-01"])}
    records = []
    for company_id in company_ids:
        for year in range(FIRST_YEAR, LAST_YEAR + 1):
            n, avg = counts.get((company_id, year), (0, None))
            records.append({"company_id": company_id, "year": year, "reviews": n,
                            "avg_compound": avg if n >= MIN_REVIEWS else None})
    return pd.DataFrame(records)


def last_review_date(conn: sqlite3.Connection, company_ids: list[str]) -> str | None:
    marks = ", ".join("?" for _ in company_ids)
    return conn.execute(f"SELECT MAX(review_date) FROM reviews WHERE company_id IN ({marks}) "
                        "AND sentiment_compound IS NOT NULL", company_ids).fetchone()[0]


def section_yearly(conn: sqlite3.Connection) -> tuple[str, dict[str, pd.DataFrame]]:
    companies = top_companies(conn)
    frame = yearly_sentiment(conn, companies)
    last = last_review_date(conn, companies)
    cell = {(r.company_id, r.year): (NOT_AVAILABLE if pd.isna(r.avg_compound)
                                     else f"{r.avg_compound:+.2f} ({r.reviews:,})")
            for r in frame.itertuples()}
    year_label = {year: str(year) for year in range(FIRST_YEAR, LAST_YEAR + 1)}
    if last and last[:4] == str(LAST_YEAR):
        year_label[LAST_YEAR] = f"{LAST_YEAR}*"
    rows = [[year_label[year], *[cell[(c, year)] for c in companies]]
            for year in range(FIRST_YEAR, LAST_YEAR + 1)]
    note = (f"\\* {LAST_YEAR} runs Jan to {month_year(last)}{sparse_note(last)}: reviews fall from about "
            "21,000 a month in March 2023 to a few hundred a month after it, so the "
            f"{LAST_YEAR} figure leans on the first quarter." if year_label[LAST_YEAR].endswith("*") else "")
    text = "\n\n".join(filter(None, [
        "# d. Yearly average review sentiment, top 10 companies by reviews",
        f"Average VADER compound per calendar year, with reviews scored in brackets. A year with fewer than "
        f"{MIN_REVIEWS} reviews shows \"{NOT_AVAILABLE}\" (the 20-review rule).",
        md_table(["year", *companies], rows),
        note,
    ]))
    return text, {"d_yearly_sentiment.csv": frame}


# --- e. proxy against published attrition -----------------------------------

def section_proxy(conn: sqlite3.Connection) -> tuple[str, dict[str, pd.DataFrame]]:
    pairs = comparison_pairs(conn)
    groups = (("IT majors (publish attrition quarterly)", [p for p in pairs if p["it_major"]]),
              ("All companies with both", pairs))
    correlations = []
    for title, group in groups:
        attrition = [p["attrition"] for p in group]
        correlations.append({"group": title, "companies": len(group),
                             "proxy_total": spearman([p["proxy"] for p in group], attrition),
                             "proxy_leaving": spearman([p["leaving"] for p in group], attrition)})
    text = "\n\n".join([
        "# e. Turnover proxy against published attrition",
        f"Companies with both a shown proxy (reviews dated {WINDOW_TITLE}) and a published figure whose "
        "period overlaps that window. Proxy and leaving are per 100 reviews; published is % of staff as "
        "printed.",
        md_table(["company", "published", "basis", "period", "proxy", "leaving/attrition part"],
                 [[p["company_id"], f"{p['attrition']:g}%", p["basis"], p["period"], f"{p['proxy']:.1f}",
                   f"{p['leaving']:.1f}"] for p in pairs]),
        md_table(["group", "companies", "Spearman: proxy", "Spearman: leaving part only"],
                 [[c["group"], c["companies"], signed(c["proxy_total"]), signed(c["proxy_leaving"])]
                  for c in correlations]),
        "**Finding:** the proxy doesn't track published attrition; the correlations are about zero. It "
        "measures what reviewers write about, not how many people leave.\n\n"
        "**Caveats:** samples this small (8 and 12) can't support a stronger claim either way. Periods "
        "differ in length and alignment (e.g. Accenture's fiscal year ends in August), definitions "
        "differ (basis voluntary or not stated), and ltimindtree's proxy is pre-merger Mindtree reviews "
        "compared with the merged company's figure.",
    ])
    return text, {"e_proxy_vs_attrition.csv": pd.DataFrame(pairs),
                  "e_proxy_vs_attrition_spearman.csv": pd.DataFrame(correlations)}


SECTIONS = {
    "a_kappa.md": section_kappa,
    "b_star_validation.md": section_star_validation,
    "c_themes_vs_subratings.md": section_themes,
    "d_yearly_sentiment.md": section_yearly,
    "e_proxy_vs_attrition.md": section_proxy,
}


def write_section(name: str, text: str, tables: dict[str, pd.DataFrame], out_dir: Path) -> None:
    (out_dir / name).write_text(text + "\n", encoding="utf-8")
    for csv_name, frame in tables.items():
        frame.to_csv(out_dir / csv_name, index=False, lineterminator="\n")


def main() -> int:
    # Checked before connecting, because get_conn would create an empty file.
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}; build it first (see README).", file=sys.stderr)
        return 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        for name, build in SECTIONS.items():
            text, tables = build(conn)
            write_section(name, text, tables, OUT_DIR)
            print(f"wrote docs/analysis/{name} and {', '.join(tables)}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
