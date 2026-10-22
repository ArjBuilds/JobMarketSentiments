"""Check the review sentiment method, for the report. Writes nothing to the database.

Run with:  python -m process.sentiment_checks

Run process.review_sentiment first. Three checks, each on a seeded random
sample, so every run gives the same numbers:

    1. Method comparison (seed 42, 20,000 reviews with a star rating): how
       well each way of feeding a review to VADER tracks the star rating.
       F is the method the pipeline uses, read from the stored scores.
    2. Held-out (seed 7, another 20,000, none of them in sample 1): method F
       again. F was chosen on sample 1, so this shows the result isn't
       specific to the sample it was chosen on.
    3. TextBlob cross-check (seed 42, 50,000 scored reviews): TextBlob scores
       the same parts with the same formula and cut-offs, and we count how
       often its label agrees with VADER's.

Prints the results and writes data/raw/sentiment_checks.txt.
"""

from __future__ import annotations

import random
import sqlite3
import sys

import pandas as pd
from textblob import TextBlob
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from jmsa.config import RAW_DIR
from jmsa.db import get_conn
from jmsa.sentiment import NEGATIVE_AT, POSITIVE_AT, combine

REPORT_TXT = RAW_DIR / "sentiment_checks.txt"

METHOD_SEED, HELD_OUT_SEED = 42, 7
METHOD_SAMPLE = 20_000
TEXTBLOB_SAMPLE = 50_000

# SQLite caps the number of ? placeholders in one statement.
IDS_PER_QUERY = 900


def draw_samples(ids: list[str], size: int) -> tuple[list[str], list[str]]:
    """(method sample, held-out sample): two seeded samples with no review in both.

    The held-out sample is drawn only from the ids the first sample didn't take.
    """
    first = random.Random(METHOD_SEED).sample(ids, min(size, len(ids)))
    taken = set(first)
    rest = [review_id for review_id in ids if review_id not in taken]
    held_out = random.Random(HELD_OUT_SEED).sample(rest, min(size, len(rest)))
    return first, held_out


def fetch(conn: sqlite3.Connection, ids: list[str]) -> pd.DataFrame:
    """The sampled reviews, with empty text as "" rather than None."""
    frames = []
    for start in range(0, len(ids), IDS_PER_QUERY):
        chunk = ids[start:start + IDS_PER_QUERY]
        frames.append(pd.read_sql_query(
            "SELECT review_id, rating, headline, pros, cons, sentiment_compound, sentiment_label "
            f"FROM reviews WHERE review_id IN ({', '.join('?' for _ in chunk)})",
            conn, params=chunk,
        ))
    reviews = pd.concat(frames, ignore_index=True)
    for column in ("headline", "pros", "cons"):
        reviews[column] = reviews[column].fillna("")
    return reviews


def labels(scores: pd.Series) -> pd.Series:
    return pd.Series(
        ["positive" if s >= POSITIVE_AT else "negative" if s <= NEGATIVE_AT else "neutral" for s in scores],
        index=scores.index,
    )


def star_labels(ratings: pd.Series) -> pd.Series:
    """4-5 stars positive, 3 neutral, 1-2 negative."""
    return pd.Series(
        ["positive" if r >= 4 else "negative" if r <= 2 else "neutral" for r in ratings],
        index=ratings.index,
    )


def method_stats(scores: pd.Series, ratings: pd.Series) -> dict[str, float]:
    """How well one method's scores track the star ratings, as numbers."""
    # Spearman is Pearson on the ranks; computing it this way avoids scipy.
    shares = labels(scores).value_counts(normalize=True)
    return {
        "pearson": scores.corr(ratings),
        "spearman": scores.rank().corr(ratings.rank()),
        "positive": shares.get("positive", 0),
        "neutral": shares.get("neutral", 0),
        "negative": shares.get("negative", 0),
        "agree_with_stars": (labels(scores) == star_labels(ratings)).mean(),
    }


def method_row(name: str, scores: pd.Series, ratings: pd.Series) -> str:
    s = method_stats(scores, ratings)
    return (f"  {name:38} {s['pearson']:7.3f} {s['spearman']:8.3f}   "
            f"{s['positive']:4.0%} {s['neutral']:4.0%} "
            f"{s['negative']:4.0%}   {s['agree_with_stars']:6.1%}")


HEADER = (f"  {'method':38} {'pearson':>7} {'spearman':>8}   {'pos':>4} {'neu':>4} {'neg':>4}   "
          f"{'agree w/ stars':>6}")


def method_scores(reviews: pd.DataFrame) -> dict[str, pd.Series]:
    """Each candidate method's score for every review, by method name."""
    analyzer = SentimentIntensityAnalyzer()

    def vader(text: str) -> float:
        return analyzer.polarity_scores(text)["compound"] if text else 0.0

    h, p, c = (reviews[part].map(vader) for part in ("headline", "pros", "cons"))
    joined = (reviews["headline"] + ". " + reviews["pros"] + ". " + reviews["cons"]).map(vader)
    return {
        "A headline only": h,
        "B headline+pros+cons as one text": joined,
        "C (pros - cons)/2": (p - c) / 2,
        "D (pros + cons)/2": (p + c) / 2,
        "E (headline + pros + cons)/3": (h + p + c) / 3,
        "F (headline + (pros+cons)/2)/2  [used]": reviews["sentiment_compound"],
    }


def compare_methods(reviews: pd.DataFrame) -> list[str]:
    methods = method_scores(reviews)
    ratings = reviews["rating"]
    stars = star_labels(ratings).value_counts(normalize=True)
    lines = [HEADER] + [method_row(name, scores, ratings) for name, scores in methods.items()]
    lines.append(f"  star ratings in this sample: {stars.get('positive', 0):.0%} positive, "
                 f"{stars.get('neutral', 0):.0%} neutral, {stars.get('negative', 0):.0%} negative")
    return lines


def textblob_crosstab(reviews: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """(table, agreement): VADER's labels (rows) against TextBlob's (columns),
    for the reviews TextBlob could score, and the share where they agree."""
    def polarity(text: str) -> float | None:
        return TextBlob(text).sentiment.polarity if text else None

    tb = pd.Series(
        [combine(polarity(r.headline), polarity(r.pros), polarity(r.cons)) for r in reviews.itertuples()],
        index=reviews.index,
    )
    scored = tb.notna()
    tb_labels = labels(tb[scored])
    vader_labels = reviews.loc[scored, "sentiment_label"]
    agree = (tb_labels == vader_labels).mean()
    return pd.crosstab(vader_labels.rename("VADER"), tb_labels.rename("TextBlob")), agree


def textblob_sample(conn: sqlite3.Connection) -> list[str]:
    """The seeded sample of scored reviews the TextBlob check runs on."""
    scored = [r[0] for r in conn.execute(
        "SELECT review_id FROM reviews WHERE sentiment_compound IS NOT NULL ORDER BY review_id")]
    return random.Random(METHOD_SEED).sample(scored, min(TEXTBLOB_SAMPLE, len(scored)))


def rated_samples(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    """(method sample, held-out sample) of reviews with a star rating and a score."""
    rated = [r[0] for r in conn.execute(
        "SELECT review_id FROM reviews WHERE rating IS NOT NULL AND sentiment_compound IS NOT NULL "
        "ORDER BY review_id")]
    if not rated:
        raise SystemExit("no scored reviews; run python -m ingest.load_reviews and "
                         "python -m process.review_sentiment first")
    return draw_samples(rated, METHOD_SAMPLE)


def textblob_check(reviews: pd.DataFrame) -> list[str]:
    table, agree = textblob_crosstab(reviews)
    return [
        f"  reviews compared: {int(table.to_numpy().sum()):,}",
        f"  VADER/TextBlob label agreement: {agree:.1%}",
        "  rows are VADER's label, columns TextBlob's:",
        *("    " + line for line in table.to_string().splitlines()),
    ]


def build_report(conn: sqlite3.Connection) -> str:
    method_ids, held_out_ids = rated_samples(conn)

    lines = [
        "Review sentiment checks",
        f"Labels: positive at >= {POSITIVE_AT}, negative at <= {NEGATIVE_AT}, neutral otherwise.",
        "Stars: 4-5 positive, 3 neutral, 1-2 negative. Empty text scores 0 in methods A-E.",
        "",
        f"1. Method comparison (seed {METHOD_SEED}, {len(method_ids):,} reviews with a star rating)",
        *compare_methods(fetch(conn, method_ids)),
        "",
        f"2. Held-out: method F on a separate sample (seed {HELD_OUT_SEED}, "
        f"{len(held_out_ids):,} reviews, none in sample 1)",
    ]
    if held_out_ids:
        held_out = fetch(conn, held_out_ids)
        lines += [HEADER, method_row("F held-out", held_out["sentiment_compound"], held_out["rating"])]
    else:
        lines.append("  not enough reviews loaded for a second sample")

    textblob_ids = textblob_sample(conn)
    lines += [
        "",
        f"3. TextBlob cross-check (seed {METHOD_SEED}, {len(textblob_ids):,} scored reviews, "
        "same formula and cut-offs)",
        *textblob_check(fetch(conn, textblob_ids)),
    ]
    return "\n".join(lines)


def main() -> int:
    conn = get_conn()
    try:
        report = build_report(conn)
    finally:
        conn.close()
    print(report)
    REPORT_TXT.write_text(report + "\n", encoding="utf-8")
    print(f"\nwrote {REPORT_TXT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
