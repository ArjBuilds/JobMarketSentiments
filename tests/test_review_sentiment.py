import pytest
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from ingest.load_reviews import load_reviews
from jmsa.aliases import read_aliases
from jmsa.display import NOT_AVAILABLE
from jmsa.sentiment import combine, label, read_summary
from process.review_sentiment import (
    THEMES_CSV,
    ThemesError,
    build_report,
    read_themes,
    rebuild_summary,
    score_review,
    score_reviews,
)
from process.sentiment_checks import draw_samples, fetch

GOOD = {"headline": "Great place", "pros": "Friendly people", "cons": "Long commute"}


def rows(company_id, n, **fields):
    return [{"company_id": company_id, **GOOD, **fields} for _ in range(n)]


def run(db, write_reviews, reviews):
    """Load, score and summarise, as the two commands would."""
    load_reviews(db, write_reviews(reviews))
    score_reviews(db)
    rebuild_summary(db)


def periods(db, company_id):
    return {view["title"]: view for view in read_summary(db, company_id)["periods"]}


# --- labels and the scoring formula ---------------------------------------

@pytest.mark.parametrize("compound, expected", [
    (0.05, "positive"), (0.0499, "neutral"), (0.0, "neutral"),
    (-0.0499, "neutral"), (-0.05, "negative"), (None, None),
])
def test_label_cut_offs(compound, expected):
    assert label(compound) == expected


@pytest.mark.parametrize("parts, expected", [
    ((0.5, 0.8, -0.4), 0.35),      # mean(0.5, mean(0.8, -0.4))
    ((None, 0.8, -0.4), 0.2),      # no headline: the pros/cons net alone
    ((0.5, 0.8, None), 0.65),      # no cons: mean(headline, pros)
    ((None, None, None), None),    # no text: no score, not 0
])
def test_combine(parts, expected):
    result = combine(*parts)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# --- themes -----------------------------------------------------------------

@pytest.mark.parametrize("text, theme, matches", [
    ("Great work-life balance", "wlb", True),
    ("work/life balance is poor", "wlb", True),
    ("Work Life Balance", "wlb", True),
    ("Managers are kind", "management", True),
    ("Salary hikes are late", "pay", True),
    ("Joined PayPal last year", "pay", False),
    ("Payment portal is slow", "pay", False),
])
def test_theme_keywords(text, theme, matches):
    assert bool(read_themes(THEMES_CSV)[theme].search(text)) is matches


def test_unknown_theme_in_file_fails(tmp_path):
    path = tmp_path / "themes.csv"
    path.write_text("theme,keyword\npay,salary\nculture,team\nwlb,hours\nmanagement,boss\nperks,gym\n",
                    encoding="utf-8")
    with pytest.raises(ThemesError, match="'perks' is not one of"):
        read_themes(path)


def test_theme_without_keywords_fails(tmp_path):
    path = tmp_path / "themes.csv"
    path.write_text("theme,keyword\npay,salary\nculture,team\nwlb,hours\n", encoding="utf-8")
    with pytest.raises(ThemesError, match="'management' has no keywords"):
        read_themes(path)


def test_theme_score_comes_from_the_section_that_mentions_it():
    analyzer = SentimentIntensityAnalyzer()
    texts = {"headline": "Okay", "pros": "Great salary", "cons": "Terrible management"}
    compound, _, themes, pay, culture, wlb, management = score_review(analyzer, read_themes(THEMES_CSV), texts)
    assert themes == "pay;management"
    assert pay == analyzer.polarity_scores("Great salary")["compound"]
    assert management == analyzer.polarity_scores("Terrible management")["compound"]
    assert culture is None and wlb is None


# --- scoring runs -----------------------------------------------------------

def test_review_with_no_text_gets_no_score(library, write_reviews):
    run(library, write_reviews, [{"company_id": "acme", "rating": "", "review_date": ""}])
    row = library.execute("SELECT sentiment_compound, sentiment_label, themes FROM reviews").fetchone()
    assert tuple(row) == (None, None, None)
    assert "reviews with no text (sentiment stays NULL): 1" in build_report(library)


def test_rescore_is_idempotent(library, write_reviews):
    run(library, write_reviews, rows("acme", 3) + rows("globex", 2, cons="Bad managers"))
    first = [tuple(r) for r in library.execute("SELECT * FROM reviews ORDER BY review_id")]
    score_reviews(library, rescore=True)
    assert [tuple(r) for r in library.execute("SELECT * FROM reviews ORDER BY review_id")] == first


def test_default_run_scores_only_unscored_reviews(library, write_reviews):
    run(library, write_reviews, rows("acme", 3))
    # Mark one review as already scored with a value VADER would never give
    # this text, and clear another, as if a run had stopped before it.
    library.execute("UPDATE reviews SET sentiment_compound = 0.999 WHERE review_id = 'gd-0000001'")
    library.execute("UPDATE reviews SET sentiment_compound = NULL WHERE review_id = 'gd-0000002'")
    library.commit()
    stats = score_reviews(library)
    assert stats["processed"] == 1
    scores = dict(library.execute("SELECT review_id, sentiment_compound FROM reviews").fetchall())
    assert scores["gd-0000001"] == 0.999
    assert scores["gd-0000002"] == scores["gd-0000003"]


def test_limit_stops_early(library, write_reviews):
    load_reviews(library, write_reviews(rows("acme", 5)))
    assert score_reviews(library, limit=2)["processed"] == 2
    assert library.execute("SELECT count(*) FROM reviews WHERE sentiment_compound IS NULL").fetchone()[0] == 3


# --- summary and the display rules --------------------------------------------

def test_fewer_than_20_reviews_is_hidden_and_20_is_shown(library, write_reviews):
    run(library, write_reviews, rows("acme", 19) + rows("globex", 20))
    acme, globex = periods(library, "acme")["All time"], periods(library, "globex")["All time"]
    assert acme["average"] == "hidden: fewer than 20 reviews (19)"
    assert acme["shares"] == "hidden: fewer than 20 reviews (19)"
    assert acme["reviews"] == "19"          # the count is shown even when the score isn't
    assert globex["average"].startswith("+0.")
    assert globex["reviews"] == "20"


def test_theme_with_fewer_than_20_mentions_is_hidden(library, write_reviews):
    reviews = rows("acme", 19, pros="Good salary and nice team") + rows("acme", 1, pros="Nice team")
    run(library, write_reviews, reviews)
    themes = {t["Theme"]: t for t in periods(library, "acme")["All time"]["themes"]}
    assert themes["Pay"]["Reviews mentioning"] == "19"
    assert themes["Pay"]["Score"] == "hidden: fewer than 20 reviews (19)"
    assert themes["Culture"]["Score"].startswith("+")


def test_undated_review_counts_in_all_time_but_not_2020_2023(library, write_reviews):
    reviews = rows("acme", 1, review_date="") + rows("acme", 1, review_date="2022-03-01") \
        + rows("acme", 1, review_date="2015-03-01")
    run(library, write_reviews, reviews)
    counts = dict(library.execute(
        "SELECT period, review_count FROM review_summary WHERE company_id = 'acme'").fetchall())
    assert counts == {"all": 3, "2020-2023": 1}
    assert periods(library, "acme")["All time"]["range"] == "Mar 2015 – Mar 2022"


def test_company_with_no_reviews_shows_not_available(library, write_reviews):
    run(library, write_reviews, rows("acme", 25))
    assert library.execute(
        "SELECT count(*) FROM review_summary WHERE company_id = 'initech'").fetchone()[0] == 0
    summary = read_summary(library, "initech")
    assert summary["available"] is False
    for view in summary["periods"]:
        for key in ("range", "reviews", "average", "shares"):
            assert view[key] == NOT_AVAILABLE
        assert view["themes"] == []
    assert "not available (2): globex, initech" in build_report(library)


def test_pre_merger_reviews_carry_a_note(library, write_reviews):
    run(library, write_reviews, rows("acme", 20, is_pre_merger="1") + rows("globex", 20))
    assert "All 20 reviews are from Mindtree" in read_summary(library, "acme")["note"]
    assert read_summary(library, "globex")["note"] is None


def test_shares_add_up(library, write_reviews):
    run(library, write_reviews, rows("acme", 10) + rows("acme", 10, headline="Awful", pros="", cons="Terrible pay"))
    row = library.execute("SELECT * FROM review_summary WHERE company_id = 'acme' AND period = 'all'").fetchone()
    assert row["share_positive"] + row["share_neutral"] + row["share_negative"] == pytest.approx(1)
    assert row["share_negative"] == pytest.approx(0.5)


# --- the real alias file and the checks script ----------------------------------

def test_four_companies_have_no_review_alias():
    aliased = {company_id for company_id, _ in read_aliases("glassdoor_reviews")}
    assert aliased.isdisjoint({"atlassian", "workday", "jpmorgan-chase", "hdfc-bank"})


def test_held_out_sample_never_overlaps_and_is_repeatable():
    ids = [f"gd-{n:07d}" for n in range(1, 1001)]
    first, held_out = draw_samples(ids, 300)
    assert len(first) == len(held_out) == 300
    assert set(first).isdisjoint(held_out)
    assert draw_samples(ids, 300) == (first, held_out)


def test_checks_fetch_reads_sampled_reviews(library, write_reviews):
    run(library, write_reviews, rows("acme", 3))
    reviews = fetch(library, ["gd-0000001", "gd-0000003"])
    assert sorted(reviews["review_id"]) == ["gd-0000001", "gd-0000003"]
    assert reviews["sentiment_compound"].notna().all()
