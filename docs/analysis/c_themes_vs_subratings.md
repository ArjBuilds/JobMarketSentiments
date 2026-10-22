# c. Theme sentiment against Glassdoor sub-ratings

Per company: the theme's average VADER score over the reviews that mention it (review_summary, all time) against the company's mean sub-rating (1-5 stars) over all its reviews that have one. Companies with at least 100 theme mentions and 20 sub-ratings. Spearman rank correlation across companies.

| theme | sub-rating | companies | Spearman |
|---|---|---|---|
| Pay | compensation_and_benefits | 77 | +0.95 |
| Culture | culture_and_values | 77 | +0.84 |
| Work-life balance | work_life_balance | 77 | +0.92 |
| Management | senior_management | 77 | +0.83 |

## Where they disagree most

The 3 companies per theme whose rank by theme sentiment and rank by sub-rating are furthest apart (rank 1 = lowest).

### Pay vs compensation_and_benefits

| company | mentions | theme score | rank | sub-rating | rank | rank gap |
|---|---|---|---|---|---|---|
| visa | 2,580 | +0.556 | 62 | 3.71 | 41 | 21 |
| flipkart | 1,221 | +0.346 | 29 | 3.87 | 49 | 20 |
| target | 30,207 | +0.342 | 28 | 3.20 | 11 | 17 |

### Culture vs culture_and_values

| company | mentions | theme score | rank | sub-rating | rank | rank gap |
|---|---|---|---|---|---|---|
| tata-motors | 1,123 | +0.368 | 9 | 4.00 | 56 | 47 |
| tata-consultancy-services | 36,077 | +0.384 | 12 | 3.93 | 49 | 37 |
| mercedes-benz | 545 | +0.464 | 49 | 3.60 | 21 | 28 |

### Work-life balance vs work_life_balance

| company | mentions | theme score | rank | sub-rating | rank | rank gap |
|---|---|---|---|---|---|---|
| google | 6,301 | +0.308 | 37 | 4.15 | 74 | 37 |
| meta | 2,129 | +0.217 | 23 | 3.75 | 50 | 27 |
| visa | 1,631 | +0.440 | 62 | 3.60 | 40 | 22 |

### Management vs senior_management

| company | mentions | theme score | rank | sub-rating | rank | rank gap |
|---|---|---|---|---|---|---|
| flipkart | 988 | +0.112 | 23 | 3.55 | 62 | 39 |
| tata-motors | 685 | +0.079 | 10 | 3.38 | 46 | 36 |
| micron | 1,569 | +0.189 | 52 | 3.16 | 22 | 30 |
