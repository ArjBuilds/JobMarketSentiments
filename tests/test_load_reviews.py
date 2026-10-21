import sqlite3

import pytest

from ingest.load_reviews import ReviewsError, load_reviews


def everything(db):
    return [tuple(r) for r in db.execute("SELECT * FROM reviews ORDER BY review_id")]


def ids(db):
    return [r[0] for r in db.execute("SELECT review_id FROM reviews ORDER BY review_id")]


FIVE = [
    {"company_id": "acme", "headline": "One"},
    {"company_id": "globex", "headline": "Two"},
    {"company_id": "acme", "headline": "Three"},
    {"company_id": "globex", "headline": "Four"},
    {"company_id": "acme", "headline": "Five"},
]


def test_review_id_is_the_zero_padded_record_number(library, write_reviews):
    load_reviews(library, write_reviews(FIVE[:2]))
    assert ids(library) == ["gd-0000001", "gd-0000002"]


def test_sub_ratings_and_codes(library, write_reviews):
    stats = load_reviews(library, write_reviews([{
        "company_id": "acme", "recommend": "v", "ceo_approval": "r", "business_outlook": "o",
        "career_opportunities": "5.0", "senior_management": "3",
        "compensation_and_benefits": "10u0eun", "work_life_balance": "",
    }]))
    row = library.execute("SELECT * FROM reviews").fetchone()
    assert (row["recommend"], row["ceo_approval"], row["business_outlook"]) == ("v", "r", "o")
    assert (row["career_opportunities"], row["senior_management"]) == (5, 3)
    # A scraped code is not a star rating, and an empty cell is no answer.
    assert row["compensation_and_benefits"] is None
    assert row["work_life_balance"] is None
    assert stats["discarded"] == {"compensation_and_benefits": 1}


def test_empty_text_and_location_stored_as_null(library, write_reviews):
    load_reviews(library, write_reviews([{"company_id": "acme", "pros": "Good pay"}]))
    row = library.execute("SELECT * FROM reviews").fetchone()
    assert row["pros"] == "Good pay"
    assert (row["headline"], row["cons"], row["location"]) == (None, None, None)


def test_undated_review_is_kept_with_null_date(library, write_reviews):
    stats = load_reviews(library, write_reviews([{"company_id": "acme", "review_date": ""}]))
    assert library.execute("SELECT review_date FROM reviews").fetchone()[0] is None
    assert stats["undated"] == 1


def test_pre_merger_flag_is_stored(library, write_reviews):
    load_reviews(library, write_reviews([{"company_id": "acme", "is_pre_merger": "1"}]))
    assert library.execute("SELECT is_pre_merger FROM reviews").fetchone()[0] == 1


def test_rerun_is_idempotent(library, write_reviews):
    path = write_reviews(FIVE)
    load_reviews(library, path)
    first = everything(library)
    load_reviews(library, path)
    assert everything(library) == first


def test_company_option_replaces_only_that_company(library, write_reviews):
    load_reviews(library, write_reviews(FIVE))
    globex_before = [r for r in everything(library) if r[1] == "globex"]
    load_reviews(library, write_reviews([{"company_id": "acme", "headline": "New"}], "new.csv"), company="acme")
    assert [r[0] for r in library.execute("SELECT headline FROM reviews WHERE company_id = 'acme'")] == ["New"]
    assert [r for r in everything(library) if r[1] == "globex"] == globex_before


def test_limit_then_resume_loads_the_rest_without_duplicates(library, write_reviews):
    path = write_reviews(FIVE)
    load_reviews(library, path, limit=3, batch_rows=2)
    assert len(ids(library)) == 3
    stats = load_reviews(library, path, resume=True, batch_rows=2)
    assert stats["resumed_after"] == "gd-0000003"
    assert ids(library) == [f"gd-000000{n}" for n in range(1, 6)]


def test_crash_keeps_committed_batches_and_resume_finishes(library, write_reviews):
    # Record 4 names an unknown company. Records 1-2 are already committed as
    # batch one; batch two fails and is rolled back.
    broken = FIVE[:3] + [{"company_id": "nobody"}] + FIVE[4:]
    with pytest.raises(ReviewsError, match="record 4"):
        load_reviews(library, write_reviews(broken, "broken.csv"), batch_rows=2)
    assert ids(library) == ["gd-0000001", "gd-0000002"]

    load_reviews(library, write_reviews(FIVE), resume=True, batch_rows=2)
    assert len(ids(library)) == 5


def test_unknown_company_in_first_batch_leaves_old_rows(library, write_reviews):
    load_reviews(library, write_reviews(FIVE))
    before = everything(library)
    with pytest.raises(ReviewsError, match="'nobody' is not in the companies table"):
        load_reviews(library, write_reviews([{"company_id": "nobody"}], "bad.csv"))
    assert everything(library) == before


def test_wrong_header_fails(library, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("company_id,headline\nacme,Hi\n", encoding="utf-8")
    with pytest.raises(ReviewsError, match="header"):
        load_reviews(library, path)


def test_empty_companies_table_fails(db, write_reviews):
    with pytest.raises(ReviewsError, match="companies table is empty"):
        load_reviews(db, write_reviews(FIVE))


def test_unknown_company_option_fails(library, write_reviews):
    with pytest.raises(ReviewsError, match="--company 'nobody'"):
        load_reviews(library, write_reviews(FIVE), company="nobody")


def test_database_from_before_milestone_4_gets_rebuild_message(write_reviews):
    # The reviews table as milestone 1 created it: no is_pre_merger column.
    old = sqlite3.connect(":memory:")
    old.execute("CREATE TABLE companies (company_id TEXT PRIMARY KEY, name TEXT, sector TEXT)")
    old.execute("CREATE TABLE reviews (review_id TEXT PRIMARY KEY, company_id TEXT, review_date TEXT,"
                " rating REAL, headline TEXT, pros TEXT, cons TEXT, job_title TEXT)")
    with pytest.raises(ReviewsError, match="predates milestone 4"):
        load_reviews(old, write_reviews(FIVE))
    old.close()


def test_load_drops_stale_summary_rows(library, write_reviews):
    load_reviews(library, write_reviews(FIVE))
    library.execute("INSERT INTO review_summary (company_id, period, review_count, pre_merger_count)"
                    " VALUES ('acme', 'all', 3, 0)")
    library.commit()
    load_reviews(library, write_reviews(FIVE))
    assert library.execute("SELECT count(*) FROM review_summary").fetchone()[0] == 0
