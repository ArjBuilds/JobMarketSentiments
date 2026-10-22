"""Every page runs, twice, against a small database, with no exception.

Streamlit's own AppTest runs each page headlessly, through the router
(app/app.py) as a real visit does: links between pages only resolve there,
and the router sets up the shared state and checks the database. The second
run matters: Streamlit reruns a page on another thread, which is how the old
home page's cached sqlite connection once crashed ("SQLite objects created
in a thread can only be used in that same thread").
"""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import jmsa.config
import jmsa.db
from app.ui.components import PAGES
from jmsa.db import get_conn, init_db

ROOT = Path(__file__).resolve().parents[1]


def open_page(page: str) -> AppTest:
    """The app opened at one page (a PAGES value), through the router."""
    app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=30)
    app.run()
    return app.switch_page(page)


@pytest.fixture
def small_db(tmp_path, monkeypatch):
    """A temporary database with two companies, pointed at by every page.

    The pages read DB_PATH from jmsa.config and get_conn reads its own copy
    in jmsa.db, so both are patched. Cached results are cleared, so no page
    sees another test's database.
    """
    path = tmp_path / "pages.db"
    init_db(path)
    conn = get_conn(path)
    conn.executemany(
        "INSERT INTO companies (company_id, name, sector, hq_country, glassdoor_rating,"
        " glassdoor_review_count) VALUES (?, ?, 'IT Services', 'India', ?, ?)",
        [("acme", "Acme", 4.1, 2500), ("hooli", "Hooli", None, None)],
    )
    conn.execute(
        "INSERT INTO review_summary (company_id, period, review_count, first_date, last_date,"
        " avg_compound, share_positive, share_neutral, share_negative, pre_merger_count)"
        " VALUES ('acme', 'all', 500, '2010-01-01', '2023-07-06', 0.2, 0.6, 0.2, 0.2, 0)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(jmsa.config, "DB_PATH", path)
    monkeypatch.setattr(jmsa.db, "DB_PATH", path)
    st.cache_data.clear()
    yield path
    st.cache_data.clear()


@pytest.mark.parametrize("page", PAGES.values())
def test_page_runs_twice_without_an_exception(small_db, page):
    app = open_page(page)
    for _ in range(2):
        app.run()
        assert not app.exception, app.exception
        # A syntax error isn't an exception to AppTest: the page just draws
        # nothing. Every page starts with its title, so a missing one fails.
        assert app.title, f"{page} drew nothing: does it compile?"


def test_router_shows_one_error_without_a_database(tmp_path, monkeypatch):
    """No database: the router says how to build one instead of failing,
    and doesn't create the file while checking."""
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(jmsa.config, "DB_PATH", missing)
    monkeypatch.setattr(jmsa.db, "DB_PATH", missing)
    st.cache_data.clear()
    app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    assert "There is no database" in app.error[0].value
    assert "python -m jmsa.db init" in app.error[0].value
    assert not missing.exists()


def test_router_shows_one_error_with_no_companies(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    init_db(path)
    monkeypatch.setattr(jmsa.config, "DB_PATH", path)
    monkeypatch.setattr(jmsa.db, "DB_PATH", path)
    st.cache_data.clear()
    app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=30)
    app.run()
    assert not app.exception, app.exception
    assert "has no companies loaded" in app.error[0].value
    st.cache_data.clear()


def test_about_opens_without_a_database(tmp_path, monkeypatch):
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(jmsa.config, "DB_PATH", missing)
    monkeypatch.setattr(jmsa.db, "DB_PATH", missing)
    st.cache_data.clear()
    app = open_page(PAGES["about"]).run()
    assert not app.exception, app.exception
    assert not app.error   # the router lets About through
    assert "No database" in app.warning[0].value
    assert app.expander[0].label == "How scores work"
    assert not missing.exists()


def test_compare_asks_for_two_companies_then_shows_the_table(small_db):
    app = open_page(PAGES["compare"]).run()
    assert "Pick 2 to 4 companies" in app.info[0].value
    app.multiselect[0].select("acme").select("hooli").run()
    assert not app.exception, app.exception
    assert len(app.dataframe) >= 1
