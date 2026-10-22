"""Write data/demo.db: the dashboard's data without the pipeline-only bulk.

Run from the repo root, after rebuilding data/jmsa.db:

    python scripts/make_demo_db.py

data/jmsa.db is about 770 MB, almost all of it the 1.8M rows of review text
in `reviews`, which no page reads (pages read the per-company figures in
review_summary). The demo copy keeps every table and row the pages read and
empties what they don't:
- reviews: every row (the review text);
- articles.summary: GNews's description of each article (pages show only
  the title, outlet, date and label);
- news_fetches.response_json: the cached GNews responses ('{}' instead, since
  the column is NOT NULL).
The result is about 1 MB and is committed, so a fresh clone opens the
dashboard without the pipeline (app/app.py falls back to it when
data/jmsa.db is missing). The full database stays local and gitignored.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Run as a script, so the repo root isn't on sys.path yet (as in app/app.py).
sys.path.insert(0, str(ROOT))

from jmsa.config import DB_PATH, DEMO_DB_PATH  # noqa: E402


def make_demo(source: Path, target: Path) -> None:
    """Copy source to target, then empty what the dashboard never reads."""
    target.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dest = sqlite3.connect(target)
    try:
        src.backup(dest)   # a consistent copy, read-only on the source
        with dest:
            dest.execute("DELETE FROM reviews")
            dest.execute("UPDATE articles SET summary = NULL")
            dest.execute("UPDATE news_fetches SET response_json = '{}'")
        dest.execute("VACUUM")   # give the freed pages back, or the file stays 770 MB
    finally:
        src.close()
        dest.close()


def main() -> int:
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}; build it first (see README).", file=sys.stderr)
        return 1
    if DB_PATH.resolve() == DEMO_DB_PATH.resolve():
        print("JMSA_DB_PATH points at the demo database itself; unset it first.", file=sys.stderr)
        return 1
    make_demo(DB_PATH, DEMO_DB_PATH)
    print(f"wrote {DEMO_DB_PATH} ({DEMO_DB_PATH.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
