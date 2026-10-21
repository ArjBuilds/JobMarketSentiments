import pytest

from jmsa.display import NOT_AVAILABLE
from jmsa.library import (
    Filters,
    apply,
    column_headers,
    display_row,
    load_library,
    minimum_steps,
)

# company_id, sector, hq_country, rating, {period: (review_count, avg_compound)}
COMPANIES = [
    ("acme", "IT Services", "India", 4.0, {"all": (500, 0.30), "2020-2023": (200, 0.20)}),
    ("globex", "Banking", "United States", 3.5, {"all": (50, 0.10), "2020-2023": (30, 0.40)}),
    ("hooli", "Software", "United States", 4.5, {}),                       # no reviews
    ("initech", "IT Services", "United States", None, {"all": (2000, 0.25), "2020-2023": (1500, 0.25)}),
    ("tiny", "Software", "India", 3.8, {"all": (12, 0.60), "2020-2023": (12, 0.60)}),  # under 20
]


def add_company(db, company_id, sector, country, rating, periods, pre_merger=0):
    db.execute(
        "INSERT INTO companies (company_id, name, sector, hq_country, glassdoor_rating,"
        " glassdoor_review_count) VALUES (?, ?, ?, ?, ?, ?)",
        (company_id, company_id.title(), sector, country, rating, 1000 if rating else None),
    )
    for period, (count, compound) in periods.items():
        db.execute(
            "INSERT INTO review_summary (company_id, period, review_count, avg_compound,"
            " pre_merger_count) VALUES (?, ?, ?, ?, ?)",
            (company_id, period, count, compound, pre_merger),
        )


@pytest.fixture
def records(db):
    for company in COMPANIES:
        add_company(db, *company)
    db.commit()
    return load_library(db)


def ids(records, filters=Filters(), sort_key="name", descending=False):
    return [r["company_id"] for r in apply(records, filters, sort_key, descending)]


# --- loading ---------------------------------------------------------------

def test_load_gives_one_record_per_company_in_name_order(records):
    assert [r["company_id"] for r in records] == ["acme", "globex", "hooli", "initech", "tiny"]


def test_under_20_reviews_loads_as_missing_sentiment_but_keeps_the_count(records):
    tiny = next(r for r in records if r["company_id"] == "tiny")
    assert tiny["sentiment"] == {"all": None, "2020-2023": None}
    assert tiny["reviews"] == {"all": 12, "2020-2023": 12}


# --- filters, one at a time ------------------------------------------------

def test_no_filters_keeps_every_company(records):
    assert ids(records) == ["acme", "globex", "hooli", "initech", "tiny"]


def test_sector_filter(records):
    assert ids(records, Filters(sectors=("IT Services",))) == ["acme", "initech"]


def test_country_filter(records):
    assert ids(records, Filters(countries=("India",))) == ["acme", "tiny"]


def test_min_rating_is_inclusive_and_drops_missing(records):
    # tiny is rated exactly 3.8; initech has no rating.
    assert ids(records, Filters(min_rating=3.8)) == ["acme", "hooli", "tiny"]


def test_min_rating_with_missing_included(records):
    assert ids(records, Filters(min_rating=3.8, include_missing=True)) == [
        "acme", "hooli", "initech", "tiny"]


def test_min_sentiment_drops_missing_and_hidden(records):
    # hooli has no reviews and tiny's 12 are hidden: both count as missing.
    assert ids(records, Filters(min_sentiment=0.2)) == ["acme", "initech"]


def test_min_sentiment_with_missing_included(records):
    assert ids(records, Filters(min_sentiment=0.2, include_missing=True)) == [
        "acme", "hooli", "initech", "tiny"]


def test_min_reviews_at_the_20_rule_filters_nothing(records):
    assert ids(records, Filters(min_reviews=20)) == ["acme", "globex", "hooli", "initech", "tiny"]


def test_min_reviews_above_20(records):
    # globex (50) and tiny (12) have counts below 100; hooli has none.
    assert ids(records, Filters(min_reviews=100)) == ["acme", "initech"]


def test_min_reviews_with_missing_included_keeps_only_the_missing(records):
    # Including missing values brings back hooli, which has no count, but not
    # tiny, whose count of 12 is a value below the minimum.
    assert ids(records, Filters(min_reviews=100, include_missing=True)) == ["acme", "hooli", "initech"]


def test_min_reviews_uses_the_selected_period(records):
    # acme has 500 all-time but only 200 in 2020-2023.
    assert ids(records, Filters(min_reviews=500)) == ["acme", "initech"]
    assert ids(records, Filters(period="2020-2023", min_reviews=500)) == ["initech"]


def test_min_sentiment_uses_the_selected_period(records):
    assert ids(records, Filters(min_sentiment=0.35)) == []
    assert ids(records, Filters(period="2020-2023", min_sentiment=0.35)) == ["globex"]


# --- combinations and the empty result -------------------------------------

def test_combined_filters(records):
    filters = Filters(sectors=("IT Services",), min_rating=3.9, min_sentiment=0.2)
    assert ids(records, filters) == ["acme"]


def test_combined_filters_with_missing_included(records):
    # initech has no rating but its sentiment (0.25) still has to pass.
    filters = Filters(sectors=("IT Services",), min_rating=3.9, min_sentiment=0.2, include_missing=True)
    assert ids(records, filters) == ["acme", "initech"]


def test_including_missing_never_lets_a_low_value_through(records):
    filters = Filters(min_rating=4.0, min_sentiment=0.2, include_missing=True)
    # globex (3.5, 0.10) and tiny (3.8) have values below the minimums.
    assert ids(records, filters) == ["acme", "hooli", "initech"]


def test_nothing_matches(records):
    assert apply(records, Filters(sectors=("Banking",), countries=("India",))) == []


# --- sorting: missing values last in both directions -----------------------

@pytest.mark.parametrize("sort_key, descending, expected", [
    ("name", False, ["acme", "globex", "hooli", "initech", "tiny"]),
    ("name", True, ["tiny", "initech", "hooli", "globex", "acme"]),
    ("rating", False, ["globex", "tiny", "acme", "hooli", "initech"]),
    ("rating", True, ["hooli", "acme", "tiny", "globex", "initech"]),
    # hooli (no reviews) and tiny (hidden) are missing; last either way, in name order.
    ("sentiment", False, ["globex", "initech", "acme", "hooli", "tiny"]),
    ("sentiment", True, ["acme", "initech", "globex", "hooli", "tiny"]),
    ("reviews", False, ["tiny", "globex", "acme", "initech", "hooli"]),
    ("reviews", True, ["initech", "acme", "globex", "tiny", "hooli"]),
])
def test_sort(records, sort_key, descending, expected):
    assert ids(records, sort_key=sort_key, descending=descending) == expected


def test_sort_uses_the_selected_period(records):
    # In 2020-2023 globex leads (0.40) rather than trailing.
    assert ids(records, Filters(period="2020-2023"), "sentiment", True)[:3] == ["globex", "initech", "acme"]


# --- display ---------------------------------------------------------------

def rows_by_id(records, period="all"):
    return {r["company_id"]: display_row(r, period) for r in records}


def test_display_shows_not_available_never_none(records):
    rows = rows_by_id(records)
    for row in rows.values():
        assert all(isinstance(value, str) and value for value in row.values())
    headers = column_headers("all")
    assert rows["hooli"][headers["sentiment"]] == NOT_AVAILABLE
    assert rows["hooli"][headers["reviews"]] == NOT_AVAILABLE
    assert rows["initech"][headers["rating"]] == NOT_AVAILABLE


def test_display_formats_numbers(records):
    headers = column_headers("all")
    acme = rows_by_id(records)["acme"]
    assert acme[headers["rating"]] == "4.0"
    assert acme[headers["sentiment"]] == "+0.30 (positive)"
    assert acme[headers["reviews"]] == "500"


def test_display_hides_a_score_under_20_but_shows_its_count(records):
    headers = column_headers("all")
    tiny = rows_by_id(records)["tiny"]
    assert tiny[headers["sentiment"]] == "hidden: fewer than 20 reviews (12)"
    assert tiny[headers["reviews"]] == "12"


def test_review_headers_name_the_period():
    assert column_headers("all")["sentiment"] == "Review sentiment (all time)"
    assert column_headers("2020-2023")["reviews"] == "Reviews scored (2020–2023)"


def test_pre_merger_reviews_are_marked(db):
    add_company(db, "mindco", "IT Services", "India", 3.5, {"all": (100, 0.26)}, pre_merger=100)
    db.commit()
    [record] = load_library(db)
    assert display_row(record, "all")[column_headers("all")["sentiment"]] == (
        "+0.26 (positive) · pre-merger Mindtree reviews")


# --- slider stops ----------------------------------------------------------

def test_minimum_steps_cover_the_data_with_exact_values():
    assert minimum_steps([3.5, None, 4.6], 0.1) == [3.5, 3.6, 3.7, 3.8, 3.9, 4.0, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6]
    assert minimum_steps([0.14, 0.53], 0.05) == [0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55]
    assert minimum_steps([None], 0.1) == []
