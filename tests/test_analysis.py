import pandas as pd
import pytest

from jmsa.display import NOT_AVAILABLE
from process.analysis import (
    MIN_MENTIONS, kappa_from_crosstab, kappa_note, md_table, section_yearly, theme_comparison,
    theme_subrating_rows, top_companies, yearly_sentiment,
)

# The library fixture holds acme, globex and initech.


def add_summary(db, company_id, review_count, pay_count, pay_compound):
    db.execute("INSERT INTO review_summary (company_id, period, review_count, pay_count, pay_compound,"
               " pre_merger_count) VALUES (?, 'all', ?, ?, ?, 0)",
               (company_id, review_count, pay_count, pay_compound))


def add_reviews(db, company_id, count, start=0, date="2022-06-01", compound=0.5, pay_rating=3):
    db.executemany(
        "INSERT INTO reviews (review_id, company_id, review_date, sentiment_compound,"
        " compensation_and_benefits) VALUES (?, ?, ?, ?, ?)",
        [(f"{company_id}-{start + n}", company_id, date, compound, pay_rating) for n in range(count)])


@pytest.fixture
def themes(library):
    """Three companies with pay mentions and pay sub-ratings, plus a fourth too thin to count."""
    library.execute("INSERT INTO companies (company_id, name, sector) VALUES ('hooli', 'Hooli', 'IT Services')")
    # Theme scores rank acme < globex < initech; sub-ratings rank initech < acme < globex.
    for company_id, compound, rating in (("acme", 0.1, 3), ("globex", 0.2, 4), ("initech", 0.3, 2)):
        add_summary(library, company_id, 25, MIN_MENTIONS, compound)
        add_reviews(library, company_id, 20, pay_rating=rating)
    add_summary(library, "hooli", 25, MIN_MENTIONS - 1, 0.9)   # too few mentions
    add_reviews(library, "hooli", 20, pay_rating=5)
    library.commit()
    return library


def test_theme_rows_keep_companies_with_enough_mentions(themes):
    rows = theme_subrating_rows(themes, "pay")
    assert [r["company_id"] for r in rows] == ["acme", "globex", "initech"]
    assert rows[0]["subrating"] == "compensation_and_benefits"
    assert rows[1]["subrating_mean"] == pytest.approx(4)


def test_theme_rows_need_20_subratings(themes):
    themes.execute("UPDATE reviews SET compensation_and_benefits = NULL WHERE review_id = 'acme-0'")
    assert [r["company_id"] for r in theme_subrating_rows(themes, "pay")] == ["globex", "initech"]


def test_theme_comparison_spearman_and_disagreements(themes):
    result = theme_comparison(theme_subrating_rows(themes, "pay"))
    # Theme ranks 1, 2, 3 against sub-rating ranks 2, 3, 1: d^2 = 1 + 1 + 4 = 6,
    # so 1 - 6*6/(3*8) = -0.5.
    assert result["n"] == 3
    assert result["spearman"] == pytest.approx(-0.5)
    assert [r["company_id"] for r in result["disagree"]] == ["initech", "acme", "globex"]
    assert result["disagree"][0]["rank_gap"] == 2


def test_yearly_sentiment_applies_the_20_review_rule(library):
    add_reviews(library, "acme", 20, date="2021-03-01", compound=0.4)
    add_reviews(library, "acme", 5, start=100, date="2022-03-01", compound=0.1)
    add_reviews(library, "acme", 30, start=200, date="2007-03-01")        # before 2008: left out
    frame = yearly_sentiment(library, ["acme"]).set_index("year")
    assert frame.loc[2021, "reviews"] == 20
    assert frame.loc[2021, "avg_compound"] == pytest.approx(0.4)
    assert frame.loc[2022, "reviews"] == 5
    assert pd.isna(frame.loc[2022, "avg_compound"])
    assert 2007 not in frame.index
    assert len(frame) == 16                                              # 2008 to 2023


def test_yearly_section_marks_sparse_2023(library):
    add_summary(library, "acme", 40, 0, None)
    add_reviews(library, "acme", 20, date="2023-01-15")
    add_reviews(library, "acme", 20, start=100, date="2023-07-10")
    library.commit()
    assert top_companies(library) == ["acme"]
    text, tables = section_yearly(library)
    assert "| 2023* | +0.50 (40) |" in text
    assert "Jan to Jul 2023 (sparse after Mar 2023)" in text
    assert f"| 2022 | {NOT_AVAILABLE} |" in text
    assert list(tables) == ["d_yearly_sentiment.csv"]


def test_kappa_from_crosstab_orders_and_fills_labels():
    crosstab = pd.DataFrame({"positive": [1, 8], "negative": [5, 1]}, index=["negative", "positive"])
    counts, figures = kappa_from_crosstab(crosstab)
    assert counts == [[5, 0, 1], [0, 0, 0], [1, 0, 8]]
    assert figures["p_o"] == pytest.approx(13 / 15)


def test_kappa_note_wording():
    note = kappa_note({"p_o": 0.80508, "p_e": 0.6747, "kappa": 0.4008})
    assert note == ("VADER and TextBlob agree on 80.5% of labels (raw agreement); "
                    "Cohen's kappa 0.40, on the fair/moderate boundary (Landis-Koch).")


def test_md_table():
    assert md_table(["a", "b"], [[1, 2]]) == "| a | b |\n|---|---|\n| 1 | 2 |"
