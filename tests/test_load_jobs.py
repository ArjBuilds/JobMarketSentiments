import csv

import pytest

from ingest.load_jobs import (
    JobsError,
    build_report,
    cities_from_slug,
    is_data_role,
    link_tail,
    load_jobs,
    posted_text,
    read_keywords,
)

# The library fixture holds acme, globex and initech.


def link(slug, job_id="261023500868"):
    """A Naukri link for a slug, with the experience band and job ID it always ends in."""
    return f"https://www.naukri.com/job-listings-{slug}-3-to-5-years-{job_id}"


def write_aliases(tmp_path, rows=()):
    """rows: (company_id, alias_in_dataset) for the naukri source."""
    path = tmp_path / "aliases.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company_id", "alias_in_dataset", "source"])
        writer.writerows([(company_id, alias, "naukri") for company_id, alias in rows])
    return path


@pytest.fixture
def load(library, tmp_path, write_jobs):
    """Load rows of postings into the library database; returns the result."""
    def run(rows, aliases=(), rejected=None):
        kwargs = {} if rejected is None else {"rejected": rejected}
        return load_jobs(library, write_jobs(rows), write_aliases(tmp_path, aliases), **kwargs)
    return run


def jobs(db):
    return {row["job_id"]: dict(row) for row in db.execute("SELECT * FROM jobs")}


# --- matching ----------------------------------------------------------------

def test_exact_name_matches_after_normalising(load, library):
    load([{"job_title": "Data Analyst", "company_name": "ACME"}])
    assert jobs(library)["nk-1"]["company_id"] == "acme"


def test_alias_matches_and_the_posted_name_is_kept(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Globex India Pvt Ltd"}],
         aliases=[("globex", "Globex India Pvt Ltd")])
    row = jobs(library)["nk-1"]
    assert row["company_id"] == "globex"
    assert row["employer_name"] == "Globex India Pvt Ltd"


def test_agency_posting_for_a_client_is_not_matched(load, library):
    result = load([{"job_title": "Data Analyst", "company_name": "ABC Consultants hiring for Acme"}])
    assert jobs(library) == {}
    assert result["unmatched"] == 1


def test_a_rejected_name_never_matches_even_exactly(load, library):
    result = load([{"job_title": "Data Analyst", "company_name": "Acme"}],
                  rejected={"Acme": "a namesake"})
    assert jobs(library) == {}
    assert result["rejected_seen"] == {"Acme": 1}


def test_an_alias_on_a_rejected_name_fails_and_writes_nothing(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Acme"}])
    with pytest.raises(JobsError, match="REJECTED_NAMES"):
        load([{"job_title": "Data Analyst", "company_name": "Acme Insurance"}],
             aliases=[("acme", "Acme Insurance")], rejected={"Acme Insurance": "different line of work"})
    assert list(jobs(library)) == ["nk-1"]   # the earlier load is untouched


@pytest.mark.parametrize("alias, message", [
    (("hooli", "Hooli"), "not in companies"),
    (("acme", "Acme Labs"), "not a company_name in the postings file"),
])
def test_bad_aliases_fail(load, alias, message):
    with pytest.raises(JobsError, match=message):
        load([{"job_title": "Data Analyst", "company_name": "Acme"}], aliases=[alias])


def test_an_empty_library_fails(db, tmp_path, write_jobs):
    with pytest.raises(JobsError, match="companies table is empty"):
        load_jobs(db, write_jobs([]), write_aliases(tmp_path))


# --- title filter and counts -----------------------------------------------

@pytest.mark.parametrize("title, kept", [
    ("Data Scientist", True),
    ("Senior Business Intelligence Analyst", True),
    ("ML Engineer", True),
    ("Telecaller", False),
    ("Data Entry Operator", False),       # excluded although it says "data"
    ("Sr. Data Analyst II Hybrid Model", True),   # "model" alone is not a keyword
    ("Manager - Hybrid Model", False),
    ("Sales Manager", False),
    ("Snowflake Developer", True),
    ("Spark Scala Developer", True),
])
def test_title_filter(title, kept):
    assert is_data_role(title, *read_keywords()) is kept


@pytest.mark.parametrize("title, kept", [
    ("Business Analyst", False),
    ("Senior Business Analyst", False),
    ("Business Analyst - Requirements Analysis", False),   # "analysis" is not data-specific
    ("Business Analyst (Life Science)", False),             # nor is "science" on its own
    ("Business Analyst - Data Science", True),
    ("Senior Business Analyst - BI", True),
    ("Business Analyst || C# and SQL", True),
])
def test_business_analyst_is_kept_only_with_a_data_keyword(title, kept):
    assert is_data_role(title, *read_keywords()) is kept


def test_the_business_analyst_exception_does_not_lift_other_excludes():
    assert not is_data_role("Business Analyst - Data Entry", *read_keywords())


def test_counts_for_dropped_unmatched_and_loaded(load):
    result = load([
        {"job_title": "Data Analyst", "company_name": "Acme"},
        {"job_title": "Telecaller", "company_name": "Acme"},
        {"job_title": "Data Analyst", "company_name": "Somebody Else"},
    ])
    assert result["read"] == 3
    assert sum(result["dropped_titles"].values()) == 1
    assert result["dropped_by_company"] == {"acme": 1}
    assert result["unmatched"] == 1
    assert result["loaded"] == 1


def test_loading_twice_gives_the_same_rows(load, library):
    rows = [{"job_title": "Data Analyst", "company_name": "Acme",
             "post_url": link("data-analyst-acme-pune"), "post_time_relative": "1 Day Ago"},
            {"job_title": "Data Engineer", "company_name": "Initech"},
            {"job_title": "Data Engineer", "company_name": "Initech"}]   # a duplicate
    load(rows)
    first = {job_id: {k: v for k, v in row.items() if k != "loaded_at"} for job_id, row in jobs(library).items()}
    load(rows)
    second = {job_id: {k: v for k, v in row.items() if k != "loaded_at"} for job_id, row in jobs(library).items()}
    assert first == second and sorted(second) == ["nk-1", "nk-2"]


# --- dedup -------------------------------------------------------------------

def test_verified_rows_are_deduplicated_by_job_id(load, library):
    url = link("data-analyst-acme-pune", "261023000001")
    result = load([{"job_title": "Data Analyst", "company_name": "Acme", "post_url": url},
                   {"job_title": "Data Analyst", "company_name": "Acme", "post_url": url}])
    assert list(jobs(library)) == ["nk-1"]
    assert result["matched"]["acme"] == 2 and result["loaded"] == 1


def test_verified_rows_with_the_same_title_and_different_ids_are_both_kept(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Acme",
           "post_url": link("data-analyst-acme-pune", "261023000001")},
          {"job_title": "Data Analyst", "company_name": "Acme",
           "post_url": link("data-analyst-acme-chennai", "261023000002")}])
    assert sorted(jobs(library)) == ["nk-1", "nk-2"]


def test_unverified_rows_are_collapsed_by_employer_and_title(load, library):
    # Titles and employers compare after normalising; the lowest job_row_id is kept.
    load([{"job_title": "Data Engineer", "company_name": "Acme", "job_row_id": "7"},
          {"job_title": "Data Engineer", "company_name": "Acme", "job_row_id": "3"},
          {"job_title": "DATA ENGINEER", "company_name": "ACME", "job_row_id": "5"},
          {"job_title": "Data Scientist", "company_name": "Acme", "job_row_id": "9"}])
    assert sorted(jobs(library)) == ["nk-3", "nk-9"]


def test_an_unverified_row_is_dropped_when_a_verified_row_has_its_title(load, library):
    # The unverified copy comes first in the file and is still dropped.
    load([{"job_title": "Data Analyst", "company_name": "Acme"},
          {"job_title": "Data Analyst", "company_name": "Acme", "post_url": link("data-analyst-acme-pune")}])
    assert list(jobs(library)) == ["nk-2"]
    assert jobs(library)["nk-2"]["city"] == "Pune"


def test_same_title_at_different_employers_is_not_collapsed(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Acme"},
          {"job_title": "Data Analyst", "company_name": "Initech"}])
    assert sorted(jobs(library)) == ["nk-1", "nk-2"]


# --- link verification -----------------------------------------------------

def test_a_verified_link_keeps_url_post_time_and_city(load, library):
    url = link("data-analyst-acme-india-pvt-ltd-bangalore-bengaluru")
    load([{"job_title": "Data Analyst", "company_name": "Acme", "post_url": url,
           "post_time_relative": "4 Days Ago", "locations": "Kolkata"}])
    row = jobs(library)["nk-1"]
    assert (row["url"], row["posted_relative"], row["city"]) == (url, "4 Days Ago", "Bengaluru")


def test_a_link_to_another_employer_is_dropped_with_its_time_and_city(load, library):
    # The common case in the source: same generic title, someone else's posting.
    load([{"job_title": "Data Analyst", "company_name": "Acme",
           "post_url": link("data-analyst-yes-securities-mumbai"), "post_time_relative": "1 Day Ago",
           "locations": "Mumbai"}])
    row = jobs(library)["nk-1"]
    assert (row["url"], row["posted_relative"], row["city"]) == (None, None, None)


def test_a_link_to_another_title_is_dropped(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Acme",
           "post_url": link("data-engineer-acme-pune")}])
    assert jobs(library)["nk-1"]["url"] is None


def test_the_library_name_verifies_a_link_when_the_posted_name_differs(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Globex Global Services Private Limited",
           "post_url": link("data-analyst-globex-india-pune")}],
         aliases=[("globex", "Globex Global Services Private Limited")])
    assert jobs(library)["nk-1"]["city"] == "Pune"


@pytest.mark.parametrize("slug, cities", [
    ("data-analyst-acme-bangalore-bengaluru", ["Bengaluru"]),
    ("data-analyst-acme-mumbai-new-delhi-delhi-ncr", ["Mumbai", "Delhi", "Delhi NCR"]),
    ("data-analyst-acme-navi-mumbai", ["Navi Mumbai"]),
    ("data-analyst-acme-shillong", []),
    ("data-analyst-acme-india", []),
])
def test_cities_are_read_after_the_employer(slug, cities):
    assert cities_from_slug(link_tail(link(slug), "Data Analyst", ["Acme"])) == cities


def test_a_city_inside_the_title_is_not_read():
    tail = link_tail(link("data-analyst-pune-acme-chennai"), "Data Analyst Pune", ["Acme"])
    assert cities_from_slug(tail) == ["Chennai"]


def test_ampersands_are_ignored_when_matching_the_employer():
    # normalise() spells "&" as "and"; a slug drops it.
    assert link_tail(link("data-analyst-procter-gamble-mumbai"), "Data Analyst", ["Procter & Gamble"]) == ["mumbai"]


@pytest.mark.parametrize("value, shown", [
    ("1 Day Ago", "1 Day Ago"),
    ("30+ Days Ago", "30+ Days Ago"),
    ("Few Hours Ago", "Few Hours Ago"),
    ("Just Now", "Just Now"),
    ("Starts in 1-3 months", None),
    ("Starts : 13th Nov' 23", None),
    ("", None),
])
def test_only_relative_post_times_are_kept(value, shown):
    assert posted_text(value) == shown


def test_unreliable_columns_are_never_stored(load, library):
    load([{"job_title": "Data Analyst", "company_name": "Acme", "skills_raw": "PythonSQL",
           "locations": "Pune", "experience_required": "2-5 Yrs"}])
    row = jobs(library)["nk-1"]
    assert row["skills_raw"] is None and row["city"] is None
    assert row["source"] == "naukri" and row["loaded_at"]


# --- report ----------------------------------------------------------------

def test_report_lists_unmatched_companies_with_unaccepted_suggestions(load):
    result = load([{"job_title": "Data Analyst", "company_name": "Acme"},
                   {"job_title": "Data Analyst", "company_name": "Globexx"},
                   {"job_title": "Telecaller", "company_name": "Initech"}])
    report = build_report(result)
    assert "matched to a library company:         1  (1 company)" in report
    assert "globex                       suggestions, not accepted: globexx (1)" in report
    assert "[1 matched, all dropped by the title filter]" in report
    assert "30 most common titles dropped by the title filter\n      1  Telecaller" in report


def test_report_shows_rows_before_and_after_dedup(load):
    report = build_report(load([{"job_title": "Data Analyst", "company_name": "Acme"},
                                {"job_title": "Data Analyst", "company_name": "Acme"},
                                {"job_title": "Data Engineer", "company_name": "Acme"}]))
    assert "Distinct listings loaded:               2  (1 duplicates removed)" in report
    assert "  acme                             3 ->    2  links    0  Acme (2)" in report
    assert "  TOTAL                            3 ->    2  links    0" in report
