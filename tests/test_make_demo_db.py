"""scripts/make_demo_db.py: the committed demo copy keeps what pages read and
drops the review text and cached GNews payloads."""

import importlib.util
import os
import subprocess
import sys

from jmsa.config import REPO_ROOT
from jmsa.db import get_conn, init_db

spec = importlib.util.spec_from_file_location("make_demo_db", REPO_ROOT / "scripts" / "make_demo_db.py")
make_demo_db = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_demo_db)


def test_the_demo_copy_drops_review_text_and_news_payloads_but_keeps_the_rest(tmp_path):
    source, target = tmp_path / "full.db", tmp_path / "demo.db"
    init_db(source)
    conn = get_conn(source)
    conn.execute("INSERT INTO companies (company_id, name, sector) VALUES ('acme', 'Acme', 'IT Services')")
    conn.execute("INSERT INTO reviews (review_id, company_id, headline) VALUES ('gd-1', 'acme', 'Great place')")
    conn.execute("INSERT INTO review_summary (company_id, period, review_count, avg_compound, pre_merger_count)"
                 " VALUES ('acme', 'all', 500, 0.2, 0)")
    conn.execute("INSERT INTO articles (article_id, company_id, title, summary, sentiment_label)"
                 " VALUES ('acme:1', 'acme', 'Acme hires', 'A long description', 'positive')")
    conn.execute("INSERT INTO news_fetches (company_id, fetched_at, query, window_from, returned,"
                 " dropped_irrelevant, dropped_duplicate, kept, response_json)"
                 " VALUES ('acme', '2026-10-21T09:30:00Z', 'q', '2026-09-21T09:30:00Z', 1, 0, 0, 1, '{\"articles\": []}')")
    conn.commit()
    conn.close()

    make_demo_db.make_demo(source, target)

    demo = get_conn(target)
    assert demo.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 0
    assert demo.execute("SELECT review_count FROM review_summary").fetchone()[0] == 500
    assert tuple(demo.execute("SELECT title, summary FROM articles").fetchone()) == ("Acme hires", None)
    assert demo.execute("SELECT response_json, fetched_at FROM news_fetches").fetchone()[0] == "{}"
    demo.close()
    # The source is only read.
    full = get_conn(source)
    assert full.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1
    full.close()


def test_the_script_refuses_to_overwrite_the_database_it_reads(tmp_path):
    result = subprocess.run(
        [sys.executable, "scripts/make_demo_db.py"], cwd=REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "JMSA_DB_PATH": str(REPO_ROOT / "data" / "demo.db")},
    )
    assert result.returncode == 1
    assert "points at the demo database itself" in result.stderr
