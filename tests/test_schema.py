import sqlite3

import pytest

from jmsa.db import TABLES, apply_schema

# job_skills reaches companies through jobs, so it carries job_id instead.
# skill_counts is market-wide: the source doesn't tie skills to a company.
COMPANY_KEYED = tuple(t for t in TABLES if t not in ("job_skills", "skill_counts"))


def table_names(db):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row["name"] for row in rows}


def columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def test_six_tables_created(db):
    assert table_names(db) >= set(TABLES)


def test_every_company_table_is_keyed_on_company_id(db):
    for table in COMPANY_KEYED:
        assert "company_id" in columns(db, table), table


def test_job_skills_links_through_jobs(db):
    assert columns(db, "job_skills") == {"job_id", "skill"}


def test_apply_schema_is_idempotent(db):
    apply_schema(db)  # the fixture already applied it once
    assert table_names(db) >= set(TABLES)


def test_foreign_keys_are_enforced(db):
    # Guards the PRAGMA in get_conn: without it this insert would succeed and
    # silently orphan the row from its company.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO reviews (review_id, company_id) VALUES ('r1', 'no-such-company')"
        )


def test_sentiment_label_rejects_values_outside_the_vader_three(db):
    db.execute("INSERT INTO companies (company_id, name, sector) VALUES ('x', 'X', 'IT Services')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO reviews (review_id, company_id, sentiment_label)"
            " VALUES ('r1', 'x', 'very positive')"
        )
