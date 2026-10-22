"""How the dashboard shows a value, including one that is missing.

The missing-data rule (PRD.md): a field with no data reads "Not available",
never None, NaN, a blank or an estimate. Every page formats values through
show() so the rule lives in one place.
"""

from __future__ import annotations

import math

NOT_AVAILABLE = "Not available"


def show(value):
    """Return value unchanged, or NOT_AVAILABLE if it is None, NaN or blank."""
    if value is None:
        return NOT_AVAILABLE
    # NaN is the one value that isn't equal to itself; pandas uses it for gaps.
    if isinstance(value, float) and math.isnan(value):
        return NOT_AVAILABLE
    if isinstance(value, str) and not value.strip():
        return NOT_AVAILABLE
    return value


def plural(n: int, word: str, many: str | None = None) -> str:
    """'1 company', '2 companies', '1,200 reviews': a count with its noun.

    many is the plural when adding an s won't do; a word ending in a
    consonant + y takes -ies on its own.
    """
    if n == 1:
        noun = word
    elif many is not None:
        noun = many
    elif word.endswith("y") and word[-2:-1] not in "aeiou":
        noun = word[:-1] + "ies"
    else:
        noun = word + "s"
    return f"{n:,} {noun}"
