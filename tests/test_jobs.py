from jmsa.display import NOT_AVAILABLE
from jmsa.jobs import read_roles

# The library fixture holds acme, globex and initech.


def add_job(db, job_id, company_id, url=None, city=None, posted=None, title="Data Analyst"):
    db.execute(
        "INSERT INTO jobs (job_id, company_id, employer_name, title, city, posted_relative, url, source)"
        " VALUES (?, ?, 'Acme India', ?, ?, ?, ?, 'naukri')",
        (job_id, company_id, title, city, posted, url),
    )


def test_a_company_with_no_postings_is_not_available(library):
    roles = read_roles(library, "globex")
    assert roles == {"available": False, "count": NOT_AVAILABLE, "rows": []}


def test_a_missing_city_reads_not_available(library):
    add_job(library, "nk-1", "acme")
    [row] = read_roles(library, "acme")["rows"]
    assert row == {"Title": "Data Analyst", "Employer (as posted)": "Acme India", "City": NOT_AVAILABLE}


def test_link_and_post_time_are_stored_but_not_shown(library):
    # Expired 2023 links and "1 Day Ago" would mislead; they stay in jobs only.
    add_job(library, "nk-1", "acme", url="https://www.naukri.com/x", city="Pune", posted="1 Day Ago")
    [row] = read_roles(library, "acme")["rows"]
    assert list(row) == ["Title", "Employer (as posted)", "City"]
    assert tuple(library.execute("SELECT url, posted_relative FROM jobs").fetchone()) == \
        ("https://www.naukri.com/x", "1 Day Ago")


def test_cities_are_comma_joined_and_linked_rows_come_first(library):
    add_job(library, "nk-1", "acme", title="A unlinked role")
    add_job(library, "nk-2", "acme", url="https://www.naukri.com/x", city="Mumbai;Delhi",
            posted="1 Day Ago", title="B linked role")
    roles = read_roles(library, "acme")
    assert roles["count"] == "2"
    assert [r["Title"] for r in roles["rows"]] == ["B linked role", "A unlinked role"]
    assert roles["rows"][0]["City"] == "Mumbai, Delhi"
