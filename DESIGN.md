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
| Explore (default) | Browse and narrow the library (F1, F2) | Featured companies, recent articles, sidebar filters, company table |
| Company | Everything about one company (F3–F6, F8) | Header, metric row, tabs: Sentiment, Data roles & skills, News, Turnover |
| Compare | 2–4 companies side by side (F9) | One metrics table + small multiples |
| Market skills | Skills Indian data-role postings ask for, market-wide (F7) | One-line market-wide label, view switch (all / tools / methods), top skills bar chart |
| About the data | Sources and their dates | Sources table (source, used for, dates) and one collapsed "How scores work" expander |

Sidebar: app name, page nav in the order Explore, Company, Compare, Market skills, About the data, and a data-freshness line ("Data last refreshed: <newest source date>", linking to About the data, where each source's own date is listed). The date is read from `jmsa/freshness.py`, never typed in. The sidebar carries no compare-list count; "Compare (n)" sits beside the compare picker on Explore. Explore draws its filters in the sidebar; no other page does, because no other page filters the library.

## Cross-page connectivity (most important section)
State lives in `st.session_state`, set up in `app/state.py` by an idempotent `init_state()`. `app/app.py` calls it before `st.navigation(...).run()`; each page also calls it at the top, so a page run on its own (as the page tests do) still has its state.

- `selected_company`: a `company_id` slug. Mirrored to `st.query_params["company"]` so a company page URL can be shared or refreshed. On load, if the query param exists and is a known `company_id`, it wins; an unknown value is ignored.
- `compare_ids`: list of up to 4 slugs.
- `filters`: dict mirroring `jmsa.library.Filters` plus the sort (period, sectors, countries, min_rating, min_sentiment, min_reviews, has_data_roles, include_missing, attrition_basis, attrition_scope, sort, descending). Store it in a plain session key, not only in widget keys, because Streamlit discards widget state when the widget is not rendered on the current page. Widgets read their default from `filters` and write back on change. There is no skill filter: no skill can be tied to a company.

Links between pages:
- Explore: a featured card's full-width "Open <name>" button, an article's company button, and a click on any table cell or a row's checkbox (`selection_mode=["single-row", "single-cell"]`) all call `open_company()` in `app/ui/components.py`, which sets `selected_company` and calls `st.switch_page` to Company in the same tab. Never a LinkColumn: it opens a new tab and a new session. `st.container` has no click of its own, so a card is not clickable as a whole. The compare picker beside the table adds to compare.
- Company page: a company selectbox at the top (so users can hop between companies without going back), "Add to compare" / "Remove from compare" button, and a "← Back to results" `st.page_link` to Explore that returns with filters intact.
- Clickable context on Company page: the sector links back to Explore with that sector filter pre-applied (set `filters`, then switch page). The Data roles & skills tab links to Market skills, where skills live.
- Compare page: each company name links to its Company page. Empty compare list shows a message and a link to Explore.
- Never make a user re-pick a company or re-apply a filter they already chose.

## Visual direction
- Style: dense, calm, analytical. Think a clean research tool, not a marketing site.
- Theme lives in `.streamlit/config.toml` (`[theme]`: base, primaryColor, backgroundColor, secondaryBackgroundColor, textColor, font). One accent colour, used for primary actions and selection only. Support Streamlit's light and dark modes; do not hard-code white backgrounds in charts.
- Custom CSS: avoid. If unavoidable, keep it in one `app/ui/styles.py` injected once, under 30 lines, and never target auto-generated class names.
- Semantic colours are fixed and reused everywhere (tables, badges, every chart), chosen to stay distinct for colour-blind viewers in light and dark mode (checked with a CVD validator, one hex each for both modes):
  - positive blue `#2a78d6`, neutral grey `#9E9E9E`, negative orange-red `#d95926`
  - proxy marker: aqua `#199e70`
  - accent (primary buttons, selection, a single-series chart): violet `#6250d6`, so no control reads as a sentiment
  - In `.streamlit/config.toml` they are Streamlit's `blueColor`, `grayColor`, `redColor` and `greenColor` (the proxy), so `:blue-badge[...]` etc. match the charts.
- One shared Plotly template in `app/ui/charts.py` (font, margins, gridlines, transparent background, semantic colours). Every chart uses it. No 3D, no pie charts for more than 3 slices, no chart without axis labels and units.
- Layout: `layout="wide"`. Content in `st.columns` and `st.container(border=True)` groups. Max one row of 4 metrics at the top of a page.
- Numbers:
  - Sentiment: signed compound score to 2 decimals plus label, e.g. `+0.31 · Positive`, `-0.12 · Negative`. Formatted only by `score_text()` in `jmsa/sentiment.py`.
  - Published attrition: `%` with basis, scope and period, as printed in the company's document.
  - Turnover proxy: "per 100 reviews", never with a `%` sign, always with the Proxy tag.
  - Counts with thousands separators. Dates as `21 Oct 2026` in UI (ISO in the DB); every date comes from `jmsa/freshness.py`, never typed into a caption or constant.
- Missing values read "Not available" (the `NOT_AVAILABLE` constant in `jmsa/display.py`, applied through `show()`).
- Copy: plain, specific labels ("Data-role listings (2023 snapshot)", not "Opportunities"). Postings are a 2023 snapshot: never "open now", "hiring now" or "open roles". Buttons use verbs ("Add to compare"). Emoji only as page icons in navigation, nowhere else.

## Text on pages
The app reads like a finished product a student uses, not a methods write-up. Labels, one-sentence tooltips and a one-line source-and-date note per data block; never method or caveat paragraphs, long captions, export file names, or mention of the course or assignment. The method and caveats live in docs/methods.md.
- Proxy: a "Proxy" tag beside every proxy number, tooltip "Reviews mentioning people leaving, per 100 reviews. Not a share of staff."
- Data roles: "Data-role listings (2023 snapshot)", tooltip "From a 2023 dataset, not live openings."
- Missing and thin data: "Not available" and "Fewer than 20 reviews (n = X)".
- Freshness: source name + date only, e.g. "Glassdoor reviews · to Jul 2023", "GNews · fetched 22 Oct 2026".
- Column tooltips: one short sentence at most.

## Shared components (build once in `app/ui/components.py`, reuse everywhere)
- `company_header(company)`: name, sector link, HQ country, India cities, size band.
- `metric_or_na(label, value, help, source=None)`: renders `st.metric` or a consistent "Not available" with the reason in the tooltip.
- `sentiment_badge(compound)`: label + colour from the fixed cut-offs in `jmsa/sentiment.py` (≥0.05 positive, ≤−0.05 negative).
- `proxy_tag()`: aqua "Proxy" badge with the one-line tooltip on hover. Shown next to every proxy turnover number, in tables too.
- `freshness_note(notes, *keys)`: one small caption under a data block, "Glassdoor reviews · to Jul 2023", from `jmsa.freshness.freshness_notes()` so the dates come from the database.
- `empty_state(message, action_label=None, target_page=None)`: one sentence plus one next action.

If a page needs something these don't cover, add a component here rather than styling inline.

## Page specs
**Explore.** Top to bottom:
- Featured companies: up to 6 bordered cards, 3 a row. `jmsa.library.featured()` picks the companies with every figure a card shows (all-time sentiment from at least 20 reviews, published attrition, data-role listings, at least one news article; no Glassdoor rating needed), by review count, at most 2 per sector. A card shows name, sector, sentiment badge with review count, published attrition, data-role listings (2023 snapshot), the mean headline sentiment of its news with the article count, and an "Open <name>" primary button.
- Recent articles: `st.tabs` Positive / Neutral / Negative, each label with its total count, each tab the 15 newest in a fixed-height scrolling container. A row: title (external link), outlet, date, sentiment badge, and the company name as a button to its page. The GNews freshness line after the tabs.
- All companies: the table below.

Neither the cards nor the articles are filtered. Filters in the sidebar, drawn by Explore only, and applied to the companies table only: the main filters (sector multiselect, HQ country, min sentiment, "Has data roles" toggle, sort and descending), the rest (review period, min Glassdoor rating, min reviews, include companies with no value, published attrition basis and scope) in a "More filters" expander, then "Clear filters". Results count right above the table. Table columns via `st.column_config`: name, sector, HQ, India cities, Glassdoor rating, sentiment (the `+0.31 · Positive` text, coloured by label, so hidden and missing values still read as text), reviews scored, data-role listings (2023 snapshot), published attrition, turnover proxy (with Proxy marker). Column notes go in one-sentence header tooltips; under the table only the source-and-date note. Hide the index. The proxy is never sortable. Loads in under 3 s (use `st.cache_data` on DB reads).

**Company.** Selectbox + Back link + Add to compare on top, then `company_header`, then a row of 4 metrics: Employee sentiment, Reviews analysed, Published attrition, Data-role listings (2023 snapshot). The attrition metric shows only a published figure or "Not available"; it never falls back to the proxy. Then `st.tabs`:
- Sentiment: positive/neutral/negative share bar, sentiment by theme (pay, culture, WLB, management) as a horizontal bar, review date range, Glassdoor rating (labelled as a separate source). Scores show "Fewer than 20 reviews (n = X)" below the threshold; the review count is always shown.
- Data roles & skills: "Current openings" link to the official careers site; data-role listings table with title, employer as posted and city only (never link or posted time), under the "Data-role listings (2023 snapshot)" label and its tooltip; then skills "Not available" for one company, with a link to Market skills.
- News: up to 10 articles, each as a row: title (link), outlet, date, sentiment badge; the note "GNews · fetched <date>".
- Turnover: published attrition (value, basis, scope, period, source link) and, under its own heading, the review-based proxy with its Proxy tag and split. Neither stands in for the other.

**Market skills.** A one-line market-wide label, the view switch and one bar chart of the top skills (share of distinct skill lists). No company appears on this page.

**Compare.** Shows `compare_ids`, the list built on Explore and Company, with a picker to change it. One box per company: its name opens its Company page, plus a Remove button. Table with companies as columns and metrics as rows, same formatting and colours as elsewhere; a grouped bar of theme sentiment where colour means sentiment and each bar is labelled with its company. Fewer than 2 companies: a message and a link to Explore. The list holds 4; Add to compare on a full list says so rather than doing nothing.

**About the data.** A clean, short page: a table of sources (source, what it is used for, dates) and at most one collapsed "How scores work" expander with no more than 4 one-line bullets. No paragraphs. It still opens when the database is missing.

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
- No data-role count is presented as current openings; every one is labelled "Data-role listings (2023 snapshot)".
- No page has a method or caveat paragraph; each data block ends in one source-and-date line.
- No raw DB column names or Python reprs are visible.
- Works in Streamlit light and dark themes.
