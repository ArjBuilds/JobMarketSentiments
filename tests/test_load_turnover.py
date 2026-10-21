import csv

import pytest

from ingest.load_turnover import (
    COLUMNS,
    TURNOVER_CSV,
    TurnoverError,
    comparison_lines,
    comparison_pairs,
    load_turnover,
    ranks,
    read_turnover_csv,
    spearman,
)
from jmsa.config import COMPANIES_CSV
from jmsa.turnover import WINDOW_END, WINDOW_PERIOD, WINDOW_START, overlaps_window

# The library fixture holds acme, globex and initech.

ROW = {
    "company_id": "acme", "period": "FY2025-26", "period_start": "2025-04-01", "period_end": "2026-03-31",
    "attrition_pct": "12.5", "basis": "voluntary", "scope": "group", "definition": "Voluntary attrition, LTM",
    "entity": "Acme Ltd", "source_url": "https://acme.example/ar.pdf", "source_ref": "p. 40",
    "retrieved_on": "2026-10-22", "note": "",
}


@pytest.fixture
def write_csv(tmp_path):
    """Write a turnover CSV; each row is a dict of overrides to ROW."""
    def write(rows, header=COLUMNS):
        path = tmp_path / "turnover.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n", extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(ROW | row)
        return path
    return write


def problems(path, ids=frozenset({"acme", "globex", "initech"})):
    with pytest.raises(TurnoverError) as error:
        read_turnover_csv(path, set(ids))
    return error.value.problems


# --- validation --------------------------------------------------------------

def test_a_good_file_loads(write_csv):
    rows = read_turnover_csv(write_csv([{}]), {"acme"})
    assert rows[0]["attrition_pct"] == "12.5"


@pytest.mark.parametrize("override, problem", [
    ({"source_url": ""}, "missing source_url"),
    ({"source_url": "http://acme.example/ar.pdf"}, "must start with https://"),
    ({"source_ref": ""}, "missing source_ref"),
    ({"retrieved_on": ""}, "missing retrieved_on"),
    ({"attrition_pct": "12,5"}, "not a number from 0 to 100"),
    ({"attrition_pct": "12.5%"}, "not a number from 0 to 100"),
    ({"attrition_pct": "-1"}, "not a number from 0 to 100"),
    ({"attrition_pct": "101"}, "not a number from 0 to 100"),
    ({"company_id": "umbrella"}, "unknown company_id"),
    ({"basis": "mostly voluntary"}, "basis"),
    ({"scope": "india"}, "scope"),
    ({"period_end": "31/03/2026"}, "not an ISO date"),
    ({"period_start": "2026-04-01", "period_end": "2026-03-31"}, "before period_start"),
    ({"definition": ""}, "missing definition"),
    ({"entity": ""}, "missing entity"),
])
def test_a_bad_row_is_rejected(write_csv, override, problem):
    assert any(problem in p for p in problems(write_csv([override])))


def test_not_stated_is_a_basis(write_csv):
    assert read_turnover_csv(write_csv([{"basis": "not-stated"}]), {"acme"})


def test_a_duplicate_period_is_rejected(write_csv):
    assert any("second row" in p for p in problems(write_csv([{}, {"period_start": "2025-04-02"}])))


def test_two_rows_ending_the_same_day_are_rejected(write_csv):
    # The latest figure is picked by period_end, so a tie would be ambiguous.
    found = problems(write_csv([{}, {"period": "LTM to Mar 2026"}]))
    assert any("also ends on" in p for p in found)


def test_a_wrong_header_is_rejected(write_csv):
    assert any("header" in p for p in problems(write_csv([{}], header=COLUMNS[:-1])))


def test_every_problem_is_listed_and_nothing_is_written(library, write_csv):
    path = write_csv([{"company_id": "umbrella"}, {"company_id": "globex", "attrition_pct": "abc"}])
    with pytest.raises(TurnoverError) as error:
        load_turnover(library, path)
    assert len(error.value.problems) == 2
    assert library.execute("SELECT count(*) FROM turnover").fetchone()[0] == 0


def test_the_committed_file_is_valid():
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as handle:
        ids = {row["company_id"] for row in csv.DictReader(handle)}
    rows = read_turnover_csv(TURNOVER_CSV, ids)
    assert {r["basis"] for r in rows} <= {"voluntary", "total", "not-stated"}
    # Excluded by the India-subsidiary rule, or replaced by the group figure.
    assert not {"novartis", "oracle", "pfizer"} & {r["company_id"] for r in rows}
    assert all("Siemens Ltd" not in r["entity"] for r in rows)


# --- loading -------------------------------------------------------------------

def add_proxy(db, company_id, n, matched, leaving):
    db.execute(
        "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, proxy_share,"
        " reviews_in_window, reviews_matched, reviews_leaving, reviews_layoffs, definition, entity,"
        " method_note) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, 0, 'd', 'e', 'n')",
        (company_id, WINDOW_PERIOD, WINDOW_START, WINDOW_END, matched / n, n, matched, leaving),
    )


def test_a_load_replaces_published_rows_and_keeps_the_proxy(library, write_csv):
    add_proxy(library, "acme", 100, 5, 3)
    load_turnover(library, write_csv([{"attrition_pct": "20"}]))
    load_turnover(library, write_csv([{"attrition_pct": "13"}]))
    published = library.execute("SELECT attrition_pct, attrition_text FROM turnover WHERE is_proxy = 0").fetchall()
    assert [tuple(r) for r in published] == [(13.0, "13")]
    assert library.execute("SELECT count(*) FROM turnover WHERE is_proxy = 1").fetchone()[0] == 1


def test_the_value_is_kept_as_printed(library, write_csv):
    load_turnover(library, write_csv([{"attrition_pct": "8.80"}]))
    assert library.execute("SELECT attrition_text FROM turnover").fetchone()[0] == "8.80"


# --- the proxy comparison ----------------------------------------------------------

def test_overlap_with_the_proxy_window():
    assert overlaps_window("2022-04-01", "2023-03-31")
    assert overlaps_window("2022-09-01", "2023-08-31")       # Accenture's fiscal 2023
    assert overlaps_window("2020-04-01", "2021-04-01")       # touches the first day
    assert not overlaps_window("2025-04-01", "2026-03-31")
    assert not overlaps_window(None, "2023-03-31")


def test_ranks_average_ties():
    assert ranks([10, 30, 20, 20]) == [1, 4, 2.5, 2.5]


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1)
    assert spearman([1, 2], [1, 2]) is None                # too few pairs
    assert spearman([1, 2, 3], [5, 5, 5]) is None          # no spread on one side


def test_pairs_use_the_overlapping_figure_and_skip_hidden_proxies(library, write_csv):
    library.execute("UPDATE companies SET publishes_attrition = 'yes' WHERE company_id = 'acme'")
    load_turnover(library, write_csv([
        {},                                                                   # latest: not in the window
        {"period": "FY2022-23", "period_start": "2022-04-01", "period_end": "2023-03-31", "attrition_pct": "20.1"},
        {"company_id": "globex", "period_start": "2022-04-01", "period_end": "2023-03-31", "basis": "not-stated"},
        {"company_id": "initech", "period_start": "2022-04-01", "period_end": "2023-03-31"},
    ]))
    add_proxy(library, "acme", 1000, 61, 40)
    add_proxy(library, "globex", 500, 10, 10)
    add_proxy(library, "initech", 19, 2, 2)                                   # hidden: under 20 reviews
    pairs = comparison_pairs(library)
    assert [p["company_id"] for p in pairs] == ["acme", "globex"]
    acme = pairs[0]
    assert (acme["attrition"], acme["proxy"], acme["leaving"], acme["it_major"]) == (20.1, 6.1, 4.0, True)


def test_comparison_reports_n_basis_mix_and_the_pre_merger_caveat():
    pairs = [
        {"company_id": f"c{i}", "attrition": a, "period": "FY2022-23", "basis": b, "proxy": p, "leaving": p,
         "it_major": i < 3, "pre_merger": i == 0}
        for i, (a, p, b) in enumerate([(20, 6, "voluntary"), (15, 4, "not-stated"), (10, 2, "voluntary"),
                                       (12, 5, "not-stated")])
    ]
    text = "\n".join(comparison_lines(pairs))
    assert "IT majors (publishes_attrition = yes): n = 3; basis mix: not-stated 1, voluntary 2" in text
    assert "All companies with both: n = 4" in text
    assert "proxy total vs published:            +1.00" in text
    assert "c0: the proxy comes from pre-merger Mindtree reviews" in text


def test_comparison_says_when_there_is_nothing_to_compare():
    assert "Run python -m process.turnover_proxy first." in "\n".join(comparison_lines([]))
