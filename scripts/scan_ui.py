"""Look for raw values leaking into the dashboard, against the real database.

Run from the repo root:  python scripts/scan_ui.py

Opens every page headlessly through the router (app/app.py), then the
Company page for every company and Compare for a few sets, and searches
everything drawn (titles, text, captions, metrics, buttons, table headers
and cells) for what should never be shown: None, nan, snake_case names
(raw column names), lowercase "not available" and Python reprs. Links are
skipped, because URLs may hold underscores. Exits 1 if anything is found.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Run as a script, so the repo root isn't on sys.path yet (as in app/app.py).
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from app.ui.components import PAGES  # noqa: E402
from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402

APP = str(ROOT / "app" / "app.py")
BAD = re.compile(r"\bNone\b|\bnan\b|\bNaN\b|not available|\{'|\[\]|\b[a-z]+_[a-z_]+\b")
LINK = re.compile(r"\]\([^)]*\)|https?://\S+")
# Lowercase "not available" the dashboard means to show: the Company page's
# disabled careers button, which reads as a sentence, not a missing value.
ALLOWED = ("Careers page not available",)
NO_REVIEWS = ["atlassian", "workday", "jpmorgan-chase", "hdfc-bank"]


def texts(app: AppTest) -> list[tuple[str, str]]:
    """(kind, text) for everything the page drew."""
    out = []
    for kind in ("title", "header", "subheader", "markdown", "caption", "info", "warning", "error"):
        out += [(kind, element.value) for element in getattr(app, kind)]
    out += [("metric", f"{m.label}: {m.value} | {m.help}") for m in app.metric]
    out += [("button", f"{b.label} | {b.help}") for b in app.button]
    for frame in [*app.dataframe, *app.table]:
        data = getattr(frame.value, "data", frame.value)   # a Styler holds its frame in .data
        out += [("table header", str(column)) for column in data.columns]
        out += [("table cell", str(value)) for value in data.astype(str).to_numpy().ravel()]
    return out


def allowed_removed(text: str) -> str:
    for phrase in ALLOWED:
        text = text.replace(phrase, "")
    return text


def scan(app: AppTest, where: str) -> list[tuple[str, ...]]:
    hits = [(where, kind, match, str(value)[:120])
            for kind, value in texts(app)
            for match in BAD.findall(allowed_removed(LINK.sub("", str(value))))]
    if app.exception:
        hits.append((where, "exception", "", app.exception[0].message[:200]))
    return hits


def main() -> int:
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}; build it first (see README).", file=sys.stderr)
        return 1
    hits = []
    for key, page in PAGES.items():
        app = AppTest.from_file(APP, default_timeout=60)
        app.run()
        hits += scan(app.switch_page(page).run(), key)

    conn = get_conn()
    try:
        ids = [row[0] for row in conn.execute("SELECT company_id FROM companies ORDER BY company_id")]
    finally:
        conn.close()
    app = AppTest.from_file(APP, default_timeout=60)
    app.run()
    for company_id in ids:
        app.session_state["selected_company"] = company_id
        hits += scan(app.switch_page(PAGES["company"]).run(), f"company:{company_id}")
    compare_sets = [ids[:4], ids[4:8], ids[-4:], NO_REVIEWS]
    for compare in compare_sets:
        app.session_state["compare_ids"] = compare
        hits += scan(app.switch_page(PAGES["compare"]).run(), f"compare:{','.join(compare)}")

    print(f"scanned {len(PAGES)} pages, {len(ids)} companies, {len(compare_sets)} compare sets: "
          f"{len(hits)} found")
    for hit in hits:
        print("  " + " | ".join(hit))
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
