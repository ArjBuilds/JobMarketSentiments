"""Count the data-role skills the Naukri postings list, market-wide (F7).

Run with:  python -m process.skill_counts [--check N] [--seed S]

Reads skills_raw from data/raw/naukri_jobs_merged.csv and the skill list in
data/skills.csv, and replaces skill_counts. Nothing else needs loading first.

Why market-wide: the postings' columns are misaligned row by row, so a row's
skills_raw belongs to some other posting. Skills can't be tied to a company
or a title, only counted over a whole export. The headline scope pools the two
data-science exports (87-91% data-role titles); the analytics export (38%) is
counted on its own for comparison only.

Why each distinct string counts once: listings were scraped repeatedly, so
the same skills_raw string was copied onto many rows (one list 187 times).
Different postings sharing an identical ordered list of about eight tags is
implausible, so copies are collapsed, pooled across both data-science
exports, which overlap heavily. Counts are therefore a lower bound.

How a skills_raw string is read. Naukri glues its tags together with no
separator ("Data analysisMachine learningSQLPython"), so the string is
prepared in four steps before matching:

    1. separators   ";" and "," become spaces.
    2. unglue       a camelCase skill name from skills.csv (JavaScript, PyTorch,
                    NoSQL) is lowercased and padded with spaces, so step 3
                    can't cut it in two. A known name of 5+ letters glued to
                    the letter before it ("Infrastructurepower bi") gets a
                    space in front, unless a lowercase letter follows it
                    (so "Excellence" never yields Excel).
    3. case split   a space goes between a lowercase letter (or ")", "+", "#")
                    and a capital, and before the last capital of a run
                    that starts a new word: "SQLPython" -> "SQL Python". A run
                    of capitals on its own (SQL, AWS, NLP) is never split.
    4. match        spaCy's PhraseMatcher on a blank English tokenizer (no
                    model download), comparing lowercase tokens. Where
                    matches overlap the longest wins, so "Advanced Excel"
                    is one Excel and "JavaScript" is never Java. Each skill
                    counts once per list.

Tags glued in all lowercase ("managementsql") or after an acronym ("GCPdata")
are missed; the hand check in --check measures how often.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import spacy
from spacy.matcher import PhraseMatcher
from spacy.tokens import Span
from spacy.util import filter_spans

from ingest.load_jobs import NAUKRI_CSV
from jmsa.config import DATA_DIR, RAW_DIR
from jmsa.db import apply_schema, get_conn
from jmsa.display import plural
from jmsa.skills import DATA_SCIENCE_EXPORTS, EXPORTS, HEADLINE_SCOPE, TOP_N, TYPES

SKILLS_CSV = DATA_DIR / "skills.csv"
REPORT_PATH = RAW_DIR / "skill_counts_report.txt"
CHECK_PATH = RAW_DIR / "skill_check_sample.txt"
CHECK_SEED = 2023

SKILLS_HEADER = ["skill", "type", "synonym"]

# Synonyms that would match ordinary words, so skills.csv may never list them.
BANNED_SYNONYMS = {
    "go": "matches go-to-market and go-live; use Golang",
    "bi": "matches the BI of a glued 'power bi'; use Business intelligence",
}

# A name glued to the letter before it is split off only if it has at least
# this many letters: short names (SQL, AWS, R) occur inside ordinary words.
MIN_GLUE_LETTERS = 5

SEPARATORS = re.compile(r"[;,]")
CASE_SPLITS = (
    re.compile(r"(?<=[a-z)+#])(?=[A-Z])"),     # "learningSQL", "C++Front"
    re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])"),   # "SQLPython", "NLPMachine"
)

INSERT_SQL = """
    INSERT INTO skill_counts (scope, skill, type, postings, share, scope_postings)
    VALUES (?, ?, ?, ?, ?, ?)
"""


class SkillsError(ValueError):
    """The inputs failed a check; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def split_case(text: str) -> str:
    """Put a space at each case boundary: 'Machine learningSQLPython' -> 'Machine learning SQL Python'."""
    for rule in CASE_SPLITS:
        text = rule.sub(" ", text)
    return text


def read_skills(path: str | Path = SKILLS_CSV) -> list[tuple[str, str, str]]:
    """(skill, type, synonym) rows from skills.csv, checked before anything is matched."""
    problems: list[str] = []
    rows: list[tuple[str, str, str]] = []
    types: dict[str, str] = {}
    seen: dict[str, str] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SKILLS_HEADER:
            raise SkillsError([f"{path}: header must be {','.join(SKILLS_HEADER)}, not {reader.fieldnames}"])
        for line, row in enumerate(reader, start=2):
            skill, kind, synonym = (row[c].strip() for c in SKILLS_HEADER)
            key = " ".join(synonym.lower().split())
            if not (skill and kind and synonym):
                problems.append(f"line {line}: skill, type and synonym must all be filled in")
            elif kind not in TYPES:
                problems.append(f"line {line}: type must be {' or '.join(TYPES)}, not {kind!r} ({skill})")
            elif types.setdefault(skill, kind) != kind:
                problems.append(f"line {line}: {skill} is both {types[skill]} and {kind}; a skill has one type")
            elif key in BANNED_SYNONYMS:
                problems.append(f"line {line}: {synonym!r} can't be a synonym: {BANNED_SYNONYMS[key]}")
            elif key in seen:
                problems.append(f"line {line}: synonym {synonym!r} is listed for {seen[key]} already")
            else:
                seen[key] = skill
                rows.append((skill, kind, synonym))
    if problems:
        raise SkillsError([f"{path}: {p}" for p in problems])
    return rows


class SkillMatcher:
    """Finds skills.csv's skills in a skills_raw string; see the module docstring."""

    def __init__(self, rows: list[tuple[str, str, str]]):
        self.types = {skill: kind for skill, kind, _ in rows}
        self.nlp = spacy.blank("en")
        self.matcher = PhraseMatcher(self.nlp.vocab, attr="LOWER")
        patterns: dict[str, list] = {}
        for skill, _, synonym in rows:
            patterns.setdefault(skill, []).append(self.nlp.make_doc(synonym))
        for skill, docs in patterns.items():
            self.matcher.add(skill, docs)

        synonyms = [synonym for _, _, synonym in rows]
        # Names the case split would cut in two ("JavaScript" -> "Java Script").
        self.protected = {s.lower() for s in synonyms if split_case(s) != s}
        names = [s for s in synonyms
                 if s.lower() in self.protected or sum(ch.isalpha() for ch in s) >= MIN_GLUE_LETTERS]
        # Longest first, so the scan prefers "pyspark" to "spark" at the same place.
        names.sort(key=len, reverse=True)
        self.names = re.compile("|".join(re.escape(name) for name in names), re.IGNORECASE)

    def unglue(self, text: str) -> str:
        """Step 2: protect camelCase names, and split known names off the word they're glued to."""
        pieces: list[str] = []
        last = 0
        for found in self.names.finditer(text):
            start, end = found.span()
            if found.group(0).lower() in self.protected:
                pieces += [text[last:start], " ", found.group(0).lower(), " "]
                last = end
            elif start > 0 and text[start - 1].isalpha() and not (end < len(text) and text[end].islower()):
                pieces += [text[last:start], " "]
                last = start
        pieces.append(text[last:])
        return "".join(pieces)

    def prepare(self, raw: str) -> str:
        return split_case(self.unglue(SEPARATORS.sub(" ", raw)))

    def extract(self, raw: str) -> set[str]:
        """The skills a skills_raw string lists, each once."""
        doc = self.nlp.make_doc(self.prepare(raw))
        spans = [Span(doc, start, end, label=match_id) for match_id, start, end in self.matcher(doc)]
        return {span.label_ for span in filter_spans(spans)}


def read_postings(path: str | Path = NAUKRI_CSV) -> dict[str, list[str]]:
    """export -> its non-empty skills_raw strings, in file order, copies included."""
    lists: dict[str, list[str]] = {export: [] for export in EXPORTS}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in ("skills_raw", "source_file") if c not in (reader.fieldnames or [])]
        if missing:
            raise SkillsError([f"{path}: missing columns {missing}"])
        for row in reader:
            if row["source_file"] not in lists:
                raise SkillsError([f"{path}: unknown source_file {row['source_file']!r}"])
            if row["skills_raw"].strip():
                lists[row["source_file"]].append(row["skills_raw"].strip())
    return lists


def scopes(lists: dict[str, list[str]]) -> dict[str, list[str]]:
    """scope -> its distinct skill lists. Each export on its own, and the
    data-science exports pooled, with copies across the two collapsed too."""
    pooled = [s for export in DATA_SCIENCE_EXPORTS for s in lists[export]]
    distinct = {export: list(dict.fromkeys(strings)) for export, strings in lists.items()}
    return {HEADLINE_SCOPE: list(dict.fromkeys(pooled)), **distinct}


def tally(strings: list[str], found: dict[str, set[str]]) -> Counter:
    counts: Counter = Counter()
    for s in strings:
        counts.update(found[s])
    return counts


def count_skills(
    conn: sqlite3.Connection,
    postings_path: str | Path = NAUKRI_CSV,
    skills_path: str | Path = SKILLS_CSV,
) -> dict:
    """Replace skill_counts; return the figures for the report."""
    matcher = SkillMatcher(read_skills(skills_path))
    lists = read_postings(postings_path)
    found = {s: matcher.extract(s) for strings in lists.values() for s in set(strings)}
    by_scope = scopes(lists)

    rows = []
    for scope, strings in by_scope.items():
        for skill, n in sorted(tally(strings, found).items()):
            rows.append((scope, skill, matcher.types[skill], n, n / len(strings), len(strings)))

    # One transaction: a failure leaves the previous counts in place.
    with conn:
        conn.execute("DELETE FROM skill_counts")
        conn.executemany(INSERT_SQL, rows)

    pooled_rows = [s for export in DATA_SCIENCE_EXPORTS for s in lists[export]]
    return {
        "matcher": matcher,
        "lists": lists,
        "scopes": by_scope,
        "found": found,
        "pooled_rows": pooled_rows,
        "stored": len(rows),
    }


def top_line(counts: Counter, n_lists: int, types: dict[str, str], kind: str | None) -> str:
    ranked = sorted(((n, skill) for skill, n in counts.items() if kind in (None, types[skill])),
                    key=lambda pair: (-pair[0], pair[1]))[:TOP_N]
    return "; ".join(f"{skill} {n / n_lists:.1%}" for n, skill in ranked) or "none"


def build_report(result: dict) -> str:
    lines: list[str] = []
    add = lines.append
    types, found = result["matcher"].types, result["found"]
    kinds = Counter(types.values())
    add(f"Skill list: {len(types)} skills ({kinds['tool']} tools, {kinds['method']} methods) from {SKILLS_CSV.name}")
    add("Share = distinct skill lists that list the skill / distinct non-empty skill lists in the scope.")
    add("")

    add("Per export (each export's distinct skill lists counted once)")
    for export in EXPORTS:
        rows, distinct = result["lists"][export], result["scopes"][export]
        if not distinct:
            add(f"  {export}: no skill lists")
            continue
        counts = tally(distinct, found)
        none = sum(1 for s in distinct if not found[s])
        add(f"  {export}: {len(rows):,} rows with skills -> {len(distinct):,} distinct lists; "
            f"no listed skill found in {none / len(distinct):.0%}")
        add(f"    tools:   {top_line(counts, len(distinct), types, 'tool')}")
        add(f"    methods: {top_line(counts, len(distinct), types, 'method')}")
    add("")

    pooled, distinct = result["pooled_rows"], result["scopes"][HEADLINE_SCOPE]
    add(f"Headline scope {HEADLINE_SCOPE!r}: {' + '.join(DATA_SCIENCE_EXPORTS)}, pooled")
    if distinct:
        none = sum(1 for s in distinct if not found[s])
        add(f"  {len(pooled):,} rows -> {len(distinct):,} distinct lists "
            f"({len(pooled) - len(distinct):,} copies removed); no listed skill found in {none / len(distinct):.0%}")
        deduped, copied = tally(distinct, found), tally(pooled, found)
        for title, kind in (("tools", "tool"), ("methods", "method"), ("all skills", None)):
            add(f"  Top {TOP_N} {title}")
            add(f"    distinct lists:    {top_line(deduped, len(distinct), types, kind)}")
            add(f"    rows (no dedupe):  {top_line(copied, len(pooled), types, kind)}")
    add("")
    add(f"Rows stored in skill_counts: {result['stored']:,}")
    return "\n".join(lines)


def write_check(path: Path, n: int, seed: int, postings_path: str | Path, skills_path: str | Path) -> int:
    """Write n seeded random distinct headline lists with what was matched, for a hand check."""
    matcher = SkillMatcher(read_skills(skills_path))
    distinct = scopes(read_postings(postings_path))[HEADLINE_SCOPE]
    sample = random.Random(seed).sample(distinct, min(n, len(distinct)))
    lines = [f"Hand check: {len(sample)} distinct skill lists from the {HEADLINE_SCOPE!r} scope, seed {seed}.",
             "For each, mark found skills that are wrong (precision) and skills.csv skills present",
             "in the raw text but not found (recall).", ""]
    for number, raw in enumerate(sample, start=1):
        lines += [f"{number:>2}. raw:      {raw}",
                  f"    prepared: {matcher.prepare(raw)}",
                  f"    found:    {', '.join(sorted(matcher.extract(raw))) or '(none)'}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(sample)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m process.skill_counts")
    parser.add_argument("--csv", type=Path, default=NAUKRI_CSV, help="postings CSV to read")
    parser.add_argument("--skills", type=Path, default=SKILLS_CSV, help="skill list to match")
    parser.add_argument("--check", type=int, metavar="N",
                        help=f"write N random lists with their matches to {CHECK_PATH.name}; the database is not touched")
    parser.add_argument("--seed", type=int, default=CHECK_SEED, help="random seed for --check")
    args = parser.parse_args(argv)

    try:
        if args.check:
            n = write_check(CHECK_PATH, args.check, args.seed, args.csv, args.skills)
            print(f"{plural(n, 'skill list')} written to {CHECK_PATH} for a hand check; the database was not touched")
            return 0
        conn = get_conn()
        try:
            apply_schema(conn)
            result = count_skills(conn, args.csv, args.skills)
        finally:
            conn.close()
    except SkillsError as error:
        print("not counted, nothing written", file=sys.stderr)
        for problem in error.problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    report = build_report(result)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nReport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
