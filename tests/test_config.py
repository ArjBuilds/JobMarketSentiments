import os
import subprocess
import sys
from pathlib import Path

from jmsa.config import DATA_DIR, REPO_ROOT


def test_jmsa_db_path_overrides_the_default_database(tmp_path):
    # DB_PATH is read once, when jmsa.config is first imported, so the check
    # runs in a fresh interpreter with the variable set, exactly like
    # `JMSA_DB_PATH=data/sample.db python -m ...` in Git Bash.
    sample = tmp_path / "sample.db"
    result = subprocess.run(
        [sys.executable, "-c", "from jmsa.config import DB_PATH; print(DB_PATH)"],
        cwd=REPO_ROOT, env={**os.environ, "JMSA_DB_PATH": str(sample)},
        capture_output=True, text=True, check=True,
    )
    printed = Path(result.stdout.strip())
    assert printed == sample
    assert printed != DATA_DIR / "jmsa.db"
