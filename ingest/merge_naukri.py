"""Try to rebuild naukri_jobs_merged.csv from the three original Kaggle exports.

Run with:  python -m ingest.merge_naukri --src "/c/Users/wadar/Downloads/archive (1)"

A reproducibility check, not a loader: ingest.load_jobs and
process.skill_counts read the pinned data/raw/naukri_jobs_merged.csv, which
was merged by hand before the project began. This script reads the three
exports in --src (never changing them), applies the merge rules inferred
from the merged file, writes the result to its own file (never over the
merged file), and compares the two: columns, rows per source_file, row by
row, and file hashes.

The rules aren't recorded, so a few variants are each tried once, and the
closest is written and reported with its differences. No variant is tuned
to force a match. Writes data/raw/naukri_merge_check.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from jmsa.config import RAW_DIR

MERGED_CSV = RAW_DIR / "naukri_jobs_merged.csv"
REBUILT_CSV = RAW_DIR / "naukri_jobs_merged.rebuilt.csv"
REPORT_PATH = RAW_DIR / "naukri_merge_check.txt"

# Export file name -> its source_file value, in merge order. The file names
# have spaces where the source_file values have underscores, so the mapping
# is spelled out rather than derived.
EXPORTS = {
    "NaukriData_Data Science.csv": "NaukriData_Data_Science",
    "NaukriData_data analytics.csv": "NaukriData_data_analytics",
    "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data.csv": "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data",
}

# Rows per source_file in the merged file (PRD, "The postings snapshot").
EXPECTED_ROWS = {
    "NaukriData_Data_Science": 11_465,
    "NaukriData_data_analytics": 12_686,
    "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data": 19_479,
}

# The two header styles: underscores in the first two exports, spaces in the
# third, which also has no link or post-time column.
COLUMN_MAP = {
    "Job_Titles": "job_title", "Job Titles": "job_title",
    "Company_Names": "company_name", "Company Names": "company_name",
    "Experience_Required": "experience_required", "Experience Required": "experience_required",
    "Package_Details": "package", "Package": "package",
    "Locations": "locations",
    "Skills": "skills_raw",
    "Post_Url": "post_url",
    "Post_Time": "post_time_relative",
}

CONTENT = ["job_title", "company_name", "experience_required", "package", "locations", "skills_raw",
           "post_url", "post_time_relative"]
COLUMNS = ["job_row_id", *CONTENT, "source_file"]

SAMPLES = 5


def read_export(path: Path, source_file: str) -> pd.DataFrame:
    """One export with the merged file's column names; every cell as text,
    with an empty cell as "" (no NaN), and the columns it lacks as ""."""
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    unknown = [c for c in frame.columns if c not in COLUMN_MAP]
    if unknown:
        raise ValueError(f"{path.name}: unexpected columns {unknown}")
    frame = frame.rename(columns=COLUMN_MAP)
    for column in CONTENT:
        if column not in frame.columns:
            frame[column] = ""
    frame["source_file"] = source_file
    return frame[[*CONTENT, "source_file"]]


def read_exports(src: Path) -> list[pd.DataFrame]:
    missing = [name for name in EXPORTS if not (src / name).is_file()]
    if missing:
        raise FileNotFoundError(f"not in {src}: {', '.join(missing)}")
    return [read_export(src / name, source_file) for name, source_file in EXPORTS.items()]


def drop_blank_titles(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["job_title"].str.strip() != ""]


# Each variant takes the exports in order and returns the merged rows, without
# job_row_id. Every one drops rows with no title: the merged file has none.

def within_export(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Whole-row duplicates dropped within each export, then concatenated."""
    return pd.concat([drop_blank_titles(f).drop_duplicates() for f in frames], ignore_index=True)


def within_export_stripped(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """As within_export, after trimming spaces from every cell."""
    return within_export([f.apply(lambda column: column.str.strip()) for f in frames])


def across_exports(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Whole-row duplicates (ignoring source_file) dropped across all three; first seen wins."""
    merged = pd.concat([drop_blank_titles(f) for f in frames], ignore_index=True)
    return merged.drop_duplicates(subset=CONTENT)


def within_export_by_listing(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """One row per title, employer and link within each export."""
    return pd.concat([drop_blank_titles(f).drop_duplicates(subset=["job_title", "company_name", "post_url"])
                      for f in frames], ignore_index=True)


VARIANTS = {
    "dedup whole rows within each export": within_export,
    "trim spaces, then dedup within each export": within_export_stripped,
    "dedup whole rows across exports": across_exports,
    "dedup title+employer+link within each export": within_export_by_listing,
}


def numbered(rows: pd.DataFrame) -> pd.DataFrame:
    """The merged file's layout: job_row_id from 1, then the content, then source_file."""
    rows = rows.reset_index(drop=True)
    rows.insert(0, "job_row_id", [str(n) for n in range(1, len(rows) + 1)])
    return rows[COLUMNS]


def row_keys(frame: pd.DataFrame) -> Counter:
    """Each row as (source_file, content...), counted, ignoring job_row_id."""
    return Counter(map(tuple, frame[["source_file", *CONTENT]].itertuples(index=False, name=None)))


def compare(rebuilt: pd.DataFrame, existing: pd.DataFrame) -> dict:
    """How far the rebuilt rows are from the existing file's.

    Two views: positional (row i against row i, job_row_id included), and as
    multisets ignoring job_row_id, so a difference in order alone shows up as
    positional mismatches with nothing only-in-one-file.
    """
    columns_equal = list(rebuilt.columns) == list(existing.columns)
    counts = {source: (int((rebuilt["source_file"] == source).sum()),
                       int((existing["source_file"] == source).sum()),
                       EXPECTED_ROWS[source]) for source in EXPECTED_ROWS}
    shared = min(len(rebuilt), len(existing))
    if columns_equal and shared:
        same = (rebuilt.iloc[:shared].to_numpy() == existing.iloc[:shared].to_numpy()).all(axis=1)
        positional = int(same.sum())
        first_diff = next((i for i, ok in enumerate(same) if not ok), None)
    else:
        positional, first_diff = 0, 0 if shared else None
    keys_rebuilt, keys_existing = row_keys(rebuilt), row_keys(existing)
    only_rebuilt, only_existing = keys_rebuilt - keys_existing, keys_existing - keys_rebuilt
    return {
        "columns_equal": columns_equal,
        "rows": (len(rebuilt), len(existing)),
        "counts": counts,
        "positional_equal": positional,
        "first_positional_diff": first_diff,
        "matched": sum((keys_rebuilt & keys_existing).values()),
        "only_rebuilt": only_rebuilt,
        "only_existing": only_existing,
        "reproduced": columns_equal and len(rebuilt) == len(existing) and positional == len(existing),
    }


def by_source(keys: Counter) -> dict[str, int]:
    totals: Counter = Counter()
    for key, n in keys.items():
        totals[key[0]] += n
    return dict(sorted(totals.items()))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sample_lines(keys: Counter) -> list[str]:
    lines = []
    for key in list(keys)[:SAMPLES]:
        source, title, company, *rest = key
        lines.append(f"    [{source}] {title!r} at {company!r}; package {rest[1]!r}, "
                     f"post time {rest[5]!r}, link {'yes' if rest[4] else 'no'}")
    return lines


def report(src: Path, variants: dict[str, dict], best: str, result: dict,
           rebuilt_path: Path, existing_path: Path, raw_rows: dict[str, int]) -> str:
    lines = [
        "Naukri merge reproducibility check",
        f"Exports read from: {src}",
        "Rows in each export as read: " + ", ".join(f"{s} {n:,}" for s, n in raw_rows.items()),
        "",
        "Variants tried (each once; rows matched = rows found in the existing file, ignoring job_row_id):",
    ]
    for name, r in variants.items():
        counts = " / ".join(f"{rebuilt:,}" for rebuilt, _, _ in r["counts"].values())
        lines.append(f"  {name:48} rows {r['rows'][0]:>6,} ({counts}); matched {r['matched']:,}"
                     f"{'   <- closest' if name == best else ''}")
    rebuilt_rows, existing_rows = result["rows"]
    lines += [
        "",
        f"Closest variant: {best}. Written to {rebuilt_path}",
        f"Columns equal: {'yes' if result['columns_equal'] else 'no'}",
        f"Rows: rebuilt {rebuilt_rows:,}, existing {existing_rows:,}",
        f"  {'source_file':52} {'rebuilt':>8} {'existing':>9} {'expected':>9}",
        *(f"  {source:52} {rebuilt:>8,} {existing:>9,} {expected:>9,}"
          for source, (rebuilt, existing, expected) in result["counts"].items()),
        f"Row by row (same position, job_row_id included): {result['positional_equal']:,} of "
        f"{existing_rows:,} equal"
        + (f"; first difference at row {result['first_positional_diff'] + 1:,}"
           if result["first_positional_diff"] is not None else ""),
        f"As multisets ignoring job_row_id: {result['matched']:,} rows in both",
        f"  only in rebuilt:  {sum(result['only_rebuilt'].values()):,} {by_source(result['only_rebuilt'])}",
        *sample_lines(result["only_rebuilt"]),
        f"  only in existing: {sum(result['only_existing'].values()):,} {by_source(result['only_existing'])}",
        *sample_lines(result["only_existing"]),
        "",
        f"SHA-256 rebuilt:  {sha256(rebuilt_path)}",
        f"SHA-256 existing: {sha256(existing_path)}",
        "",
        "Verdict: " + ("reproduced exactly." if result["reproduced"] else
                       "NOT reproduced. The pinned naukri_jobs_merged.csv stays the input of record."),
    ]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.merge_naukri")
    parser.add_argument("--src", type=Path, required=True, help="folder holding the three original exports")
    parser.add_argument("--out", type=Path, default=REBUILT_CSV, help="where to write the rebuilt file")
    parser.add_argument("--existing", type=Path, default=MERGED_CSV, help="the merged file to compare with")
    parser.add_argument("--report", type=Path, default=REPORT_PATH, help="where to write the check report")
    args = parser.parse_args(argv)

    if args.out.resolve() in (args.existing.resolve(), MERGED_CSV.resolve()):
        print(f"refusing to write over {args.out}: choose another --out", file=sys.stderr)
        return 2
    if not args.existing.is_file():
        print(f"no merged file at {args.existing} to compare with", file=sys.stderr)
        return 2
    try:
        frames = read_exports(args.src)
    except (FileNotFoundError, ValueError) as error:
        print(error, file=sys.stderr)
        return 2

    existing = pd.read_csv(args.existing, dtype=str, keep_default_na=False)
    tried = {name: compare(numbered(variant(frames)), existing) for name, variant in VARIANTS.items()}
    best = max(tried, key=lambda name: tried[name]["matched"])
    rebuilt = numbered(VARIANTS[best](frames))
    rebuilt.to_csv(args.out, index=False, lineterminator="\n")

    raw_rows = {f["source_file"].iat[0] if len(f) else name: len(f) for name, f in zip(EXPORTS, frames)}
    text = report(args.src, tried, best, tried[best], args.out, args.existing, raw_rows)
    print(text)
    args.report.write_text(text + "\n", encoding="utf-8")
    print(f"\nwrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
