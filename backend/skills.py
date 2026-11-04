"""Skill tags for a Greenhouse posting, from the skill list in data/skills.csv.

Greenhouse's content field is HTML, escaped once more as text
("&lt;p&gt;Python&lt;/p&gt;"). extract_skills unescapes it, drops the tags,
splits the rest into lowercase tokens and looks up every run of 1..N tokens
against the synonyms, longest first, so "SQL Server" is one SQL and not
SQL plus a stray "server". Each skill counts once per posting.

Single-letter synonyms (R, C) are left out: in free text they match "R&D"
and "C-suite" far more often than the languages.
"""

from __future__ import annotations

import csv
import html
import re
from functools import lru_cache
from pathlib import Path

SKILLS_CSV = Path(__file__).resolve().parents[1] / "data" / "skills.csv"

TAG = re.compile(r"<[^>]*>")
# A token is letters/digits plus the symbols that belong inside a skill name
# (c++, c#, node.js); a trailing full stop ends the token, so "Python." is Python.
TOKEN = re.compile(r"[a-z0-9+#]+(?:\.[a-z0-9+#]+)*")


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.lower())


@lru_cache(maxsize=1)
def synonym_table(path: str = str(SKILLS_CSV)) -> tuple[dict[tuple[str, ...], str], int]:
    """{token tuple: skill} and the longest synonym in tokens."""
    table: dict[tuple[str, ...], str] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = tuple(tokens(row["synonym"]))
            if key and len("".join(key)) > 1:
                table[key] = row["skill"]
    return table, max(len(k) for k in table)


@lru_cache(maxsize=1)
def first_tokens() -> frozenset[str]:
    """Every token a synonym can start with: about 140 of them."""
    return frozenset(key[0] for key in synonym_table()[0])


def match_tokens(toks: list[str]) -> list[str]:
    """Skills named in a token list, longest synonym first, each once, sorted.

    The profiled hot spot of the worker (docs/BACKEND.md). Almost no token
    starts a skill name, so one set lookup per token, done in a list
    comprehension, finds the few places worth trying; only there are the
    1..N-token tuples built and looked up. Same result as
    match_tokens_reference, which tries every width at every token.
    """
    table, longest = synonym_table()
    starts = first_tokens()
    found: set[str] = set()
    n = len(toks)
    free = 0  # tokens before this belong to a match already made
    for i in [i for i, t in enumerate(toks) if t in starts]:
        if i < free:
            continue
        for width in range(min(longest, n - i), 0, -1):
            skill = table.get(tuple(toks[i:i + width]))
            if skill:
                found.add(skill)
                free = i + width
                break
    return sorted(found)


def match_tokens_reference(toks: list[str]) -> list[str]:
    """The original match_tokens, kept as the benchmark's "before" and its correctness check."""
    table, longest = synonym_table()
    found: set[str] = set()
    i, n = 0, len(toks)
    while i < n:
        for width in range(min(longest, n - i), 0, -1):
            skill = table.get(tuple(toks[i:i + width]))
            if skill:
                found.add(skill)
                i += width
                break
        else:
            i += 1
    return sorted(found)


def extract_skills(content: str | None) -> list[str]:
    """Skills named in a posting's escaped-HTML content."""
    if not content:
        return []
    text = TAG.sub(" ", html.unescape(html.unescape(content)))
    return match_tokens(tokens(text))
