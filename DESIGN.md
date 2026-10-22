# DESIGN.md — Job Market Analyser

Read this file before changing anything in `app/`. It is the design contract for the Streamlit dashboard. CLAUDE.md covers code rules; this file covers how the app looks, how pages connect, and how every state is shown. Where this file and PRD.md or CLAUDE.md disagree on what data may be shown or how, those win; fix this file to match.

## Product context
- Product: a Streamlit dashboard where a student picks a company and sees, on one page, what it is like to work there and what data roles it posted in India (82 large global companies that hire in India).
- Primary user: a final-year engineering student in India shortlisting employers before placements. They are comparing many companies quickly and want a consistent, trustworthy picture.
- Audience for the demo: course faculty. The app must look deliberate and honest about its data, not like a default Streamlit script.
- Stack: Python 3.11, Streamlit (pin a recent version in requirements.txt), Plotly, SQLite. No custom frontend, no React, no external CSS frameworks.

## Design goal
Every screen answers one question fast: "Should I shortlist this company, and why?" Prefer clear hierarchy, real numbers with their source and date, and explicit "Not available" over anything decorative. A user should be able to go Explore → Company → Compare → back to Explore without losing their filters or their place.

## Information architecture
Use `st.navigation` with `st.Page` (not the legacy `pages/` folder auto-discovery) so page titles, icons and order are controlled in one place, the entry file `app/app.py` (run with `streamlit run app/app.py`).

| Page | Purpose | Key content |
|---|---|---|
| Explore (default) | Browse and narrow the library (F1, F2) | Filter bar, results count, company table |
| Company | Everything about one company (F3–F6, F8) | Header, metric row, tabs: Sentiment, Data roles & skills, News, Turnover |
| Market skills | Skills Indian data-role postings ask for, market-wide (F7) | Top skills bar chart, view switch (all / tools / methods), export comparison |
| Compare | 2–4 companies side by side (F9) | One metrics table + small multiples |
| About the data | Sources, methods, date ranges, refresh dates | Sources and freshness table, dataset names and licences, VADER cut-offs, proxy definition, caveats |

Sidebar: app name, page nav, a "Compare (n)" indicator, and a data-freshness line ("Data last refreshed: <newest source date>", linking to About the data, where each source's own date is listed). The date is read from `jmsa/freshness.py`, never typed in. No filters in the sidebar; filters live on Explore.

## Cross-page connectivity (most important section)
State lives in `st.session_state`, set up in `app/state.py` by an idempotent `init_state()`. `app/app.py` calls it before `st.navigation(...).run()`; each page also calls it at the top, so a page run on its own (as the page tests do) still has its state.

- `selected_company`: a `company_id` slug. Mirrored to `st.query_params["company"]` so a company page URL can be shared or refreshed. On load, if the query param exists and is a known `company_id`, it wins; an unknown value is ignored.
- `compare_ids`: list of up to 4 slugs.
- `filters`: dict mirroring `jmsa.library.Filters` plus the sort (period, sectors, countries, min_rating, min_sentiment, min_reviews, has_data_roles, include_missing, attrition_basis, attrition_scope, sort, descending). Store it in a plain session key, not only in widget keys, because Streamlit discards widget state when the widget is not rendered on the current page. Widgets read their default from `filters` and write back on change. There is no skill filter: no skill can be tied to a company.

Links between pages:
- Explore table: single-row selection (`st.dataframe(..., on_select="rerun", selection_mode="single-row")`). Selecting a row sets `selected_company` and calls `st.switch_page` to Company. Also offer a checkbox column or button to add to compare.
- Company page: a company selectbox at the top (so users can hop between companies without going back), "Add to compare" / "Remove from compare" button, and a "← Back to results" `st.page_link` to Explore that returns with filters intact.
- Clickable context on Company page: the sector links back to Explore with that sector filter pre-applied (set `filters`, then switch page). The Data roles & skills tab links to Market skills, where skills live.
- Compare page: each company name links to its Company page. Empty compare list shows a message and a link to Explore.
- Never make a user re-pick a company or re-apply a filter they already chose.

## Visual direction
- Style: dense, calm, analytical. Think a clean research tool, not a marketing site.
- Theme lives in `.streamlit/config.toml` (`[theme]`: base, primaryColor, backgroundColor, secondaryBackgroundColor, textColor, font). One accent colour, used for primary actions and selection only. Support Streamlit's light and dark modes; do not hard-code white backgrounds in charts.
- Custom CSS: avoid. If unavoidable, keep it in one `app/ui/styles.py` injected once, under 30 lines, and never target auto-generated class names.
- Semantic colours are fixed and reused everywhere (tables, badges, every chart):
  - positive `#2E7D32`, neutral `#9E9E9E`, negative `#C62828`
  - proxy/estimate marker: amber `#B26A00`
- One shared Plotly template in `app/ui/charts.py` (font, margins, gridlines, transparent background, semantic colours). Every chart uses it. No 3D, no pie charts for more than 3 slices, no chart without axis labels and units.
- Layout: `layout="wide"`. Content in `st.columns` and `st.container(border=True)` groups. Max one row of 4 metrics at the top of a page.
- Numbers:
  - Sentiment: signed compound score to 2 decimals plus label, e.g. `+0.31 · Positive`, `-0.12 · Negative`. Formatted only by `score_text()` in `jmsa/sentiment.py`.
  - Published attrition: `%` with basis, scope and period, as printed in the company's document.
  - Turnover proxy: "per 100 reviews", never with a `%` sign, always with the Proxy tag.
  - Counts with thousands separators. Dates as `21 Oct 2026` in UI (ISO in the DB); every date comes from `jmsa/freshness.py`, never typed into a caption or constant.
- Missing values read "Not available" (the `NOT_AVAILABLE` constant in `jmsa/display.py`, applied through `show()`).
- Copy: plain, specific labels ("Data-role listings (dataset snapshot)", not "Opportunities"). Postings are a 2023 snapshot: never "open now", "hiring now" or "open roles". Data-role counts always carry the lower-bound note. Buttons use verbs ("Add to compare"). Emoji only as page icons in navigation, nowhere else.

## Shared components (build once in `app/ui/components.py`, reuse everywhere)
- `company_header(company)`: name, sector link, HQ country, India cities, size band.
- `metric_or_na(label, value, help, source=None)`: renders `st.metric` or a consistent "Not available" with the reason in the tooltip.
- `sentiment_badge(compound)`: label + colour from the fixed cut-offs in `jmsa/sentiment.py` (≥0.05 positive, ≤−0.05 negative).
- `proxy_tag()`: amber "Proxy" label with the definition on hover. Shown next to every proxy turnover number, in tables too.
- `freshness_note(source_key)`: small caption under any data block, built from `jmsa.freshness.source_line` so the source name and dates come from the database.
- `empty_state(message, action_label=None, target_page=None)`: one sentence plus one next action.

If a page needs something these don't cover, add a component here rather than styling inline.

## Page specs
**Explore.** Filter bar above the table: one row of columns for the main filters (sector multiselect, HQ country, min sentiment, "Has data roles in the dataset" toggle, sort and descending), and the rest (review period, min Glassdoor rating, min reviews, include companies with no value, published attrition basis and scope) in a "More filters" expander below it. Results count and "Clear filters" right above the table. Table columns via `st.column_config`: name, sector, HQ, India cities, Glassdoor rating, sentiment (the `+0.31 · Positive` text, coloured by label, so hidden and missing values still read as text), reviews scored, data-role listings (dataset snapshot), published attrition, turnover proxy (with Proxy marker). Column notes go in header tooltips, not in a paragraph under the table. Hide the index. The proxy is never sortable. Loads in under 3 s (use `st.cache_data` on DB reads).

**Company.** Selectbox + Back link + Add to compare on top, then `company_header`, then a row of 4 metrics: Employee sentiment, Reviews analysed, Published attrition, Data-role listings (dataset snapshot). The attrition metric shows only a published figure or "Not available"; it never falls back to the proxy. Then `st.tabs`:
- Sentiment: positive/neutral/negative share bar, sentiment by theme (pay, culture, WLB, management) as a horizontal bar, review date range, Glassdoor rating (labelled as a separate source). Scores hidden with an explanation if fewer than 20 reviews; the review count is always shown.
- Data roles & skills: "Current openings" link to the official careers site; data-role listings table with title, employer as posted and city only (never link or posted time), with the lower-bound and snapshot notes; then the note that skills are market-wide only, with a link to Market skills.
- News: up to 10 articles from the 30 days before the fetch date, each as a row: title (link), outlet, date, sentiment badge; plus the fetch date.
- Turnover: published attrition (value, basis, scope, period, entity, definition, source link) and, under its own heading, the review-based proxy with its Proxy tag, split and definition. Neither stands in for the other.

**Market skills.** One bar chart of the top skills (share of distinct skill lists), the view switch, and the export comparison in an expander. No company appears on this page.

**Compare.** Table with companies as columns and metrics as rows, same formatting and badges as elsewhere; a small grouped bar of theme sentiment. Remove buttons per company.

**About the data.** Every source with name, date range, licence/terms note, and method summary. This page is part of the grade; keep it tidy. Its static methods text shows even when the database is missing.

## Required states
- Default with real data.
- Missing field: "Not available" via `metric_or_na`, never 0, blank, or an estimate.
- Below threshold: sentiment hidden with "Fewer than 20 reviews (n = X)" (from `hidden()` in `jmsa/sentiment.py`).
- Empty filter result: "No companies match these filters" + "Clear filters".
- Empty compare list: message + link to Explore.
- Database missing or empty: a clear error telling the user to run the pipeline, not a stack trace. Checked once in `app/app.py`.
- Loading: rely on cached reads; use `st.spinner` only around genuinely slow work. Keep layout from jumping between states.

## Avoid
Default unstyled `st.write` dumps of DataFrames, raw column names (`sentiment_compound`) in the UI, rainbow chart colours, inconsistent sentiment colours between pages, gradients, emoji in body text, giant headers with no data, repeating the same metric in three places, `st.balloons`, filters that reset on page change, any number shown without its source or "proxy" label where applicable, and any wording that presents snapshot postings as current openings.

## Implementation instructions for Claude Code
1. Read this file and CLAUDE.md. List existing files in `app/` and reuse what's there.
2. Critique pass first: compare the current UI against this file and list gaps under navigation, state persistence, layout, typography/theme, colour, charts, copy, and missing states. Show the list before editing.
3. Build in this order, running the app and committing after each: (a) `state.py` + `st.navigation` in `app/app.py`; (b) theme config + `charts.py` template; (c) `components.py`; (d) Explore; (e) Company; (f) Compare; (g) About and Market skills.
4. Make the smallest change that closes each gap. Don't rewrite data-loading code to fix a visual problem.
5. After each step, check: navigate Explore → Company → Compare → Explore and confirm filters and selections survive.

## Acceptance checklist
- Selecting a company anywhere opens its page; refreshing that page keeps the company (query param).
- Filters survive leaving and returning to Explore.
- The sector link on a company page opens Explore pre-filtered.
- Sentiment colours and labels are identical on every page and chart.
- Every proxy number carries the Proxy tag; every missing value says "Not available".
- No data-role count is presented as current openings, and every one carries the lower-bound note.
- No raw DB column names or Python reprs are visible.
- Works in Streamlit light and dark themes.
