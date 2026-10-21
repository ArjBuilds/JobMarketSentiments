import csv
import json
from pathlib import Path

import pytest

from ingest.load_companies import EXPECTED_HEADER, load_companies
from ingest.load_glassdoor_ratings import (
    RATINGS_CSV,
    RatingsError,
    build_report,
    load_ratings,
)
from ingest.load_glassdoor_reviews import load_aliases as load_review_aliases

FIXTURES = Path(__file__).parent / "fixtures"

RATINGS_HEADER = [
    "company_name", "overall_rating", "employer_size", "industry",
    "review_count", "salary_count", "job_count", "location_raw",
]

COMPANIES = [
    {"company_id": "acme", "name": "Acme", "size_band": "200k+"},
    {"company_id": "globex", "name": "Globex", "size_band": "10k-50k"},
    {"company_id": "initech", "name": "Initech", "size_band": "10k-50k"},
]


def write_companies(tmp_path, companies=COMPANIES):
    path = tmp_path / "companies.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPECTED_HEADER)
        writer.writeheader()
        for company in companies:
            writer.writerow({
                "sector": "IT Services", "hq_country": "India", "india_cities": "Pune",
                "careers_url": "", "publishes_attrition": "no", **company,
            })
    return path


def write_ratings(tmp_path, rows):
    """rows: (company_name, rating, employer_size, industry, review_count)."""
    path = tmp_path / "ratings.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(RATINGS_HEADER)
        for name, rating, size, industry, count in rows:
            writer.writerow([name, rating, size, industry, count, "", "", ""])
    return path


def write_aliases(tmp_path, rows=()):
    """rows: (company_id, alias_in_dataset, source)."""
    path = tmp_path / "aliases.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company_id", "alias_in_dataset", "source"])
        writer.writerows(rows)
    return path


def glassdoor(db, company_id):
    return tuple(db.execute(
        "SELECT glassdoor_rating, glassdoor_review_count, glassdoor_employer_size, glassdoor_industry"
        " FROM companies WHERE company_id = ?", (company_id,)
    ).fetchone())


@pytest.fixture
def loaded(db, tmp_path):
    load_companies(db, write_companies(tmp_path))
    return db


def run(db, tmp_path, ratings, aliases=(), rejected=None):
    return load_ratings(
        db, write_ratings(tmp_path, ratings), write_aliases(tmp_path, aliases), rejected or {}
    )


def test_review_aliases_unchanged():
    # Captured from the reviews loader before company_aliases.csv gained its
    # source column; the refactor must not change a single mapping.
    expected = json.loads((FIXTURES / "review_aliases.json").read_text(encoding="utf-8"))
    actual = {alias: [company_id, flag] for alias, (company_id, flag) in load_review_aliases().items()}
    assert actual == expected


def test_exact_name_match_fills_columns(loaded, tmp_path):
    run(loaded, tmp_path, [("ACME", "4.1", "10000+ Employees", "Software Development", "9000")])
    assert glassdoor(loaded, "acme") == (4.1, 9000, "10000+ Employees", "Software Development")


def test_highest_review_count_wins(loaded, tmp_path):
    run(loaded, tmp_path, [
        ("Acme", "3.2", "51 to 200 Employees", "", "150"),
        ("Acme", "4.0", "10000+ Employees", "Retail", "12000"),
    ])
    assert glassdoor(loaded, "acme")[:2] == (4.0, 12000)


def test_alias_replaces_own_name(loaded, tmp_path):
    run(
        loaded, tmp_path,
        [("Globex", "2.0", "", "", "50"), ("Globex Corporation", "3.9", "", "", "8000")],
        aliases=[("globex", "Globex Corporation", "glassdoor_ratings")],
    )
    assert glassdoor(loaded, "globex")[:2] == (3.9, 8000)


def test_alias_from_another_source_is_ignored(loaded, tmp_path):
    run(
        loaded, tmp_path,
        [("Globex Corporation", "3.9", "", "", "8000")],
        aliases=[("globex", "Globex Corporation", "glassdoor_reviews")],
    )
    assert glassdoor(loaded, "globex") == (None, None, None, None)


def test_unmatched_company_stays_empty(loaded, tmp_path):
    run(loaded, tmp_path, [("Acme", "4.1", "", "", "9000")])
    assert glassdoor(loaded, "initech") == (None, None, None, None)


def test_numbers_stored_as_real_and_integer(loaded, tmp_path):
    # typeof() reports how SQLite actually stored each value; text here would
    # make filters and sorting compare "10,500" < "9,000" as strings.
    run(loaded, tmp_path, [("Acme", "4.1", "", "", "9000")])
    types = dict(
        (r[0], (r[1], r[2])) for r in loaded.execute(
            "SELECT company_id, typeof(glassdoor_rating), typeof(glassdoor_review_count) FROM companies"
        )
    )
    assert types["acme"] == ("real", "integer")
    assert types["initech"] == ("null", "null")


def test_unknown_size_and_empty_industry_stored_as_null(loaded, tmp_path):
    run(loaded, tmp_path, [("Acme", "4.1", "Unknown", "", "9000")])
    assert glassdoor(loaded, "acme")[2:] == (None, None)


def test_rejected_company_stays_empty(loaded, tmp_path):
    results = run(loaded, tmp_path, [("Acme", "4.1", "", "", "900")], rejected={"acme": "regional page"})
    assert glassdoor(loaded, "acme") == (None, None, None, None)
    assert "acme" in build_report(results, {"acme": "regional page"})


def test_rerun_is_idempotent(loaded, tmp_path):
    ratings = [("Acme", "4.1", "", "", "9000"), ("Globex", "3.5", "", "", "700")]
    run(loaded, tmp_path, ratings)
    first = [tuple(r) for r in loaded.execute("SELECT * FROM companies ORDER BY company_id")]
    run(loaded, tmp_path, ratings)
    assert [tuple(r) for r in loaded.execute("SELECT * FROM companies ORDER BY company_id")] == first


def test_company_that_stops_matching_is_cleared(loaded, tmp_path):
    run(loaded, tmp_path, [("Acme", "4.1", "", "", "9000")])
    run(loaded, tmp_path, [("Someone Else", "4.1", "", "", "9000")])
    assert glassdoor(loaded, "acme") == (None, None, None, None)


@pytest.mark.parametrize(
    "aliases, rejected, message",
    [
        ([("acme", "Acme Typo", "glassdoor_ratings")], {}, "not a company_name in the ratings file"),
        ([("nobody", "Acme", "glassdoor_ratings")], {}, "not in companies"),
        ([("acme", "Acme", "glassdoor_ratings")], {"acme": "x"}, "in REJECTED but also has the alias"),
    ],
    ids=["alias-typo", "unknown-company", "rejected-and-aliased"],
)
def test_bad_alias_fails_and_writes_nothing(loaded, tmp_path, aliases, rejected, message):
    with pytest.raises(RatingsError, match=message):
        run(loaded, tmp_path, [("Acme", "4.1", "", "", "9000")], aliases, rejected)
    assert glassdoor(loaded, "acme") == (None, None, None, None)


def test_empty_companies_table_fails(db, tmp_path):
    with pytest.raises(RatingsError, match="companies table is empty"):
        run(db, tmp_path, [("Acme", "4.1", "", "", "9000")])


def test_report_flags_large_company_with_few_reviews(loaded, tmp_path):
    results = run(loaded, tmp_path, [("Acme", "4.1", "", "", "4999"), ("Globex", "4.1", "", "", "100")])
    flagged = build_report(results).split("check: possibly a regional page")[1]
    assert "acme" in flagged            # 200k+ band, under 5,000 reviews
    assert "globex" not in flagged      # few reviews, but a 10k-50k company


@pytest.mark.skipif(not RATINGS_CSV.exists(), reason="data/raw/glassdoor_company_ratings.csv not on disk")
def test_real_snapshot_matches_66_companies(db):
    load_companies(db)
    results = load_ratings(db)
    matched = [r for r in results if r["row"] is not None]
    assert len(matched) == 66
    assert sum(1 for r in matched if r["how"] == "alias") == 6
    # Renamed "LTM (formerly LTIMindtree)", it keeps its row through an alias.
    assert next(r for r in matched if r["company_id"] == "ltimindtree")["how"] == "alias"
    assert glassdoor(db, "ltimindtree")[1] == 3400
    for company_id in ("wipro", "ey", "tata-motors", "mercedes-benz", "infosys", "tata-consultancy-services"):
        assert glassdoor(db, company_id) == (None, None, None, None)
    assert glassdoor(db, "boeing")[1] == 16100
