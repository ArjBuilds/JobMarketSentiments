"""The two statistics the report needs, by hand so the stack stays as the PRD fixes it.

    spearman()      rank correlation: the proxy comparison (ingest.load_turnover)
                    and themes against sub-ratings (process.analysis)
    cohens_kappa()  agreement beyond chance: VADER against TextBlob labels

No scipy or sklearn: each is a few lines on top of the stdlib.
"""

from __future__ import annotations

import statistics

# Below this many pairs a rank correlation says nothing.
MIN_PAIRS = 3


def ranks(values: list[float]) -> list[float]:
    """1-based ranks, ties sharing the average of the ranks they span."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    result = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            result[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return result


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman's rank correlation: Pearson's r on the ranks.

    None with fewer than MIN_PAIRS pairs, or when one side has no spread
    (every value tied), where a correlation isn't defined.
    """
    if len(xs) < MIN_PAIRS:
        return None
    rx, ry = ranks(xs), ranks(ys)
    if len(set(rx)) < 2 or len(set(ry)) < 2:
        return None
    return statistics.correlation(rx, ry)


def cohens_kappa(table: list[list[int]]) -> dict[str, float]:
    """Cohen's kappa from a square agreement table (rows: rater A, columns: rater B).

    p_o is the share on the diagonal (raw agreement). p_e is the agreement
    two raters would reach by chance with these label shares: for each label,
    A's share times B's share, summed. kappa = (p_o - p_e) / (1 - p_e), so
    0 is chance-level agreement and 1 is perfect.
    """
    size = len(table)
    if size < 2 or any(len(row) != size for row in table):
        raise ValueError("kappa needs a square table with at least two labels")
    total = sum(sum(row) for row in table)
    if total == 0:
        raise ValueError("kappa needs at least one rated item")
    p_o = sum(table[i][i] for i in range(size)) / total
    row_shares = [sum(row) / total for row in table]
    col_shares = [sum(row[j] for row in table) / total for j in range(size)]
    p_e = sum(r * c for r, c in zip(row_shares, col_shares))
    if p_e == 1:
        raise ValueError("kappa is undefined when both raters use one label only")
    return {"p_o": p_o, "p_e": p_e, "kappa": (p_o - p_e) / (1 - p_e)}


LANDIS_KOCH = ((0, "poor"), (0.20, "slight"), (0.40, "fair"), (0.60, "moderate"),
               (0.80, "substantial"), (1, "almost perfect"))


def landis_koch(kappa: float) -> str:
    """The Landis and Koch (1977) band for a kappa, e.g. 'moderate'.

    A kappa that rounds to a band edge at two decimals (0.4008 is shown as
    0.40) is reported as 'on the fair/moderate boundary', so the band never
    contradicts the number printed beside it.
    """
    for (upper, band), (_, next_band) in zip(LANDIS_KOCH, LANDIS_KOCH[1:]):
        if round(kappa, 2) == upper:
            return f"on the {band}/{next_band} boundary"
    for upper, band in LANDIS_KOCH:
        if kappa <= upper:
            return band
    return LANDIS_KOCH[-1][1]
