from datetime import date

import pytest

from jmsa.display import NOT_AVAILABLE
from jmsa.freshness import (
    attrition_dates,
    freshness_notes,
    freshness_table,
    last_refreshed,
    naukri_dates,
    news_dates,
    proxy_window,
    read_freshness,
    review_end,
    review_range,
    snapshot_month,
    source_line,
    sources_rows,
    sparse_note,
)
from jmsa.jobs import link_date

LINK = "https://www.naukri.com/job-listings-data-analyst-acme-pune-2-to-5-years-{id}"


def add_summary(db, company_id, first, last, period="all"):
    db.execute(
        "INSERT INTO review_summary (company_id, period, review_count, first_date, last_date,"
        " pre_merger_count) VALUES (?, ?, 100, ?, ?, 0)",
        (company_id, period, first, last),
    )


def add_job(db, number, company_id="acme", url=None, loaded_at="2026-10-21T17:13:15+00:00"):
    db.execute(
        "INSERT INTO jobs (job_id, company_id, title, url, loaded_at) VALUES (?, ?, 'Data Analyst', ?, ?)",
        (f"nk-{number}", company_id, url, loaded_at),
    )


def add_fetch(db, company_id, fetched_at):
    db.execute(
        "INSERT INTO news_fetches (company_id, fetched_at, query, window_from, returned,"
        " dropped_irrelevant, dropped_duplicate, kept, response_json) VALUES (?, ?, 'q', ?, 0, 0, 0, 0, '{}')",
        (company_id, fetched_at, fetched_at),
    )


def add_published(db, company_id, period, end, retrieved_on):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, attrition_pct,"
        " attrition_text, basis, scope, definition, entity, source_url, source_ref, retrieved_on)"
        " VALUES (?, 0, ?, '2025-04-01', ?, 12.0, '12.0', 'voluntary', 'group', 'd', 'e',"
        " 'https://example.com/ar.pdf', 'p. 4', ?)",
        (company_id, period, end, retrieved_on),
    )


def add_proxy(db, company_id, start="2021-04-01", end="2023-03-31"):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, proxy_share,"
        " reviews_in_window, reviews_matched, reviews_leaving, reviews_layoffs, definition, entity,"
        " method_note) VALUES (?, 1, 'w', ?, ?, 0.05, 100, 5, 3, 2, 'd', 'e', 'm')",
        (company_id, start, end),
    )


# --- the job-ID date ---------------------------------------------------------

def test_link_date_reads_ddmmyy_from_the_job_id():
    assert link_date(LINK.format(id="261023500868")) == date(2023, 10, 26)


def test_link_date_is_none_without_a_valid_id():
    assert link_date(None) is None
    assert link_date("https://www.naukri.com/some-other-page") is None
    assert link_date(LINK.format(id="991323500868")) is None   # day 99, month 13


# --- an empty database -------------------------------------------------------

def test_every_reader_says_not_available_on_an_empty_database(library):
    for reader in (review_range, review_end, snapshot_month, naukri_dates, news_dates,
                   attrition_dates, proxy_window, last_refreshed):
        assert reader(library) == NOT_AVAILABLE, reader.__name__


def test_freshness_values_are_text_even_when_empty(library):
    for row in freshness_table(read_freshness(library)):
        assert set(row) == {"Source", "Used for", "Dates", "Licence"}
        for value in row.values():
            assert isinstance(value, str) and value.strip()
    assert read_freshness(library)["ratings"]["Dates"].startswith(NOT_AVAILABLE)


# --- reviews -----------------------------------------------------------------

def test_review_range_spans_every_company_and_notes_the_sparse_tail(library):
    add_summary(library, "acme", "2012-03-04", "2023-07-06")
    add_summary(library, "globex", "2008-01-31", "2022-11-30")
    add_summary(library, "globex", "2020-01-02", "2023-12-31", period="2020-2023")   # not 'all': ignored
    assert review_range(library) == "Jan 2008 – Jul 2023 (sparse after Mar 2023)"
    assert review_end(library) == "Jul 2023 (sparse after Mar 2023)"


def test_no_sparse_note_when_the_reviews_end_inside_the_window(library):
    add_summary(library, "acme", "2015-01-01", "2023-03-31")
    assert review_range(library) == "Jan 2015 – Mar 2023"
    assert sparse_note("2023-03-31") == ""
    assert sparse_note(None) == ""
    assert sparse_note("2023-04-01") == " (sparse after Mar 2023)"


# --- postings ----------------------------------------------------------------

def test_naukri_dates_use_the_newest_stored_link_and_the_load_time(library):
    add_job(library, 1, url=LINK.format(id="120422100001"))     # 12 Apr 2022
    add_job(library, 2, url=LINK.format(id="271023100002"))     # 27 Oct 2023, the newest
    add_job(library, 3, url=None)                                # unverified: no link
    text = naukri_dates(library)
    assert text.startswith("collected in or after 27 Oct 2023 (")
    assert text.endswith("; loaded 21 Oct 2026")
    assert snapshot_month(library) == "Oct 2023"


def test_naukri_dates_without_any_link_still_give_the_load_time(library):
    add_job(library, 1, url=None)
    assert naukri_dates(library) == f"collection date {NOT_AVAILABLE}; loaded 21 Oct 2026"
    assert snapshot_month(library) == NOT_AVAILABLE


# --- news, attrition, proxy --------------------------------------------------

def test_news_dates_one_day(library):
    add_fetch(library, "acme", "2026-10-21T17:54:57Z")
    add_fetch(library, "globex", "2026-10-21T18:13:45Z")
    assert news_dates(library).startswith("fetched 21 Oct 2026 for 2 of 3 companies;")


def test_news_dates_range(library):
    add_fetch(library, "acme", "2026-10-21T17:54:57Z")
    add_fetch(library, "globex", "2026-10-23T08:00:00Z")
    assert news_dates(library).startswith("fetched 21 Oct 2026 – 23 Oct 2026 for 2 of 3 companies;")


def test_attrition_dates_read_retrieved_on_from_published_rows_only(library):
    add_published(library, "acme", "FY2025-26", "2026-03-31", "2026-10-22")
    add_published(library, "globex", "FY2025-26", "2026-03-31", "2026-10-20")
    add_proxy(library, "acme")    # proxy rows have no retrieved_on and are ignored
    assert attrition_dates(library) == ("periods vary by company (shown with each figure); "
                                        "retrieved 20 Oct 2026 – 22 Oct 2026")


def test_last_refreshed_is_the_newest_load_fetch_or_retrieval(library):
    add_job(library, 1, loaded_at="2026-10-21T17:13:15+00:00")
    add_fetch(library, "acme", "2026-10-21T17:54:57Z")
    add_published(library, "acme", "FY2025-26", "2026-03-31", "2026-10-22")   # the newest
    add_proxy(library, "globex")    # no date of its own: ignored
    assert last_refreshed(library) == "22 Oct 2026"


def test_last_refreshed_uses_whichever_sources_are_loaded(library):
    add_fetch(library, "acme", "2026-10-19T08:15:00Z")
    assert last_refreshed(library) == "19 Oct 2026"


def test_proxy_window_is_read_from_the_stored_rows(library):
    add_proxy(library, "acme", "2021-04-01", "2023-03-31")
    assert proxy_window(library) == "reviews dated Apr 2021 – Mar 2023"


@pytest.mark.parametrize("key", ["ratings", "reviews", "roles", "skills", "news", "attrition", "proxy"])
def test_source_line_names_the_source_and_its_dates(library, key):
    freshness = read_freshness(library)
    line = source_line(freshness, key)
    assert line == f"Source: {freshness[key]['Source']}; {freshness[key]['Dates']}."


# --- the short form the pages show ---------------------------------------------

def test_freshness_notes_are_source_and_date_only(library):
    add_summary(library, "acme", "2012-03-04", "2023-07-06")
    add_job(library, 1, url=LINK.format(id="271023100002"))
    add_fetch(library, "acme", "2026-10-22T08:00:00Z")
    add_published(library, "acme", "FY2025-26", "2026-03-31", "2026-10-22")
    add_proxy(library, "acme")
    notes = freshness_notes(library)
    assert notes == {
        "reviews": "Glassdoor reviews · to Jul 2023",
        "proxy": "Glassdoor reviews · Apr 2021 – Mar 2023",
        "ratings": "Glassdoor ratings · date not recorded",
        "roles": "Naukri postings · Oct 2023 snapshot",
        "skills": "Naukri postings · Oct 2023 snapshot",
        "news": "GNews · fetched 22 Oct 2026",
        "attrition": "Company reports · retrieved 22 Oct 2026",
    }


def test_freshness_notes_say_not_available_on_an_empty_database(library):
    notes = freshness_notes(library)
    assert notes["reviews"] == f"Glassdoor reviews · {NOT_AVAILABLE}"
    assert notes["news"] == f"GNews · {NOT_AVAILABLE}"
    assert notes["ratings"] == "Glassdoor ratings · date not recorded"


def test_sources_rows_name_the_review_dataset_and_its_licence(library):
    add_summary(library, "acme", "2008-01-31", "2023-07-06")
    rows = sources_rows(library)
    assert set(rows[0]) == {"Source", "Used for", "Dates"}
    reviews = rows[0]
    assert "davidgauthier/glassdoor-job-reviews-2" in reviews["Source"] and "CC BY-NC-SA 4.0" in reviews["Source"]
    assert reviews["Dates"] == "Jan 2008 – Jul 2023"
    assert [r["Dates"] for r in rows if r["Used for"] == "Glassdoor rating"] == ["Date not recorded"]
