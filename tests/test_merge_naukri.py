from pathlib import Path

import pandas as pd
import pytest

from ingest.merge_naukri import (
    COLUMNS, EXPORTS, across_exports, compare, main, numbered, read_export, read_exports, within_export,
)

# Three tiny exports with the real file names (spaces included) and both header styles:
#   Data Science: Acme twice (a whole-row duplicate), a blank row, Globex
#   data analytics: Initech, and the same Acme row again (a duplicate across exports)
#   the third export: Hooli twice, with no link or post-time column
SRC = Path(__file__).parent / "fixtures" / "naukri_exports"


def test_file_names_map_to_source_file_values():
    assert sorted(path.name for path in SRC.iterdir()) == sorted(EXPORTS)
    assert EXPORTS["NaukriData_Data Science.csv"] == "NaukriData_Data_Science"
    assert EXPORTS["NaukriData_data analytics.csv"] == "NaukriData_data_analytics"


def test_both_header_styles_are_mapped():
    third = read_export(SRC / "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data.csv", "third")
    assert list(third.columns) == COLUMNS[1:]
    assert third["job_title"].tolist() == ["BI Developer", "BI Developer"]
    assert (third["post_url"] == "").all() and (third["post_time_relative"] == "").all()
    first = read_export(SRC / "NaukriData_Data Science.csv", "NaukriData_Data_Science")
    assert first["package"].iat[0] == "Not disclosed"
    assert first["locations"].iat[3] == "Bangalore/Bengaluru, Karnataka"


def test_unknown_columns_are_refused(tmp_path):
    path = tmp_path / "odd.csv"
    path.write_text("Job_Titles,Salary\nX,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Salary"):
        read_export(path, "x")


def test_within_export_drops_blank_titles_and_duplicates():
    rows = numbered(within_export(read_exports(SRC)))
    assert list(rows.columns) == COLUMNS
    assert rows["job_row_id"].tolist() == ["1", "2", "3", "4", "5"]
    assert rows["company_name"].tolist() == ["Acme", "Globex", "Initech", "Acme", "Hooli"]
    assert rows["source_file"].value_counts().to_dict() == {
        "NaukriData_Data_Science": 2, "NaukriData_data_analytics": 2,
        "Naukri_Data_Scientist_and_Data_Analytics_Jobs_Data": 1}


def test_across_exports_keeps_the_first_copy_only():
    rows = across_exports(read_exports(SRC))
    assert rows["company_name"].tolist() == ["Acme", "Globex", "Initech", "Hooli"]


def test_compare_finds_an_exact_match_and_a_missing_row():
    rebuilt = numbered(within_export(read_exports(SRC)))
    assert compare(rebuilt, rebuilt.copy())["reproduced"]

    existing = numbered(rebuilt.drop(index=1)[COLUMNS[1:]])     # Globex missing from "existing"
    result = compare(rebuilt, existing)
    assert not result["reproduced"]
    assert result["counts"]["NaukriData_Data_Science"][:2] == (2, 1)
    assert result["matched"] == 4
    assert sum(result["only_rebuilt"].values()) == 1
    assert next(iter(result["only_rebuilt"]))[2] == "Globex"
    assert not result["only_existing"]
    assert result["first_positional_diff"] == 1


def test_compare_flags_a_row_order_difference():
    rebuilt = numbered(within_export(read_exports(SRC)))
    swapped = numbered(rebuilt.iloc[[1, 0, 2, 3, 4]][COLUMNS[1:]])
    result = compare(rebuilt, swapped)
    assert result["matched"] == 5 and not result["only_rebuilt"]
    assert not result["reproduced"]


def test_main_writes_the_rebuilt_file_and_report(tmp_path):
    existing = tmp_path / "merged.csv"
    numbered(within_export(read_exports(SRC))).to_csv(existing, index=False, lineterminator="\n")
    out, report = tmp_path / "rebuilt.csv", tmp_path / "check.txt"
    assert main(["--src", str(SRC), "--out", str(out), "--existing", str(existing),
                 "--report", str(report)]) == 0
    assert out.read_bytes() == existing.read_bytes()
    assert "Verdict: reproduced exactly." in report.read_text(encoding="utf-8")
    assert pd.read_csv(out, dtype=str).shape == (5, len(COLUMNS))


def test_main_never_writes_over_the_merged_file(tmp_path):
    existing = tmp_path / "merged.csv"
    existing.write_text("untouched\n", encoding="utf-8")
    assert main(["--src", str(SRC), "--out", str(existing), "--existing", str(existing),
                 "--report", str(tmp_path / "check.txt")]) == 2
    assert existing.read_text(encoding="utf-8") == "untouched\n"


def test_main_reports_missing_exports(tmp_path):
    existing = tmp_path / "merged.csv"
    existing.write_text("x\n", encoding="utf-8")
    assert main(["--src", str(tmp_path), "--out", str(tmp_path / "o.csv"), "--existing", str(existing),
                 "--report", str(tmp_path / "check.txt")]) == 2
