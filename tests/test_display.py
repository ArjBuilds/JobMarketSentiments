import math

import pytest

from jmsa.display import NOT_AVAILABLE, plural, show


@pytest.mark.parametrize("value", [None, math.nan, "", "   "])
def test_show_turns_missing_values_into_not_available(value):
    assert show(value) == NOT_AVAILABLE


@pytest.mark.parametrize("value", [0, 0.0, "0", "Pune"])
def test_show_keeps_real_values_including_zero(value):
    assert show(value) == value


@pytest.mark.parametrize("n, word, expected", [
    (1, "company", "1 company"),
    (2, "company", "2 companies"),
    (0, "company", "0 companies"),
    (1, "review", "1 review"),
    (1799628, "review", "1,799,628 reviews"),
    (3, "proxy row", "3 proxy rows"),
    (2, "day", "2 days"),               # a vowel before the y: just add s
])
def test_plural(n, word, expected):
    assert plural(n, word) == expected


def test_plural_with_an_irregular_form():
    assert plural(2, "analysis", "analyses") == "2 analyses"
    assert plural(1, "analysis", "analyses") == "1 analysis"
