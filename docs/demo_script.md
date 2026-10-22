# Demo rehearsal script and viva questions

The order to present in: Explore → filter → open a company → tabs → sector link → add to compare → Compare → About the data. Tick each box while rehearsing.

## Before you start

- [ ] Run `python scripts/freeze.py` after the final commit, so docs/freeze.md records it.
- [ ] From the repo root: `source .venv/Scripts/activate && streamlit run app/app.py` (the theme is read from `.streamlit/` in the folder you start in).
- [ ] Open http://localhost:8501 and click through every page once, so the caches are warm.
- [ ] Use light mode; switch to dark once at the end.

The dashboard never calls a live source, so the demo works offline.

## 1. Explore

- [ ] The app opens on **Explore companies**: one-line caption, "82 of 82 companies", the table.
- [ ] Point out the sidebar: the five pages, "Compare list: 0 of 4", "Data last refreshed: 22 Oct 2026".
- [ ] Hover the **Turnover proxy** header ("Not a share of staff") and **Data-role listings (2023 snapshot)** ("not live openings").
- [ ] Sentiment colours: blue positive, orange-red negative; thin samples read "Fewer than 20 reviews (n = …)".

## 2. Filter

- [ ] Sector **IT Services** → **Has data roles** on → Sort by **Review sentiment**, **Descending** on. The count drops.
- [ ] Open **More filters**: review period, attrition basis and scope.
- [ ] Sort by **Published attrition**: a one-line hint asks for a basis and scope to rank like with like.

## 3. Open a company

- [ ] Click the **Infosys** row. The Company page opens; the address shows `?company=infosys`.
- [ ] Header: name, sector link, HQ · size band · India cities. Four metrics; hover one for its tooltip.

## 4. Tabs

- [ ] **Sentiment**: score badge with review count and dates, the share bar, theme bars pointing left or right of zero. Switch to **2020–2023**. The Glassdoor rating sits in its own box (a separate source).
- [ ] **Data roles & skills**: **Current openings** button, the listings table, "See market-wide skills" (optionally click it to show Market skills, then come back).
- [ ] **News**: article rows with sentiment badges and the "GNews · fetched …" line.
- [ ] **Turnover**: the published figure (basis · scope · period · Source) beside the **Proxy** badge; hover the badge.
- [ ] Edge cases, using the company picker:
  - **Intuit**: a score from only 22 reviews, with the count shown.
  - **Atlassian**: every metric reads Not available; hover for the reason.
  - **LTM (formerly LTIMindtree)**: the sentiment tooltip says the reviews are pre-merger Mindtree.

## 5. Sector link

- [ ] On **Infosys**, click **IT Services** under the name. Explore opens filtered to IT Services; the other filters are as you left them.
- [ ] **Back to results** from any company returns with the filters intact.

## 6. Add to compare

- [ ] On **Infosys**: **Add to compare**. The button flips to **Remove from compare**; the sidebar says 1 of 4.
- [ ] Add **TCS** and **Wipro** the same way, then **Accenture** from **Compare list** on Explore. The link reads **Compare (4)**.
- [ ] Optional: open a fifth company and press **Add to compare**. A "compare list is full" message appears.

## 7. Compare

- [ ] Click **Compare (4)**: four company boxes, the metrics table with coloured sentiment rows, **Sentiment by theme** with each bar labelled by company.
- [ ] **Remove** one company; the table updates.
- [ ] Click a company's name to open its page, then return to Compare from the sidebar. The list is intact.

## 8. About the data

- [ ] The sources table: the reviews dataset named with its CC BY-NC-SA licence; the ratings row says "date not recorded".
- [ ] Open **How scores work**: four one-line bullets.
- [ ] Close by switching to **Dark** mode (⋮ → Settings → Theme) on Explore or Company.

Method and caveat detail for questions is in docs/methods.md; the report's numbers are in docs/analysis/.

## Ten likely viva questions

1. **Why score headline, pros and cons separately (method F)?**
   - On a seeded 20k sample, mean(headline, mean(pros, cons)) tracked star ratings best (Pearson 0.471).
   - It held up on a separate 20k held-out sample (0.477).
   - Pros minus cons had zero correlation (0.012): VADER already scores cons negative.
   - Source: data/raw/sentiment_checks.txt; docs/analysis/b_star_validation.md.

2. **VADER and TextBlob agree 80.5%. Isn't that good?**
   - Both call about 81% of reviews positive, so chance alone gives about 67% agreement.
   - Cohen's kappa is 0.40, on the fair/moderate boundary (Landis-Koch).
   - The tools agree, but less than the raw rate suggests.
   - Source: docs/analysis/a_kappa.md.

3. **Why can't you show skills per company?**
   - The Naukri columns are misaligned row by row. Only title and employer belong together.
   - A title containing "Python" lists Python in its skills only 7–10% of the time, the same as the base rate.
   - So skills are counted market-wide per export.
   - Source: PRD, "The postings snapshot".

4. **Why does the turnover proxy not match published attrition?**
   - It counts reviews that mention leaving, not people who left.
   - Spearman is −0.19 for 8 IT companies and −0.08 for all 12, which is about zero.
   - The samples are tiny and the periods and definitions differ.
   - So it is labelled "proxy" and never ranked.
   - Source: docs/analysis/e_proxy_vs_attrition.md.

5. **Why not scrape Glassdoor or LinkedIn for fresher data?**
   - Their terms forbid it.
   - We use a CC BY-NC-SA Kaggle review dataset, GNews's free API, and companies' own reports.

6. **How do you match "Hdfc", "LTIMindtree" or "PwC Service Delivery Center" to your companies?**
   - Once, at load time, through one committed alias file (company_aliases.csv), with an alias kept per source.
   - No fuzzy matching at query time.
   - Ambiguous names are rejected rather than guessed (Chase, Hdfc, Wipro's Dresden page).

7. **What does "lower bound" mean on the data-role counts?**
   - The same title and employer were copied onto many rows; American Express's one title appears 394 times.
   - We dedupe to distinct listings: 2,471 rows become 976.
   - Same-title listings without a verified link count once, so the true number can only be higher.

8. **Why a batch pipeline and SQLite, not live calls?**
   - The demo must survive a dead or rate-limited API (GNews allows 100 requests a day).
   - Pages read only SQLite and load in under 3 s (scripts/time_pages.py).

9. **How do you make sure a news article is about the company?**
   - One query per company, with workplace terms.
   - An article is kept only if its title or description names the company as a whole word with matching case: "Target" the retailer, not "target".
   - Duplicates are dropped and the 10 newest kept.
   - The free tier searches only 30 days, so news is never labelled "the last 12 months"; the page shows the fetch date.

10. **What would you do with more time?**
    - Validate the review letter codes against the dataset card.
    - Research published attrition for more companies.
    - Find a postings source with aligned columns, so skills could be per company.
    - Hand-label a sample of reviews to test VADER directly rather than through star ratings.
