import sqlite3

import pytest

from jmsa.display import NOT_AVAILABLE
from jmsa.library import SORT_KEYS, Filters, apply, column_headers, display_row, load_library
from jmsa.turnover import PRE_MERGER_NOTE, WINDOW_END, WINDOW_PERIOD, WINDOW_START, read_turnover

# The library fixture holds acme, globex and initech.


def add_proxy(db, company_id, n, matched, leaving, layoffs):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, proxy_share,"
        " reviews_in_window, reviews_matched, reviews_leaving, reviews_layoffs, definition, entity,"
        " method_note) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'def', 'Glassdoor reviews', 'note')",
        (company_id, WINDOW_PERIOD, WINDOW_START, WINDOW_END, matched / n, n, matched, leaving, layoffs),
    )


def add_published(db, company_id, pct=12.5, period="FY2024-25", end="2025-03-31", text=None,
                  basis="voluntary", scope="group", start=None):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, attrition_pct,"
        " attrition_text, basis, scope, definition, entity, source_url, source_ref, retrieved_on)"
        " VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, 'voluntary attrition, LTM', 'Acme Ltd (group)',"
        " 'https://acme.example/ar.pdf', 'p. 40', '2026-10-22')",
        (company_id, period, start, end, pct, text or f"{pct:g}", basis, scope),
    )


# --- Company page ------------------------------------------------------------

def test_nothing_recorded_is_not_available(library):
    figures = read_turnover(library, "acme")
    assert figures["published"] is None and figures["proxy"] == NOT_AVAILABLE and figures["note"] is None


def test_the_proxy_is_per_100_reviews_with_its_split_and_never_a_percentage(library):
    add_proxy(library, "acme", 1000, 61, 40, 21)
    text = read_turnover(library, "acme")["proxy"]
    assert text.startswith("6.1 per 100 reviews (leaving/attrition 4.0, layoffs 2.1), from 1,000 reviews")
    assert "Apr 2021 – Mar 2023" in text
    assert "%" not in text


def test_under_20_reviews_the_proxy_is_hidden_with_its_count(library):
    add_proxy(library, "acme", 19, 5, 5, 0)
    assert read_turnover(library, "acme")["proxy"] == "Fewer than 20 reviews (n = 19)"
    add_proxy(library, "globex", 20, 5, 5, 0)
    assert read_turnover(library, "globex")["proxy"].startswith("25.0 per 100 reviews")


def test_only_the_latest_published_figure_is_shown_beside_the_proxy(library):
    # Older rows are kept for the proxy comparison, never displayed.
    add_published(library, "acme", period="FY2022-23", end="2023-03-31", pct=20.1)
    add_published(library, "acme")
    add_proxy(library, "acme", 100, 6, 4, 2)
    figures = read_turnover(library, "acme")
    published = figures["published"]
    assert published["period"] == "FY2024-25" and published["value"] == "12.5%"
    assert (published["basis"], published["scope"]) == ("voluntary", "group")
    assert published["entity"] == "Acme Ltd (group)" and published["retrieved_on"] == "2026-10-22"
    assert figures["proxy"].startswith("6.0 per 100 reviews")


def test_a_published_value_is_shown_as_printed(library):
    # Accenture prints "13": showing "13.0%" would claim a precision it never gave.
    add_published(library, "acme", pct=13.0, text="13")
    add_published(library, "globex", pct=8.8, text="8.80", basis="not-stated", scope="india-subsidiary")
    assert read_turnover(library, "acme")["published"]["value"] == "13%"
    globex = read_turnover(library, "globex")["published"]
    assert globex["value"] == "8.80%"
    assert (globex["basis"], globex["scope"]) == ("basis not stated", "India subsidiary")


def test_no_published_figure_is_none(library):
    add_proxy(library, "acme", 100, 6, 4, 2)
    assert read_turnover(library, "acme")["published"] is None


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
    assert rows["globex"][headers["proxy"]] == "Fewer than 20 reviews (n = 10)"
    assert rows["initech"][headers["proxy"]] == NOT_AVAILABLE
    assert "proxy" in headers["proxy"].lower()


def test_the_proxy_joins_without_duplicating_companies(library):
    add_proxy(library, "acme", 100, 6, 4, 2)
    library.executemany("INSERT INTO review_summary (company_id, period, review_count, pre_merger_count)"
                        " VALUES ('acme', ?, 100, 0)", [("all",), ("2020-2023",)])
    assert [r["company_id"] for r in load_library(library)] == ["acme", "globex", "initech"]


def test_the_proxy_is_never_a_sort_key():
    assert not any("proxy" in key or "turnover" in key for key in SORT_KEYS)


def test_the_attrition_sort_ranks_published_figures_only(library):
    # globex has only a proxy, so it has no attrition value and sorts last.
    add_published(library, "acme", pct=14.0)
    add_published(library, "initech", pct=9.0)
    add_proxy(library, "globex", 1000, 900, 900, 0)
    ranked = apply(load_library(library), Filters(), "attrition")
    assert [r["company_id"] for r in ranked] == ["initech", "acme", "globex"]
    ranked = apply(load_library(library), Filters(), "attrition", descending=True)
    assert [r["company_id"] for r in ranked] == ["acme", "initech", "globex"]


def test_the_library_uses_the_latest_figure_of_each_company(library):
    add_published(library, "acme", pct=20.1, period="FY2022-23", end="2023-03-31")
    add_published(library, "acme", pct=12.5)
    records = load_library(library)
    assert len(records) == 3          # the older row does not duplicate acme
    assert next(r for r in records if r["company_id"] == "acme")["attrition"] == 12.5


def test_basis_and_scope_filters_compare_like_with_like(library):
    add_published(library, "acme", basis="voluntary", scope="segment")
    add_published(library, "globex", basis="not-stated", scope="india-subsidiary")
    records = load_library(library)

    def ids(filters):
        return [r["company_id"] for r in apply(records, filters)]

    assert ids(Filters(attrition_basis="voluntary")) == ["acme"]
    assert ids(Filters(attrition_basis="not-stated")) == ["globex"]
    assert ids(Filters(attrition_scope="india-subsidiary")) == ["globex"]
    assert ids(Filters()) == ["acme", "globex", "initech"]


def test_the_library_cell_carries_basis_scope_and_period(library):
    add_published(library, "acme", pct=12.8, basis="voluntary", scope="segment", period="LTM to Sep 2026")
    rows = {r["company_id"]: display_row(r, "all") for r in load_library(library)}
    header = column_headers("all")["attrition"]
    assert rows["acme"][header] == "12.8% · voluntary · segment · LTM to Sep 2026"
    assert rows["globex"][header] == NOT_AVAILABLE


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
            "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, attrition_text,"
            " basis, scope, definition, entity, source_url, source_ref, retrieved_on)"
            " VALUES ('acme', 0, 'FY25', '2025-03-31', 12.5, '12.5', 'voluntary', 'group', 'd', 'e', ?, ?,"
            " '2026-10-22')",
            (source_url, source_ref),
        )


def test_a_published_percentage_must_be_0_to_100(library):
    with pytest.raises(sqlite3.IntegrityError):
        add_published(library, "acme", pct=112.0)


@pytest.mark.parametrize("column, value", [("basis", "mostly voluntary"), ("scope", "india")])
def test_basis_and_scope_take_only_the_fixed_values(library, column, value):
    with pytest.raises(sqlite3.IntegrityError):
        add_published(library, "acme", **{column: value})


def test_a_published_row_needs_basis_scope_and_printed_value(library):
    with pytest.raises(sqlite3.IntegrityError):
        library.execute(
            "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, definition,"
            " entity, source_url, source_ref, retrieved_on) VALUES ('acme', 0, 'FY25', '2025-03-31', 12.5,"
            " 'd', 'e', 'https://acme.example/ar.pdf', 'p. 40', '2026-10-22')"
        )
