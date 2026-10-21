import csv

import pytest

from ingest.load_companies import EXPECTED_HEADER, LibraryError, load_companies
from jmsa.config import COMPANIES_CSV
from jmsa.display import NOT_AVAILABLE, show

GLASSDOOR_COLUMNS = [
    "glassdoor_rating",
    "glassdoor_review_count",
    "glassdoor_employer_size",
    "glassdoor_industry",
]

GOOD_ROW = {
    "company_id": "acme",
    "name": "Acme",
    "sector": "IT Services",
    "hq_country": "India",
    "india_cities": "Pune;Chennai",
    "size_band": "10k-50k",
    "careers_url": "",
    "publishes_attrition": "no",
}


def csv_row_count():
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def company_count(db):
    return db.execute("SELECT count(*) FROM companies").fetchone()[0]


def all_rows(db):
    return [tuple(r) for r in db.execute("SELECT * FROM companies ORDER BY company_id")]


def write_csv(tmp_path, rows, header=EXPECTED_HEADER):
    path = tmp_path / "companies.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_schema_matches_csv_header(db):
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    schema = [r["name"] for r in db.execute("PRAGMA table_info(companies)")]
    assert header == EXPECTED_HEADER
    assert schema == header + GLASSDOOR_COLUMNS


def test_loads_every_csv_row(db):
    assert load_companies(db) == csv_row_count()
    assert company_count(db) == csv_row_count()


def test_reload_is_idempotent(db):
    load_companies(db)
    first = all_rows(db)
    load_companies(db)
    assert all_rows(db) == first


def test_reload_keeps_glassdoor_columns(db):
    load_companies(db)
    db.execute("UPDATE companies SET glassdoor_rating = 3.8 WHERE company_id = 'infosys'")
    load_companies(db)
    rating = db.execute("SELECT glassdoor_rating FROM companies WHERE company_id = 'infosys'")
    assert rating.fetchone()[0] == 3.8


def test_empty_optional_stored_as_null(db):
    load_companies(db)
    filled = db.execute("SELECT count(*) FROM companies WHERE careers_url IS NOT NULL")
    assert filled.fetchone()[0] == 0


@pytest.mark.parametrize(
    "rows, message",
    [
        ([GOOD_ROW, GOOD_ROW], "duplicate company_id 'acme'"),
        ([{**GOOD_ROW, "company_id": "Acme Ltd"}], "not a lowercase slug"),
        ([{**GOOD_ROW, "sector": "Space Mining"}], "not in the PRD's fixed list"),
        ([{**GOOD_ROW, "hq_country": ""}], "hq_country is empty"),
        ([{**GOOD_ROW, "publishes_attrition": "maybe"}], "must be yes, no or empty"),
    ],
    ids=["duplicate-id", "non-slug-id", "unknown-sector", "missing-required", "bad-attrition"],
)
def test_bad_row_fails_and_writes_nothing(db, tmp_path, rows, message):
    path = write_csv(tmp_path, rows)
    with pytest.raises(LibraryError, match=message):
        load_companies(db, path)
    assert company_count(db) == 0


def test_wrong_header_fails_and_writes_nothing(db, tmp_path):
    header = EXPECTED_HEADER[:-1]  # publishes_attrition missing
    row = {k: v for k, v in GOOD_ROW.items() if k in header}
    path = write_csv(tmp_path, [row], header=header)
    with pytest.raises(LibraryError, match="header"):
        load_companies(db, path)
    assert company_count(db) == 0


def test_every_problem_is_reported_at_once(db, tmp_path):
    path = write_csv(tmp_path, [{**GOOD_ROW, "company_id": "Bad Id", "sector": "Nope"}])
    with pytest.raises(LibraryError) as error:
        load_companies(db, path)
    assert len(error.value.problems) == 2


def test_company_missing_from_csv_is_not_deleted(db, tmp_path):
    load_companies(db, write_csv(tmp_path, [GOOD_ROW]))
    other = {**GOOD_ROW, "company_id": "other", "name": "Other"}
    with pytest.raises(LibraryError, match="not in the CSV: acme"):
        load_companies(db, write_csv(tmp_path, [other]))
    assert [r[0] for r in db.execute("SELECT company_id FROM companies")] == ["acme"]


@pytest.mark.parametrize("missing", [None, float("nan"), "", "   "])
def test_show_missing_is_not_available(missing):
    assert show(missing) == NOT_AVAILABLE


@pytest.mark.parametrize("value", [3.8, 0, "Pune"])
def test_show_passes_real_values_through(value):
    assert show(value) == value
