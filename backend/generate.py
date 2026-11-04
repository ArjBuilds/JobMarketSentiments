"""Generate SYNTHETIC job postings into ClickHouse's synthetic_postings table.

Run with:  python -m backend.generate [--rows N] [--seed S] [--batch N] [--replace]

SYNTHETIC DATA, for load tests and benchmarks only. Not real postings, and
never written to the postings table. Every row is labelled four ways:
the table name, is_synthetic = 1 (a CHECK refuses anything else), a
dedupe_key starting "synthetic:" and board "synthetic". Employers are
"Synthetic Employer NNN", never a real company name.

"Realistic" means shaped like the real feed, not copied from it:
  employers  200, Zipf-weighted (a few post most of the jobs)
  dates      the 730 days to 2026-10-31, rising ~40% over the period,
             with weekends at a quarter of a weekday's volume
  titles     data and engineering roles with seniority levels
  skills     3-8 per posting from data/skills.csv, weighted by role family
             (an ML engineer lists PyTorch far more often than Excel)
  cities     Indian tech hubs, weighted, plus Remote

Same --seed and --rows give the same rows. Prints rows/sec for generation
and for the insert separately.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np

from backend import config
from backend.skills import synonym_table

DEFAULT_ROWS = 10_000_000
END_DAY = date(2026, 10, 31)
DAYS = 730
EMPLOYERS = [f"Synthetic Employer {i:03d}" for i in range(1, 201)]
CITIES = {"Bengaluru": 30, "Hyderabad": 16, "Pune": 12, "Chennai": 10, "Gurugram": 9, "Mumbai": 8,
          "Noida": 6, "Kolkata": 3, "Ahmedabad": 2, "Remote": 4}
LEVELS = ["", "Senior ", "Lead ", "Principal ", "Junior "]
LEVEL_WEIGHTS = [45, 30, 12, 5, 8]
# Role family -> (titles, department, skills it favours).
FAMILIES = {
    "data-eng": (["Data Engineer", "Big Data Engineer", "ETL Developer", "Analytics Engineer"], "Data",
                 ["SQL", "Python", "Spark", "AWS", "Airflow", "Kafka", "Snowflake", "Databricks", "Hadoop", "Azure"]),
    "ml": (["Machine Learning Engineer", "Data Scientist", "AI Engineer", "NLP Engineer"], "Data",
           ["Python", "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "Natural Language Processing", "Statistics", "SQL"]),
    "analyst": (["Data Analyst", "Business Analyst", "BI Developer", "Product Analyst"], "Analytics",
                ["SQL", "Excel", "Power BI", "Tableau", "Python", "Statistics", "Data Visualization"]),
    "backend": (["Backend Engineer", "Software Engineer", "Platform Engineer", "SRE"], "Engineering",
                ["Java", "Python", "Kubernetes", "Docker", "AWS", "SQL", "Go", "Git", "Linux"]),
}
FAMILY_WEIGHTS = [28, 22, 30, 20]
COMBOS_PER_FAMILY = 5000


def weights(values) -> np.ndarray:
    w = np.asarray(values, dtype=float)
    return w / w.sum()


def skill_combos(rng: np.random.Generator) -> list[list[list[str]]]:
    """COMBOS_PER_FAMILY skill lists per family, rows pick one: far cheaper than 10M draws."""
    known = sorted(set(synonym_table()[0].values()))
    combos = []
    for _titles, _dept, favoured in FAMILIES.values():
        favoured = [s for s in favoured if s in known]
        w = weights([8.0 if s in favoured else 0.15 for s in known])
        family = []
        for _ in range(COMBOS_PER_FAMILY):
            k = int(rng.integers(3, 9))
            family.append(sorted(rng.choice(known, size=k, replace=False, p=w).tolist()))
        combos.append(family)
    return combos


def day_weights() -> np.ndarray:
    days = [END_DAY - timedelta(days=DAYS - 1 - i) for i in range(DAYS)]
    trend = np.linspace(1.0, 1.4, DAYS)
    weekday = np.array([0.25 if d.weekday() >= 5 else 1.0 for d in days])
    return weights(trend * weekday)


def generate_batch(rng: np.random.Generator, seed: int, start: int, n: int, combos) -> list[list]:
    """Columns for rows start..start+n, in schema_clickhouse.sql's order."""
    employer = rng.choice(len(EMPLOYERS), size=n, p=weights(1 / np.arange(1, len(EMPLOYERS) + 1) ** 1.1))
    family = rng.choice(len(FAMILIES), size=n, p=weights(FAMILY_WEIGHTS))
    title_idx = rng.integers(0, 4, size=n)
    level = rng.choice(len(LEVELS), size=n, p=weights(LEVEL_WEIGHTS))
    city = rng.choice(len(CITIES), size=n, p=weights(list(CITIES.values())))
    day = rng.choice(DAYS, size=n, p=day_weights())
    second = rng.integers(0, 86400, size=n)
    combo = rng.integers(0, COMBOS_PER_FAMILY, size=n)

    base = datetime.combine(END_DAY - timedelta(days=DAYS - 1), datetime.min.time(), timezone.utc)
    days = [base.date() + timedelta(days=int(d)) for d in range(DAYS)]
    published = [base + timedelta(days=int(d), seconds=int(s)) for d, s in zip(day, second)]
    families = list(FAMILIES.values())
    cities = list(CITIES)
    ids = range(start, start + n)
    return [
        [f"synthetic:{seed}:{i}" for i in ids],
        ["synthetic"] * n,
        [str(i) for i in ids],
        [EMPLOYERS[e] for e in employer],
        [LEVELS[lv] + families[f][0][t] for lv, f, t in zip(level, family, title_idx)],
        [cities[c] for c in city],
        [families[f][1] for f in family],
        published,
        [days[d] for d in day],
        published,
        [""] * n,
        [combos[f][c] for f, c in zip(family, combo)],
        [1] * n,
        published,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=DEFAULT_ROWS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch", type=int, default=500_000)
    parser.add_argument("--replace", action="store_true", help="empty synthetic_postings and its aggregates first")
    args = parser.parse_args(argv)
    timing = generate(args.rows, args.seed, args.batch, args.replace)
    print(f"SYNTHETIC: {args.rows:,} rows; generate {timing['generate_rows_per_s']:,.0f} rows/s, "
          f"insert {timing['insert_rows_per_s']:,.0f} rows/s, "
          f"end to end {timing['end_to_end_rows_per_s']:,.0f} rows/s; table now holds {timing['table_rows']:,}")
    return 0


def generate(rows: int, seed: int = 42, batch: int = 500_000, replace: bool = False) -> dict:
    """Write the rows; return the seconds and rows/sec of generating and of inserting."""
    from backend.store import COLUMNS, ClickHouseStore

    store = ClickHouseStore(config.CLICKHOUSE_DB)
    if replace:
        # The aggregates too: the materialized views would add the new rows to the old counts.
        for table in ("synthetic_postings", "synthetic_volume_daily", "synthetic_skill_daily"):
            store.client.command(f"TRUNCATE TABLE {table}")
    rng = np.random.default_rng(seed)
    combos = skill_combos(rng)
    gen_s = insert_s = 0.0
    print(f"SYNTHETIC: generating {rows:,} rows (seed {seed}) into {config.CLICKHOUSE_DB}.synthetic_postings")
    for start in range(0, rows, batch):
        n = min(batch, rows - start)
        t0 = time.perf_counter()
        columns = generate_batch(rng, seed, start, n, combos)
        t1 = time.perf_counter()
        store.client.insert("synthetic_postings", columns, column_names=list(COLUMNS), column_oriented=True)
        t2 = time.perf_counter()
        gen_s += t1 - t0
        insert_s += t2 - t1
        print(f"  {start + n:>12,} rows", file=sys.stderr)
    total = store.client.command("SELECT count() FROM synthetic_postings")
    store.close()
    return {"rows": rows, "seed": seed, "batch": batch, "generate_s": gen_s, "insert_s": insert_s,
            "generate_rows_per_s": rows / gen_s, "insert_rows_per_s": rows / insert_s,
            "end_to_end_rows_per_s": rows / (gen_s + insert_s), "table_rows": total}


if __name__ == "__main__":
    raise SystemExit(main())
