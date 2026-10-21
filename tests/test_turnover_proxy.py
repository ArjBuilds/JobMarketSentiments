import csv

import pytest

from process.turnover_proxy import (
    KeywordsError,
    Sampler,
    build_check,
    compile_keywords,
    compute,
    keywords_to_check,
    kinds_mentioned,
    proxy_rows,
    read_keywords,
    save,
)
from jmsa.turnover import WINDOW_PERIOD

# The library fixture holds acme, globex and initech.

KEYWORDS = {"leaving": ["attrition", "turnover", "people leaving", "quit"],
            "layoffs": ["layoffs", "lay off", "lay offs", "laid off", "fired"]}


@pytest.fixture
def patterns():
    return compile_keywords(KEYWORDS)


def mentions(patterns, headline=None, cons=None, pros=None):
    return kinds_mentioned({"headline": headline, "cons": cons, "pros": pros}, patterns[0])


def add_reviews(db, company_id, n, date="2022-06-01", cons="Long hours", headline="Fine place",
                pros="Good pay", pre_merger=0, start=0):
    db.executemany(
        "INSERT INTO reviews (review_id, company_id, review_date, headline, pros, cons, is_pre_merger)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(f"{company_id}-{start + i}", company_id, date, headline, pros, cons, pre_merger) for i in range(n)],
    )


def run(db, patterns, companies=None):
    result = compute(db, *patterns, companies)
    save(db, proxy_rows(db, result["companies"]), companies)
    return result


def proxy(db, company_id):
    return db.execute("SELECT * FROM turnover WHERE company_id = ? AND is_proxy = 1", (company_id,)).fetchone()


# --- keyword matching ------------------------------------------------------

def test_whole_words_only(patterns):
    assert mentions(patterns, cons="High turnover in my team") == {"leaving"}
    assert mentions(patterns, cons="Turnovers are a pastry") == set()
    assert mentions(patterns, cons="He quietly quit") == {"leaving"}
    assert mentions(patterns, cons="The quite long commute") == set()


def test_any_case_and_a_hyphen_matches_a_space(patterns):
    assert mentions(patterns, cons="ATTRITION is high") == {"leaving"}
    assert mentions(patterns, cons="Constant lay-offs") == {"layoffs"}
    assert mentions(patterns, cons="lay offs every year") == {"layoffs"}


def test_headline_and_cons_count_but_pros_do_not(patterns):
    assert mentions(patterns, headline="People leaving in droves") == {"leaving"}
    assert mentions(patterns, pros="No layoffs during covid, low attrition") == set()


def test_both_kinds_can_match_one_review(patterns):
    assert mentions(patterns, cons="Layoffs and high attrition") == {"leaving", "layoffs"}


def test_excluded_words_do_not_match_with_the_committed_keywords():
    by_kind, _ = compile_keywords(read_keywords())
    for text in ("Good leave policy", "No leaves in the first year", "Felt left out",
                 "Job security is low", "Long notice period", "Can switch projects"):
        assert kinds_mentioned({"headline": None, "cons": text}, by_kind) == set(), text


# --- the keywords file -----------------------------------------------------

def write_keywords(tmp_path, rows, header=("kind", "keyword")):
    path = tmp_path / "keywords.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_the_committed_keywords_file_is_valid():
    keywords = read_keywords()
    assert set(keywords) == {"leaving", "layoffs"}
    assert "leave" not in keywords["leaving"] and "left" not in keywords["leaving"]


@pytest.mark.parametrize("rows, header, problem", [
    ([("leaving", "quit"), ("layoffs", "fired")], ("type", "keyword"), "header"),
    ([("leaving", "quit"), ("exits", "fired")], ("kind", "keyword"), "not one of"),
    ([("leaving", "quit"), ("layoffs", " ")], ("kind", "keyword"), "empty keyword"),
    ([("leaving", "quit"), ("layoffs", "Quit")], ("kind", "keyword"), "listed twice"),
    ([("leaving", "quit")], ("kind", "keyword"), "'layoffs' has no keywords"),
])
def test_bad_keyword_files_are_rejected(tmp_path, rows, header, problem):
    with pytest.raises(KeywordsError) as error:
        read_keywords(write_keywords(tmp_path, rows, header))
    assert any(problem in p for p in error.value.problems)


# --- the window and the counts ---------------------------------------------

def test_the_window_includes_its_ends_and_excludes_outside_and_undated(library, patterns):
    for number, date in enumerate(["2021-03-31", "2021-04-01", "2023-03-31", "2023-04-01", None]):
        add_reviews(library, "acme", 1, date=date, cons="High attrition", start=number)
    run(library, patterns)
    row = proxy(library, "acme")
    assert (row["reviews_in_window"], row["reviews_matched"]) == (2, 2)
    assert row["period"] == WINDOW_PERIOD


def test_counts_and_split(library, patterns):
    add_reviews(library, "acme", 6, cons="Long hours")
    add_reviews(library, "acme", 2, cons="High attrition", start=10)
    add_reviews(library, "acme", 1, cons="Layoffs", start=20)
    add_reviews(library, "acme", 1, cons="Layoffs then attrition", start=30)
    run(library, patterns)
    row = proxy(library, "acme")
    assert (row["reviews_in_window"], row["reviews_matched"], row["reviews_leaving"], row["reviews_layoffs"]) \
        == (10, 4, 3, 2)
    assert row["proxy_share"] == pytest.approx(0.4)
    assert row["attrition_pct"] is None


def test_a_company_without_reviews_in_the_window_gets_no_row(library, patterns):
    add_reviews(library, "acme", 5, date="2019-01-01")
    run(library, patterns)
    assert proxy(library, "acme") is None


def test_under_20_reviews_is_stored_with_its_count(library, patterns):
    # Hidden when shown (jmsa.turnover), but stored, so the count can be shown.
    add_reviews(library, "acme", 19)
    run(library, patterns)
    assert proxy(library, "acme")["reviews_in_window"] == 19


def test_pre_merger_reviews_name_mindtree_as_the_entity(library, patterns):
    add_reviews(library, "acme", 3, pre_merger=1)
    add_reviews(library, "globex", 3)
    run(library, patterns)
    assert proxy(library, "acme")["entity"] == "Glassdoor reviews of Mindtree (pre-merger)"
    assert proxy(library, "globex")["entity"] == "Glassdoor reviews of Globex"


# --- storage ---------------------------------------------------------------

def add_published(db, company_id="acme"):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_end, attrition_pct, attrition_text, basis,"
        " scope, definition, entity, source_url, source_ref, retrieved_on) VALUES (?, 0, 'FY2024-25',"
        " '2025-03-31', 12.5, '12.5', 'voluntary', 'group', 'voluntary', 'Acme Ltd',"
        " 'https://acme.example/ar.pdf', 'p. 40', '2026-10-22')",
        (company_id,),
    )


def test_a_rerun_replaces_proxy_rows_and_keeps_published_ones(library, patterns):
    add_published(library)
    add_reviews(library, "acme", 4, cons="High attrition")
    run(library, patterns)
    add_reviews(library, "acme", 4, start=10)
    run(library, patterns)
    assert proxy(library, "acme")["reviews_in_window"] == 8
    assert library.execute("SELECT count(*) FROM turnover WHERE is_proxy = 0").fetchone()[0] == 1


def test_a_company_run_replaces_only_that_company(library, patterns):
    add_reviews(library, "acme", 4)
    add_reviews(library, "globex", 4)
    run(library, patterns)
    run(library, patterns, companies=["globex"])
    assert proxy(library, "acme") is not None and proxy(library, "globex") is not None


# --- the hand-check sample -------------------------------------------------

def test_check_sample_covers_matched_unmatched_and_keywords(library, patterns):
    add_reviews(library, "acme", 30, cons="High turnover")
    add_reviews(library, "acme", 30, cons="Good leave policy but long hours", start=100)
    sampler = Sampler(10)
    compute(library, *patterns, sampler=sampler)
    assert len(sampler.pools["matched"]) == 10 and len(sampler.pools["unmatched"]) == 10
    assert len(sampler.pools["near_miss"]) == 5
    assert len(sampler.pools["keyword:turnover"]) == 5
    to_check = keywords_to_check(sampler, KEYWORDS)
    assert "turnover" in to_check and "fired" in to_check      # always checked, even with no hits
    text = build_check(sampler, *patterns, to_check)
    assert "[[turnover]]" in text and "Keyword 'fired' (0 reviews): 0 sampled" in text


def test_check_sample_is_reproducible(library, patterns):
    add_reviews(library, "acme", 50, cons="High turnover")
    first, second = Sampler(5), Sampler(5)
    compute(library, *patterns, sampler=first)
    compute(library, *patterns, sampler=second)
    assert first.pools == second.pools
