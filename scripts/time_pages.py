"""Time every dashboard page against the real database.

Run from the repo root:  python scripts/time_pages.py

Each page is opened headlessly through the router (app/app.py) with
Streamlit's own AppTest, then run twice: the first run is the page's first
load (nothing cached yet), the second a rerun, as when a filter changes. It measures the page script, not the browser's
rendering, so also open each page in the browser. The PRD asks for under 3 s.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Run as a script, so the repo root isn't on sys.path yet (as in app/app.py).
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

from app.ui.components import PAGES  # noqa: E402
from jmsa.config import DB_PATH  # noqa: E402
LIMIT_SECONDS = 3.0


def main() -> int:
    if not DB_PATH.exists():
        print(f"No database at {DB_PATH}; build it first (see README).", file=sys.stderr)
        return 1
    print(f"database: {DB_PATH}")
    slow = 0
    for page in PAGES.values():
        app = AppTest.from_file(str(ROOT / "app/app.py"), default_timeout=60)
        app.switch_page(page)
        started = time.perf_counter()
        app.run()
        first = time.perf_counter() - started
        started = time.perf_counter()
        app.run()
        rerun = time.perf_counter() - started
        # A page that doesn't compile raises nothing here and draws nothing,
        # so a page with no title counts as an error too.
        errors = len(app.exception) + (not app.title)
        ok = first < LIMIT_SECONDS and not errors
        slow += not ok
        print(f"  {page:36} first {first:5.2f} s   rerun {rerun:5.2f} s   errors {errors}   "
              f"{'ok' if ok else 'CHECK'}")
    return 1 if slow else 0


if __name__ == "__main__":
    raise SystemExit(main())
