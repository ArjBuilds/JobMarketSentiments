import sqlite3

import pytest

from jmsa.db import apply_schema
from jmsa.display import NOT_AVAILABLE
from jmsa.skills import (
    EXPORTS,
    HEADLINE_SCOPE,
    MIN_SCORED_POSTINGS,
    SCOPE_LABELS,
    read_export_comparison,
    read_market_skills,
)


def add_counts(db, scope, scored, skills):
    """skills: (skill, type, postings); share is worked out from scored."""
    db.executemany(
        "INSERT INTO skill_counts (scope, skill, type, postings, share, scope_postings) VALUES (?, ?, ?, ?, ?, ?)",
        [(scope, skill, kind, n, n / scored, scored) for skill, kind, n in skills],
    )


def test_the_chart_is_hidden_below_twenty_lists(db):
    add_counts(db, HEADLINE_SCOPE, MIN_SCORED_POSTINGS - 1, [("SQL", "tool", 5)])
    assert read_market_skills(db) == {"available": False, "scored": 19, "rows": []}


def test_the_chart_shows_at_twenty_lists(db):
    add_counts(db, HEADLINE_SCOPE, MIN_SCORED_POSTINGS, [("SQL", "tool", 5)])
    skills = read_market_skills(db)
    assert skills["available"] and skills["rows"] == [{"Skill": "SQL", "Postings": 5, "Share": 0.25}]


def test_nothing_counted_is_not_available(db):
    assert read_market_skills(db) == {"available": False, "scored": 0, "rows": []}


def test_the_toggle_picks_tools_methods_or_all_on_one_base(db):
    add_counts(db, HEADLINE_SCOPE, 100, [("SQL", "tool", 30), ("Machine Learning", "method", 20),
                                         ("Python", "tool", 10)])
    tools = read_market_skills(db, "Tools")["rows"]
    methods = read_market_skills(db, "Methods")["rows"]
    every = read_market_skills(db, "All")["rows"]
    assert [r["Skill"] for r in tools] == ["SQL", "Python"]
    assert [r["Skill"] for r in methods] == ["Machine Learning"]
    assert [r["Skill"] for r in every] == ["SQL", "Machine Learning", "Python"]
    # Shares don't change with the view: every one is of all lists scored.
    assert methods[0]["Share"] == every[1]["Share"] == 0.2


def test_tools_is_the_default_view(db):
    add_counts(db, HEADLINE_SCOPE, 100, [("SQL", "tool", 30), ("Machine Learning", "method", 40)])
    assert [r["Skill"] for r in read_market_skills(db)["rows"]] == ["SQL"]


def test_an_unknown_view_is_an_error(db):
    with pytest.raises(ValueError):
        read_market_skills(db, "Languages")


def test_the_top_ten_are_sorted_and_capped(db):
    add_counts(db, HEADLINE_SCOPE, 100, [(f"Tool {i:02}", "tool", i) for i in range(1, 13)])
    rows = read_market_skills(db, "Tools")["rows"]
    assert [r["Postings"] for r in rows] == list(range(12, 2, -1))


def test_the_comparison_shows_each_scope_and_gaps(db):
    add_counts(db, HEADLINE_SCOPE, 100, [("SQL", "tool", 30)])
    add_counts(db, EXPORTS[0], 50, [("SQL", "tool", 20)])
    add_counts(db, EXPORTS[2], 60, [("Python", "tool", 6)])      # scored, but no SQL
    add_counts(db, EXPORTS[1], 10, [("SQL", "tool", 2)])          # too few lists
    [row] = read_export_comparison(db, "Tools")
    assert row == {
        "Skill": "SQL",
        SCOPE_LABELS[HEADLINE_SCOPE]: "30.0%",
        SCOPE_LABELS[EXPORTS[0]]: "40.0%",
        SCOPE_LABELS[EXPORTS[2]]: "0.0%",
        SCOPE_LABELS[EXPORTS[1]]: NOT_AVAILABLE,
    }


def test_apply_schema_adds_skill_counts_to_an_existing_database(tmp_path):
    # An existing database without the new table, as data/jmsa.db was.
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.execute("CREATE TABLE companies (company_id TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL)")
    conn.execute("INSERT INTO companies VALUES ('acme', 'Acme', 'IT Services')")
    conn.commit()
    apply_schema(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "skill_counts" in tables
    assert conn.execute("SELECT count(*) FROM companies").fetchone()[0] == 1   # nothing rebuilt
    conn.close()
