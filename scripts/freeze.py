"""Record the frozen demo database in docs/freeze.md (milestone 10).

Run from the repo root, as the last step before the demo, after committing:

    python scripts/freeze.py

Writes the freeze date, the git commit (and a warning if the working tree
has uncommitted changes), the database's SHA-256 and size, every table's
row count, each source's dates as the pages show them (jmsa.freshness), and
the SHA-256 and size of every input file the loaders read. Anyone holding
the same input files can check they rebuilt the same database.
"""

import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Run as a script, so the repo root isn't on sys.path yet (as in app/app.py).
sys.path.insert(0, str(ROOT))

from ingest.merge_naukri import sha256  # noqa: E402
from jmsa.config import DATA_DIR, DB_PATH, RAW_DIR  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import read_freshness  # noqa: E402

FREEZE_MD = ROOT / "docs" / "freeze.md"

# The raw inputs the loaders read. all_reviews.csv (3.8 GB) is read only by
# ingest.load_glassdoor_reviews, which writes glassdoor_reviews_matched.csv;
# the matched file is what ingest.load_reviews loads, so it is the one hashed.
RAW_INPUTS = ["glassdoor_reviews_matched.csv", "glassdoor_company_ratings.csv",
              "naukri_jobs_merged.csv", "company_aliases.csv"]


def input_files() -> list[Path]:
    """The raw inputs, then every committed CSV in data/ (the library and keyword lists)."""
    return [RAW_DIR / name for name in RAW_INPUTS] + sorted(DATA_DIR.glob("*.csv"))


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Rows in every table, by name. Table names come from sqlite_master, not user input."""
    names = [row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in names}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def file_row(path: Path) -> list[str]:
    shown = path.relative_to(ROOT).as_posix()
    if not path.is_file():
        return [shown, "missing", "missing"]
    return [shown, f"{path.stat().st_size:,}", f"`{sha256(path)}`"]


def table(headers: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return "\n".join(lines + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows])


def freeze_text(conn: sqlite3.Connection, today: str, commit: str, dirty: bool,
                database: list[str], files: list[list[str]]) -> str:
    freshness = read_freshness(conn)
    parts = [
        "# Database freeze",
        f"Frozen on **{today}** at git commit `{commit}`.",
    ]
    if dirty:
        parts.append("**Warning: the working tree had uncommitted changes when this was written.** "
                     "Commit, then rerun `python scripts/freeze.py`.")
    parts += [
        "Written by `python scripts/freeze.py`. Rerun it after any reload; don't edit by hand.",
        "## Database",
        table(["file", "bytes", "SHA-256"], [database]),
        "## Rows per table",
        table(["table", "rows"], [[name, f"{n:,}"] for name, n in table_counts(conn).items()]),
        "## Sources and dates",
        "As the dashboard shows them (jmsa/freshness.py, read from the database).",
        table(["source", "used for", "dates", "licence"],
              [[e["Source"], e["Used for"], e["Dates"], e["Licence"]] for e in freshness.values()]),
        "## Input files",
        "The raw inputs the loaders read, then the committed CSVs in data/. data/raw/all_reviews.csv "
        "(3.8 GB) isn't hashed: only ingest.load_glassdoor_reviews reads it, to write "
        "glassdoor_reviews_matched.csv, which is.",
        table(["file", "bytes", "SHA-256"], files),
    ]
    return "\n\n".join(parts) + "\n"


def main() -> int:
    # Checked before connecting, because get_conn would create an empty file.
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}; build it first (see README).", file=sys.stderr)
        return 1
    commit = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    database = [DB_PATH.name, f"{DB_PATH.stat().st_size:,}", f"`{sha256(DB_PATH)}`"]
    files = [file_row(path) for path in input_files()]
    conn = get_conn()
    try:
        text = freeze_text(conn, date.today().isoformat(), commit, dirty, database, files)
    finally:
        conn.close()
    FREEZE_MD.parent.mkdir(parents=True, exist_ok=True)
    FREEZE_MD.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote {FREEZE_MD}")
    if dirty:
        print("warning: uncommitted changes; commit and rerun", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
