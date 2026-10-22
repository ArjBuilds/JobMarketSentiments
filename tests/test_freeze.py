import importlib.util
from pathlib import Path

# scripts/ isn't a package, so the script is loaded from its path.
spec = importlib.util.spec_from_file_location(
    "freeze", Path(__file__).resolve().parents[1] / "scripts" / "freeze.py")
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)


def test_table_counts_cover_every_table(library):
    counts = freeze.table_counts(library)
    assert set(counts) == {"companies", "reviews", "review_summary", "turnover", "articles",
                           "news_fetches", "jobs", "job_skills", "skill_counts"}
    assert counts["companies"] == 3 and counts["reviews"] == 0


def test_freeze_text(library):
    database = ["jmsa.db", "1,024", "`abc`"]
    files = [["data/raw/naukri_jobs_merged.csv", "missing", "missing"]]
    text = freeze.freeze_text(library, "2026-10-22", "1e67f4f", False, database, files)
    assert "Frozen on **2026-10-22** at git commit `1e67f4f`." in text
    assert "| companies | 3 |" in text
    assert "| data/raw/naukri_jobs_merged.csv | missing | missing |" in text
    assert "not available: the file records no snapshot date" in text   # the ratings source
    assert "Warning" not in text
    assert "Warning" in freeze.freeze_text(library, "2026-10-22", "1e67f4f", True, database, files)


def test_input_files_list_the_raw_inputs_and_committed_csvs():
    names = [path.name for path in freeze.input_files()]
    assert names[:4] == freeze.RAW_INPUTS
    assert "companies.csv" in names and "turnover.csv" in names
