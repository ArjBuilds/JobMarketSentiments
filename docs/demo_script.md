# Demo script (5 minutes) and viva questions

Before the demo:
- Run `python scripts/freeze.py` after the final commit.
- Start `streamlit run app/app.py`.
- Open http://localhost:8501 and click through every page once, so the caches are warm.
- Have docs/freeze.md and docs/analysis/ open in another tab.

The dashboard never calls a live source, so the demo works offline.

## Walkthrough

**0:00 – Home page (30 s).**
- Say: "A student shortlisting employers has to open forty tabs. This puts review sentiment, turnover, news and the data roles a company posted in India on one page, for 82 large employers that hire in India."
- Point at the sources table: "Every source, its dates and its licence. The dates are read from the database, not typed in. The ratings file records no date, so it says not available."

**0:30 – Library (60 s).**
- Show the table with every company, rating, sentiment and data-role count. Point out "not available" cells: "Where a source has nothing, we say so; we never estimate."
- In the sidebar, under *Compare attrition like with like*:
  - set **Published attrition basis = voluntary**
  - set **Published attrition scope = segment**
- Then **Sort by = Published attrition**, **Descending** on. Four IT companies remain: Wipro 13.8%, Infosys 13.0%, Cognizant 13.0%, HCLTech 12.8%.
- Say: "Companies define attrition differently, voluntary or all exits, group or one segment. So the ranking only compares like with like. The review-based proxy is never sorted on."

**1:30 – Company page: Infosys (60 s).**
- **Rating: not available.** "The ratings file has only Infosys BPM, a subsidiary, so we show nothing rather than a subsidiary's rating."
- **Sentiment.** 53,188 reviews scored, with the review count and date range beside the score. Point at the theme breakdown.
- **Turnover.** "Two headings. The published figure: 13.0% voluntary, IT services segment, last twelve months to June 2026, with the source link and page. Then the proxy: reviews that mention leaving or layoffs, per 100 reviews, never a %."
- **Data roles.** 25 listings, "historical, late 2023, a lower bound". The careers link is separate, under "Current openings".

**2:30 – Three edge cases (45 s).** Switch company in the selector:
- **Wipro**: no rating either, but for a different reason. "Its exact-name row has 2,700 reviews and a head office in Dresden: a regional page, so we rejected it."
- **LTM (formerly LTIMindtree)**: "Its 10,545 reviews are pre-merger Mindtree, and the page says so."
- **Intuit**: "22 reviews. It clears our 20-review cut-off, so the count is always shown beside the score."
- Optionally **HDFC Bank**: no review text ("the dataset's 'Hdfc' is a different employer, so we rejected it"), but published attrition 23.1%.

**3:15 – Market skills (30 s).**
- Tools view: SQL first, then Python and Excel.
- Toggle to Methods: Data Analysis, then Machine Learning.
- Say: "Market-wide, not per company. The skills column in the postings belongs to other rows, so we can't tie a skill to an employer. Each distinct skill list counts once. One list was copied 187 times."

**3:45 – Compare (30 s).** Pick Infosys, TCS, Accenture and Wipro.
- "Same labels and caveats as the other pages. Missing values read not available, never 0."

**4:15 – About and methods (30 s).** Scroll to *What the figures can't tell you*.
- "Reviews end mid-2023 and thin out after March. The proxy doesn't track published attrition: Spearman −0.08 across 12 companies. Kappa between VADER and TextBlob is 0.40, despite 80.5% raw agreement."

**4:45 – Close (15 s).**
- "Batch pipeline into SQLite, Streamlit reads only from SQLite. Frozen on the date in docs/freeze.md, with the commit and input hashes."

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
   - The free tier searches 30 days, so the page says so.

10. **What would you do with more time?**
    - Validate the review letter codes against the dataset card.
    - Research published attrition for more companies.
    - Find a postings source with aligned columns, so skills could be per company.
    - Hand-label a sample of reviews to test VADER directly rather than through star ratings.
