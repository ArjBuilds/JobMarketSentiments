# b. Star-rating validation of the sentiment method

Each method's review score against the review's star rating. Stars are labelled 4-5 positive, 3 neutral, 1-2 negative for the agreement column. Method F is the one the pipeline uses; it was chosen on the seed-42 sample, so it is re-checked on a separate held-out sample with no review in common.

| method | sample | reviews | Pearson r | Spearman | pos / neu / neg | label agrees with stars |
|---|---|---|---|---|---|---|
| A headline only | seed 42 | 20,000 | 0.443 | 0.404 | 54% / 38% / 8% | 56.5% |
| B headline+pros+cons as one text | seed 42 | 20,000 | 0.438 | 0.350 | 85% / 3% / 12% | 65.7% |
| C (pros - cons)/2 | seed 42 | 20,000 | 0.012 | -0.002 | 84% / 9% / 7% | 58.8% |
| D (pros + cons)/2 | seed 42 | 20,000 | 0.272 | 0.249 | 78% / 10% / 11% | 61.6% |
| E (headline + pros + cons)/3 | seed 42 | 20,000 | 0.428 | 0.383 | 82% / 9% / 9% | 65.7% |
| F (headline + (pros+cons)/2)/2  [used] | seed 42 | 20,000 | 0.471 | 0.423 | 81% / 10% / 9% | 66.3% |
| F held-out | seed 7 (held out) | 20,000 | 0.477 | 0.429 | 81% / 10% / 9% | 66.7% |

C, pros minus cons, has no correlation with the stars: VADER already scores cons negative, so subtracting them cancels the signal.
