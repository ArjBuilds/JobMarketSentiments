# a. VADER against TextBlob: raw agreement and Cohen's kappa

Sample: seed 42, 50,000 scored reviews (the TextBlob check in process/sentiment_checks.py). Both tools score headline, pros and cons separately, combined as mean(headline, mean(pros, cons)), with the same cut-offs (positive >= 0.05, negative <= -0.05).

|  | TextBlob negative | TextBlob neutral | TextBlob positive | total |
|---|---|---|---|---|
| VADER negative | 2,039 | 1,316 | 1,369 | 4,724 |
| VADER neutral | 579 | 1,623 | 2,578 | 4,780 |
| VADER positive | 770 | 3,134 | 36,592 | 40,496 |
| TextBlob total | 3,388 | 6,073 | 40,539 | 50,000 |

| measure | value |
|---|---|
| raw agreement (p_o) | 80.5% |
| chance agreement (p_e) | 67.5% |
| Cohen's kappa | 0.40 |

**VADER and TextBlob agree on 80.5% of labels (raw agreement); Cohen's kappa 0.40, on the fair/moderate boundary (Landis-Koch).** Raw agreement is high mostly because both tools call most reviews positive (VADER 81%, TextBlob 81%), so two tools labelling at random with those shares would already agree 67% of the time. Kappa measures agreement beyond that.
