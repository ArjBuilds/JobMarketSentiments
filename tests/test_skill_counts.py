import csv

import pytest

from process.skill_counts import (
    SKILLS_CSV,
    SkillMatcher,
    SkillsError,
    count_skills,
    read_skills,
    split_case,
)
from jmsa.skills import DATA_SCIENCE_EXPORTS, EXPORTS, HEADLINE_SCOPE

ANALYTICS = EXPORTS[1]


@pytest.fixture(scope="module")
def matcher():
    """The committed skill list: the traps must hold for the real file."""
    return SkillMatcher(read_skills(SKILLS_CSV))


def write_skills(tmp_path, rows):
    path = tmp_path / "skills.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["skill", "type", "synonym"])
        writer.writerows(rows)
    return path


# --- preprocessing --------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Data analysisMachine learning", "Data analysis Machine learning"),
    ("SQLPython", "SQL Python"),
    ("NLPMachine learning", "NLP Machine learning"),
    ("AWSGlue", "AWS Glue"),
    ("C++Front end", "C++ Front end"),
])
def test_case_split_cuts_glued_tags(raw, expected):
    assert split_case(raw) == expected


@pytest.mark.parametrize("token", ["SQL", "AWS", "NLP", "B2C", "C2C"])
def test_case_split_leaves_all_caps_and_digit_tokens_whole(token):
    assert split_case(token) == token


def test_camelcase_skill_names_are_not_cut_in_two(matcher):
    # Without protection the case split would read "Java Script" plus a glued
    # word, and Java would be a false hit.
    assert matcher.extract("JavaScriptsystem design") == {"JavaScript"}


def test_a_known_name_glued_to_the_word_before_is_split_off(matcher):
    assert matcher.extract("Cloud Infrastructurepower biTroubleshooting") == {"Power BI"}


def test_a_name_inside_a_longer_word_is_not_split_off(matcher):
    assert matcher.extract("Operational Excellence") == set()


def test_semicolons_separate_tags(matcher):
    assert matcher.extract("HTML;Javascript") == {"JavaScript"}


# --- the traps ------------------------------------------------------------

def test_java_and_javascript_are_told_apart(matcher):
    assert matcher.extract("JavaScript") == {"JavaScript"}
    assert matcher.extract("JavaScriptJavaSQL") == {"JavaScript", "Java", "SQL"}


@pytest.mark.parametrize("raw", ["R&D", "CRM", "HR", "B2C", "C2C", "Research"])
def test_r_and_c_match_only_as_standalone_tokens(matcher, raw):
    assert not matcher.extract(raw) & {"R", "C"}


def test_r_and_c_standalone_are_found(matcher):
    assert matcher.extract("Python R SQL") == {"Python", "R", "SQL"}
    assert matcher.extract("C Programming") == {"C"}


def test_cpp_and_csharp_are_not_c(matcher):
    assert matcher.extract("C++") == {"C++"}
    assert matcher.extract("C#Python") == {"C#", "Python"}


@pytest.mark.parametrize("raw", ["Google", "good communication", "Go-to-market", "Go live", "Google Cloud"])
def test_go_never_matches_ordinary_words(matcher, raw):
    assert "Go" not in matcher.extract(raw)


def test_golang_is_go(matcher):
    assert matcher.extract("SnowflakeGolangAirflow") == {"Snowflake", "Go", "Airflow"}


# --- synonyms and longest match -------------------------------------------

@pytest.mark.parametrize("raw, skill", [
    ("ML", "Machine Learning"),
    ("NLP", "Natural Language Processing"),
    ("MySQL", "SQL"),
    ("PySpark", "Spark"),
    ("Azure Data Factory", "Azure"),
])
def test_synonyms_map_to_their_skill(matcher, raw, skill):
    assert matcher.extract(raw) == {skill}


def test_longest_match_wins(matcher):
    assert matcher.extract("Advanced Excel") == {"Excel"}
    assert matcher.extract("Power BI") == {"Power BI"}
    assert matcher.extract("NoSQL") == {"NoSQL"}           # not SQL
    assert matcher.extract("Google Analytics") == {"Google Analytics"}


def test_a_skill_counts_once_per_list(matcher):
    assert matcher.extract("SQLSQL ServerMS SQL") == {"SQL"}


# --- skills.csv -----------------------------------------------------------

def test_the_committed_skill_list_has_one_type_per_skill():
    rows = read_skills(SKILLS_CSV)
    types = {}
    for skill, kind, _ in rows:
        assert types.setdefault(skill, kind) == kind, skill
    assert set(types.values()) == {"tool", "method"}


def test_a_skill_with_two_types_is_rejected(tmp_path):
    path = write_skills(tmp_path, [("SQL", "tool", "SQL"), ("SQL", "method", "SQL queries")])
    with pytest.raises(SkillsError, match="one type"):
        read_skills(path)


def test_an_unknown_type_is_rejected(tmp_path):
    with pytest.raises(SkillsError, match="type must be"):
        read_skills(write_skills(tmp_path, [("SQL", "language", "SQL")]))


def test_a_synonym_for_two_skills_is_rejected(tmp_path):
    path = write_skills(tmp_path, [("Machine Learning", "method", "ML"), ("MLOps", "method", "ml")])
    with pytest.raises(SkillsError, match="listed for Machine Learning"):
        read_skills(path)


@pytest.mark.parametrize("synonym", ["Go", "BI"])
def test_banned_synonyms_are_rejected(tmp_path, synonym):
    with pytest.raises(SkillsError, match="can't be a synonym"):
        read_skills(write_skills(tmp_path, [("X", "tool", synonym)]))


def test_a_blank_cell_is_rejected(tmp_path):
    with pytest.raises(SkillsError, match="filled in"):
        read_skills(write_skills(tmp_path, [("SQL", "tool", "")]))


# --- counting -------------------------------------------------------------

def counts(db):
    return {(r["scope"], r["skill"]): (r["type"], r["postings"], r["share"], r["scope_postings"])
            for r in db.execute("SELECT * FROM skill_counts")}


def test_copies_count_once_and_the_data_science_exports_pool(db, write_jobs):
    path = write_jobs([
        {"skills_raw": "SQLPython", "source_file": DATA_SCIENCE_EXPORTS[0]},
        {"skills_raw": "SQLPython", "source_file": DATA_SCIENCE_EXPORTS[0]},   # copy in the same export
        {"skills_raw": "SQLPython", "source_file": DATA_SCIENCE_EXPORTS[1]},   # copy in the other one
        {"skills_raw": "Excel", "source_file": DATA_SCIENCE_EXPORTS[1]},
        {"skills_raw": "Tableau", "source_file": ANALYTICS},
        {"skills_raw": "  ", "source_file": DATA_SCIENCE_EXPORTS[1]},          # empty: not scored
    ])
    count_skills(db, path)
    rows = counts(db)
    assert rows[(HEADLINE_SCOPE, "SQL")] == ("tool", 1, 0.5, 2)
    assert rows[(HEADLINE_SCOPE, "Excel")] == ("tool", 1, 0.5, 2)
    assert (HEADLINE_SCOPE, "Tableau") not in rows       # the analytics export stays out
    assert rows[(DATA_SCIENCE_EXPORTS[0], "SQL")] == ("tool", 1, 1.0, 1)
    assert rows[(DATA_SCIENCE_EXPORTS[1], "SQL")] == ("tool", 1, 0.5, 2)
    assert rows[(ANALYTICS, "Tableau")] == ("tool", 1, 1.0, 1)


def test_lists_with_no_known_skill_still_count_in_the_base(db, write_jobs):
    path = write_jobs([
        {"skills_raw": "SQL", "source_file": DATA_SCIENCE_EXPORTS[0]},
        {"skills_raw": "Cold calling", "source_file": DATA_SCIENCE_EXPORTS[0]},
    ])
    count_skills(db, path)
    assert counts(db)[(HEADLINE_SCOPE, "SQL")] == ("tool", 1, 0.5, 2)


def test_rerunning_gives_the_same_rows(db, write_jobs):
    path = write_jobs([{"skills_raw": "SQLMachine learning", "source_file": DATA_SCIENCE_EXPORTS[0]}])
    count_skills(db, path)
    first = counts(db)
    count_skills(db, path)
    assert counts(db) == first
    assert db.execute("SELECT count(*) FROM skill_counts").fetchone()[0] == len(first)


def test_a_bad_skill_list_writes_nothing(db, write_jobs, tmp_path):
    path = write_jobs([{"skills_raw": "SQL", "source_file": DATA_SCIENCE_EXPORTS[0]}])
    count_skills(db, path)
    before = counts(db)
    with pytest.raises(SkillsError):
        count_skills(db, path, write_skills(tmp_path, [("SQL", "tool", "go")]))
    assert counts(db) == before


def test_an_unknown_export_is_rejected(db, write_jobs):
    path = write_jobs([{"skills_raw": "SQL", "source_file": "SomeOtherExport"}])
    with pytest.raises(SkillsError, match="unknown source_file"):
        count_skills(db, path)
