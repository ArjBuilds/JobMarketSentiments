import sqlite3

import pytest

from jmsa.display import NOT_AVAILABLE
from jmsa.library import SORT_KEYS, column_headers, display_row, load_library
from jmsa.turnover import PRE_MERGER_NOTE, WINDOW_END, WINDOW_PERIOD, WINDOW_START, read_turnover

# The library fixture holds acme, globex and initech.


def add_proxy(db, company_id, n, matched, leaving, layoffs):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, proxy_share,"
        " reviews_in_window, reviews_matched, reviews_leaving, reviews_layoffs, definition, entity,"
        " method_note) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'def', 'Glassdoor reviews', 'note')",
        (company_id, WINDOW_PERIOD, WINDOW_START, WINDOW_END, matched / n, n, matched, leaving, layoffs),
    )


def add_published(db, company_id, pct=12.5, period="FY2024-25", end="2025-03-31"):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, definition, entity,"
        " source_url, source_ref, retrieved_on) VALUES (?, 0, ?, ?, ?, 'voluntary attrition, LTM',"
        " 'Acme Ltd (group)', 'https://acme.example/ar.pdf', 'p. 40', '2026-10-22')",
        (company_id, period, end, pct),
    )


# --- Company page ------------------------------------------------------------

def test_nothing_recorded_is_not_available(library):
    figures = read_turnover(library, "acme")
    assert figures["published"] == [] and figures["proxy"] == NOT_AVAILABLE and figures["note"] is None


def test_the_proxy_is_per_100_reviews_with_its_split_and_never_a_percentage(library):
    add_proxy(library, "acme", 1000, 61, 40, 21)
    text = read_turnover(library, "acme")["proxy"]
    assert text.startswith("6.1 per 100 reviews (leaving/attrition 4.0, layoffs 2.1), from 1,000 reviews")
    assert "Apr 2021 – Mar 2023" in text
    assert "%" not in text


def test_under_20_reviews_the_proxy_is_hidden_with_its_count(library):
    add_proxy(library, "acme", 19, 5, 5, 0)
    assert read_turnover(library, "acme")["proxy"] == "hidden: fewer than 20 reviews (19)"
    add_proxy(library, "globex", 20, 5, 5, 0)
    assert read_turnover(library, "globex")["proxy"].startswith("25.0 per 100 reviews")


def test_published_and_proxy_are_both_returned_separately(library):
    add_published(library, "acme", period="FY2023-24", end="2024-03-31", pct=14.0)
    add_published(library, "acme")
    add_proxy(library, "acme", 100, 6, 4, 2)
    figures = read_turnover(library, "acme")
    assert [f["period"] for f in figures["published"]] == ["FY2024-25", "FY2023-24"]   # latest first
    assert figures["published"][0]["value"] == "12.5%"
    assert figures["published"][0]["entity"] == "Acme Ltd (group)"
    assert figures["proxy"].startswith("6.0 per 100 reviews")


def test_pre_merger_note_comes_from_review_summary(library):
    add_proxy(library, "acme", 100, 6, 4, 2)
    library.execute("INSERT INTO review_summary (company_id, period, review_count, pre_merger_count)"
                    " VALUES ('acme', 'all', 100, 100)")
    assert read_turnover(library, "acme")["note"] == PRE_MERGER_NOTE


# --- Library page ----------------------------------------------------------------

def test_library_shows_the_proxy_total_and_split_as_two_columns(library):
    add_proxy(library, "acme", 1000, 61, 40, 21)
    add_proxy(library, "globex", 10, 1, 1, 0)
    rows = {r["company_id"]: display_row(r, "all") for r in load_library(library)}
    headers = column_headers("all")
    assert rows["acme"][headers["proxy"]] == "6.1"
    assert rows["acme"][headers["proxy_split"]] == "leaving/attrition 4.0 · layoffs 2.1"
    assert rows["globex"][headers["proxy"]] == "hidden: fewer than 20 reviews (10)"
    assert rows["initech"][headers["proxy"]] == NOT_AVAILABLE
    assert "proxy" in headers["proxy"].lower()


def test_the_proxy_joins_without_duplicating_companies(library):
    add_proxy(library, "acme", 100, 6, 4, 2)
    library.executemany("INSERT INTO review_summary (company_id, period, review_count, pre_merger_count)"
                        " VALUES ('acme', ?, 100, 0)", [("all",), ("2020-2023",)])
    assert [r["company_id"] for r in load_library(library)] == ["acme", "globex", "initech"]


def test_the_proxy_is_never_a_sort_key():
    assert not any("proxy" in key or "turnover" in key or "attrition" in key for key in SORT_KEYS)


# --- the schema keeps the two kinds apart -------------------------------------

def test_a_proxy_row_cannot_carry_an_attrition_percentage(library):
    with pytest.raises(sqlite3.IntegrityError):
        library.execute(
            "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, proxy_share,"
            " reviews_in_window, definition, entity, method_note)"
            " VALUES ('acme', 1, 'p', '2023-03-31', 6.1, 0.061, 100, 'd', 'e', 'n')"
        )


@pytest.mark.parametrize("source_url, source_ref", [
    (None, "p. 40"), ("http://acme.example/ar.pdf", "p. 40"), ("https://acme.example/ar.pdf", None),
])
def test_a_published_row_needs_an_https_source_and_a_reference(library, source_url, source_ref):
    with pytest.raises(sqlite3.IntegrityError):
        library.execute(
            "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, definition,"
            " entity, source_url, source_ref, retrieved_on)"
            " VALUES ('acme', 0, 'FY25', '2025-03-31', 12.5, 'd', 'e', ?, ?, '2026-10-22')",
            (source_url, source_ref),
        )


def test_a_published_percentage_must_be_0_to_100(library):
    with pytest.raises(sqlite3.IntegrityError):
        add_published(library, "acme", pct=112.0)
