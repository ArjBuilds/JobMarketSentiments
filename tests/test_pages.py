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


def test_compare_shows_the_list_built_elsewhere_or_points_to_explore(small_db):
    app = open_page(PAGES["compare"]).run()
    assert app.info[0].value == "Your compare list is empty."
    assert any(link.label == "Go to Explore" for link in app.get("page_link"))
    app.session_state["compare_ids"] = ["acme"]
    app.run()
    assert app.info[0].value == "Add one more company to compare with Acme."
    app.session_state["compare_ids"] = ["acme", "hooli"]
    app.run()
    assert not app.exception, app.exception
    assert list(app.dataframe[0].value.columns) == ["Metric", "Acme", "Hooli"]
    assert app.multiselect(key="compare_pick").value == ["acme", "hooli"]


def test_compare_removes_a_company_and_opens_one_by_name(small_db):
    app = open_page(PAGES["compare"]).run()
    app.session_state["compare_ids"] = ["acme", "hooli"]
    app.run()
    app.button(key="remove_hooli").click().run()
    assert app.session_state.compare_ids == ["acme"]
    app.session_state["compare_ids"] = ["acme", "hooli"]
    app.run()
    app.button(key="open_hooli").click().run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Hooli"


def test_a_full_compare_list_says_so_instead_of_adding(small_db):
    app = open_page(PAGES["company"]).run()
    app.session_state["compare_ids"] = ["hooli", "x1", "x2", "x3"]
    app.run()
    next(b for b in app.button if b.label == "Add to compare").click().run()
    assert app.session_state.compare_ids == ["hooli", "x1", "x2", "x3"]
    assert "compare list is full" in app.warning[0].value


# --- Explore: filters and the compare list survive leaving the page ----------

def test_explore_filters_survive_a_trip_to_another_page(small_db):
    app = open_page(PAGES["explore"]).run()
    app.toggle(key="filter_descending").set_value(True).run()
    app.multiselect(key="filter_sectors").select("IT Services").run()
    app.switch_page(PAGES["compare"]).run()
    app.switch_page(PAGES["explore"]).run()
    assert not app.exception, app.exception
    assert app.multiselect(key="filter_sectors").value == ["IT Services"]
    assert app.toggle(key="filter_descending").value is True
    assert app.session_state.filters["sectors"] == ("IT Services",)


def test_a_filter_set_from_another_page_reaches_the_explore_widget(small_db):
    """What the Company page's sector link does (app.state.set_filter)."""
    app = open_page(PAGES["explore"]).run()
    app.multiselect(key="filter_sectors").select("IT Services").run()
    app.switch_page(PAGES["compare"]).run()
    app.session_state["filters"] = {**app.session_state.filters, "sectors": ()}
    del app.session_state["filter_sectors"]
    app.switch_page(PAGES["explore"]).run()
    assert app.multiselect(key="filter_sectors").value == []


def test_explore_with_no_match_offers_clear_filters(small_db):
    app = open_page(PAGES["explore"]).run()
    app.toggle(key="filter_has_data_roles").set_value(True).run()   # the small database has no jobs
    assert app.info[0].value == "No companies match these filters."
    app.button(key="empty_clear_filters").click().run()
    assert app.session_state.filters["has_data_roles"] is False
    assert not app.info
    assert "2 of 2 companies" in [c.value for c in app.caption]


def test_the_explore_compare_picker_fills_the_compare_list(small_db):
    app = open_page(PAGES["explore"]).run()
    app.multiselect(key="explore_compare").select("acme").select("hooli").run()
    assert app.session_state.compare_ids == ["acme", "hooli"]
    app.switch_page(PAGES["compare"]).run()
    assert not app.exception, app.exception


# --- Company: which company, compare list, sector link, thin samples ---------

def test_the_url_opens_its_company_in_a_new_session(small_db):
    """A refresh or a shared link: no company chosen yet, so ?company= wins."""
    app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=30)
    app.query_params["company"] = "hooli"
    app.run()
    app.switch_page(PAGES["company"]).run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Hooli"
    assert app.query_params["company"] == ["hooli"] or app.query_params["company"] == "hooli"


def test_an_unknown_company_in_the_url_is_ignored(small_db):
    app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=30)
    app.query_params["company"] = "no-such-company"
    app.run()
    app.switch_page(PAGES["company"]).run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Acme"


def test_company_adds_to_and_removes_from_the_compare_list(small_db):
    app = open_page(PAGES["company"]).run()
    next(b for b in app.button if b.label == "Add to compare").click().run()
    assert app.session_state.compare_ids == ["acme"]
    next(b for b in app.button if b.label == "Remove from compare").click().run()
    assert app.session_state.compare_ids == []


def test_the_sector_link_opens_explore_filtered_to_it(small_db):
    app = open_page(PAGES["company"]).run()
    next(b for b in app.button if b.label == "IT Services").click().run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Explore companies"
    assert app.multiselect(key="filter_sectors").value == ["IT Services"]


def test_under_20_reviews_the_company_shows_the_count_not_a_score(small_db):
    conn = get_conn(small_db)
    conn.execute(
        "INSERT INTO review_summary (company_id, period, review_count, first_date, last_date,"
        " avg_compound, share_positive, share_neutral, share_negative, pre_merger_count)"
        " VALUES ('hooli', 'all', 12, '2022-01-01', '2023-01-01', 0.4, 0.7, 0.2, 0.1, 0)"
    )
    conn.commit()
    conn.close()
    app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=30)
    app.query_params["company"] = "hooli"
    app.run()
    app.switch_page(PAGES["company"]).run()
    assert not app.exception, app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Employee sentiment"] == "Fewer than 20 reviews (n = 12)"
    assert metrics["Reviews analysed"] == "12"
    assert metrics["Published attrition"] == "Not available"


# --- Explore: featured cards and recent articles ------------------------------

@pytest.fixture
def featured_db(small_db):
    """small_db plus everything a featured card needs for Acme: published
    attrition, a data-role listing and two articles (one per label)."""
    conn = get_conn(small_db)
    conn.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, attrition_text,"
        " basis, scope, definition, entity, source_url, source_ref, retrieved_on)"
        " VALUES ('acme', 0, 'FY2024-25', '2025-03-31', 12.5, '12.5', 'voluntary', 'group', 'd', 'Acme Ltd',"
        " 'https://example.com/ar', 'p. 4', '2026-10-01')"
    )
    conn.execute("INSERT INTO jobs (job_id, company_id, title) VALUES ('acme-1', 'acme', 'Data Analyst')")
    conn.executemany(
        "INSERT INTO articles (article_id, company_id, title, outlet, published_at, url, sentiment_compound,"
        " sentiment_label) VALUES (?, ?, ?, 'Reuters', ?, 'https://example.com/n', ?, ?)",
        [("acme:1", "acme", "Acme hires", "2026-10-19T08:00:00Z", 0.4, "positive"),
         ("hooli:1", "hooli", "Hooli cuts", "2026-10-20T08:00:00Z", -0.5, "negative")],
    )
    conn.commit()
    conn.close()
    return small_db


def test_a_featured_card_opens_its_company(featured_db):
    app = open_page(PAGES["explore"]).run()
    assert not app.exception, app.exception
    assert "Featured companies" in [h.value for h in app.subheader]
    app.button(key="feature_acme").click().run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Acme"


def test_a_company_without_every_card_figure_is_not_featured(featured_db):
    app = open_page(PAGES["explore"]).run()
    keys = [b.key for b in app.button]
    assert "feature_acme" in keys and "feature_hooli" not in keys


def test_recent_articles_tabs_count_and_open_the_company(featured_db):
    app = open_page(PAGES["explore"]).run()
    assert [t.label for t in app.tabs] == ["Positive (1)", "Neutral (0)", "Negative (1)"]
    app.button(key="news_negative_hooli:1").click().run()
    assert not app.exception, app.exception
    assert app.title[0].value == "Hooli"


def test_without_a_careers_site_the_openings_button_is_drawn_disabled(small_db):
    app = open_page(PAGES["company"]).run()   # the small database has no careers URLs
    button = app.button(key="careers_not_available")
    assert button.label == "Careers page not available" and button.disabled
