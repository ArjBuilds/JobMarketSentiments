"""How the dashboard shows a value, including one that is missing.

The missing-data rule (PRD.md): a field with no data reads "not available",
never None, NaN, a blank or an estimate. Every page formats values through
show() so the rule lives in one place.
"""

from __future__ import annotations

import math

NOT_AVAILABLE = "not available"


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
