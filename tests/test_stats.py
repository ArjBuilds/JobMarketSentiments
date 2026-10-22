import pytest

from jmsa.stats import cohens_kappa, landis_koch, ranks, spearman


def test_kappa_on_a_textbook_table():
    # 50 items: raters agree on 20 + 15 = 35 (p_o 0.70). Each rater says
    # "yes" half the time (25/50 and 30/50 -> p_e = 0.5*0.6 + 0.5*0.4 = 0.50).
    figures = cohens_kappa([[20, 5], [10, 15]])
    assert figures["p_o"] == pytest.approx(0.70)
    assert figures["p_e"] == pytest.approx(0.50)
    assert figures["kappa"] == pytest.approx(0.40)


def test_kappa_on_the_vader_textblob_table():
    # data/raw/sentiment_checks.txt: rows VADER, columns TextBlob (neg, neu, pos).
    figures = cohens_kappa([[2039, 1316, 1369], [579, 1623, 2578], [770, 3134, 36592]])
    assert figures["p_o"] == pytest.approx(0.80508)
    assert figures["kappa"] == pytest.approx(0.4008, abs=1e-4)


def test_kappa_perfect_and_chance():
    assert cohens_kappa([[10, 0], [0, 10]])["kappa"] == pytest.approx(1)
    # Agreement exactly at chance level gives 0.
    assert cohens_kappa([[25, 25], [25, 25]])["kappa"] == pytest.approx(0)


def test_kappa_rejects_bad_tables():
    with pytest.raises(ValueError):
        cohens_kappa([[0, 0], [0, 0]])
    with pytest.raises(ValueError):
        cohens_kappa([[1, 2, 3], [4, 5, 6]])
    with pytest.raises(ValueError):
        cohens_kappa([[5, 0], [0, 0]])        # one label only: p_e = 1


def test_landis_koch_bands():
    assert landis_koch(-0.1) == "poor"
    assert landis_koch(0.35) == "fair"
    assert landis_koch(0.55) == "moderate"
    assert landis_koch(0.9) == "almost perfect"
    # 0.4008 prints as 0.40, the fair/moderate edge.
    assert landis_koch(0.4008) == "on the fair/moderate boundary"


def test_ranks_and_spearman():
    assert ranks([10, 30, 20, 20]) == [1, 4, 2.5, 2.5]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1)
    # Ranks 1,2,3,4 against 1,3,2,4: d^2 sums to 2, so 1 - 6*2/(4*15) = 0.8.
    assert spearman([1, 2, 3, 4], [1, 3, 2, 4]) == pytest.approx(0.8)
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([1, 2, 3], [5, 5, 5]) is None
