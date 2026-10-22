import pytest

from jmsa.compare import NEWS_ARTICLES, NEWS_FETCHED, compare_table, metric_labels
from jmsa.display import NOT_AVAILABLE
from jmsa.library import column_headers, load_library


@pytest.fixture
def records(db):
    """acme has every figure; hooli has none; tiny has 12 reviews; mind is pre-merger."""
    db.executemany(
        "INSERT INTO companies (company_id, name, sector, hq_country, glassdoor_rating,"
        " glassdoor_review_count) VALUES (?, ?, 'IT Services', 'India', ?, ?)",
        [("acme", "Acme", 4.1, 2500), ("hooli", "Hooli", None, None),
         ("tiny", "Tiny", 3.6, 40), ("mind", "Mind", None, None)],
    )
    db.executemany(
        "INSERT INTO review_summary (company_id, period, review_count, avg_compound, pre_merger_count)"
        " VALUES (?, ?, ?, ?, ?)",
        [("acme", "all", 1200, 0.21, 0), ("acme", "2020-2023", 400, 0.15, 0),
         ("tiny", "all", 12, 0.5, 0), ("tiny", "2020-2023", 12, 0.5, 0),
         ("mind", "all", 300, 0.3, 300)],
    )
    db.executemany("INSERT INTO jobs (job_id, company_id, title) VALUES (?, 'acme', 'Data Analyst')",
                   [("nk-1",), ("nk-2",), ("nk-3",)])
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, attrition_pct,"
        " attrition_text, basis, scope, definition, entity, source_url, source_ref, retrieved_on)"
        " VALUES ('acme', 0, 'FY2025-26', '2025-04-01', '2026-03-31', 12.8, '12.8', 'voluntary',"
        " 'segment', 'd', 'e', 'https://example.com/r.pdf', 'p. 4', '2026-10-22')"
    )
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, proxy_share,"
        " reviews_in_window, reviews_matched, reviews_leaving, reviews_layoffs, definition, entity,"
        " method_note) VALUES ('acme', 1, 'w', '2021-04-01', '2023-03-31', 0.05, 1000, 50, 30, 25,"
        " 'd', 'e', 'm')"
    )
    db.commit()
    return load_library(db)


def news(rows=0, fetched_on="21 Oct 2026"):
    return {"available": bool(rows), "fetched_on": fetched_on, "rows": [{}] * rows,
            "message": None}


def table(records, ids, news_by_id=None):
    """compare_table as {metric: {company name: cell}}."""
    rows = compare_table(records, news_by_id or {}, ids)
    return {row.pop("Metric"): row for row in rows}


@pytest.mark.parametrize("ids", [["acme"], ["acme", "hooli", "tiny", "mind", "acme"], []])
def test_fewer_than_two_or_more_than_four_is_refused(records, ids):
    with pytest.raises(ValueError):
        compare_table(records, {}, ids)


def test_an_unknown_company_is_refused(records):
    with pytest.raises(ValueError, match="nobody"):
        compare_table(records, {}, ["acme", "nobody"])


def test_labels_are_the_library_headers_for_both_periods_plus_news():
    labels = metric_labels()
    for period in ("all", "2020-2023"):
        headers = column_headers(period)
        for key in ("rating", "rating_count", "sentiment", "reviews", "data_roles", "attrition",
                    "proxy", "proxy_split"):
            assert headers[key] in labels
    assert labels[-2:] == [NEWS_ARTICLES, NEWS_FETCHED]
    assert column_headers("all")["name"] not in labels   # the company is the column, not a row


def test_one_column_per_company_in_the_order_picked(records):
    rows = compare_table(records, {}, ["tiny", "acme"])
    assert list(rows[0]) == ["Metric", "Tiny", "Acme"]


def test_a_company_with_every_figure(records):
    cells = {metric: row["Acme"] for metric, row in table(records, ["acme", "hooli"], {"acme": news(6)}).items()}
    headers = column_headers("all")
    assert cells[headers["rating"]] == "4.1"
    assert cells[headers["rating_count"]] == "2,500"
    assert cells[headers["sentiment"]] == "+0.21 · Positive"
    assert cells[headers["reviews"]] == "1,200"
    assert cells[column_headers("2020-2023")["reviews"]] == "400"
    assert cells[headers["data_roles"]] == "3"
    # Published attrition always carries its basis, scope and period.
    assert cells[headers["attrition"]] == "12.8% · voluntary · segment · FY2025-26"
    assert cells[headers["proxy"]] == "5.0"
    assert cells[NEWS_ARTICLES] == "6"
    assert cells[NEWS_FETCHED] == "21 Oct 2026"


def test_a_company_with_no_figures_is_not_available_everywhere(records):
    cells = {metric: row["Hooli"] for metric, row in table(records, ["acme", "hooli"]).items()}
    for metric, cell in cells.items():
        if metric in (column_headers("all")["sector"], column_headers("all")["hq_country"]):
            continue
        assert cell == NOT_AVAILABLE, metric


def test_news_fetched_with_no_articles_is_not_available_not_zero(records):
    cells = table(records, ["acme", "hooli"], {"hooli": news(0)})
    assert cells[NEWS_ARTICLES]["Hooli"] == NOT_AVAILABLE
    assert cells[NEWS_FETCHED]["Hooli"] == "21 Oct 2026"


def test_under_20_reviews_is_hidden_but_shows_its_count(records):
    cells = table(records, ["acme", "tiny"])
    assert cells[column_headers("all")["sentiment"]]["Tiny"] == "Fewer than 20 reviews (n = 12)"
    assert cells[column_headers("all")["reviews"]]["Tiny"] == "12"


def test_pre_merger_reviews_are_labelled(records):
    cells = table(records, ["acme", "mind"])
    assert cells[column_headers("all")["sentiment"]]["Mind"].endswith("· pre-merger Mindtree reviews")
    # No reviews in 2020-2023: not available, not a 0.
    assert cells[column_headers("2020-2023")["reviews"]]["Mind"] == NOT_AVAILABLE


def test_every_cell_is_text(records):
    for row in compare_table(records, {"acme": news(2)}, ["acme", "hooli", "tiny", "mind"]):
        for value in row.values():
            assert isinstance(value, str) and value.strip()
