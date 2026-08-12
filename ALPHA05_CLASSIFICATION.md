# Alpha05 — Pair Screening Result and Classification

Real data, `alpha05_pair_screening_ftmo.py`, 2016–2026 (formation period =
first 50% of each pair's overlapping history).

## Result: REJECTED at the screening stage

**9 of 10 candidate pairs show no formal cointegration evidence at all** — ADF
t-stat nowhere near the 5% critical value (−3.34), including the pairs with
the highest raw correlation:

| Pair | corr(full) | ADF t-stat | Verdict |
|---|---|---|---|
| DAX–EU50 | +0.976 | −3.00 | not significant |
| NAS100–SP500 | +0.991 | −2.82 | not significant |
| SP500–US30 | +0.992 | −1.95 | not significant |
| US2000–SP500 | +0.789 | −1.04 | not significant, not even close |
| US2000–NAS100 | +0.799 | −0.70 | not significant, not even close |

This is a direct, clean empirical demonstration of exactly the caution
flagged in `ALPHA05_LITERATURE.md` §1: **correlation is not cointegration.**
DAX and EuroStoxx50 share massive constituent overlap and move together
0.976 of the time by simple correlation, yet the formal stationarity test on
their spread fails — the spread doesn't reliably revert, it can (and
statistically does) wander/trend rather than mean-revert, even between two
of the most fundamentally linked indices in the entire universe. It's also
consistent with the literature's documented decay/crowding of classic
stat-arb since the 1990s-2000s — our 2016-2026 window sits entirely in that
post-decay era.

**The one pair that marginally cleared the threshold (UK100–DAX, ADF −3.403
vs −3.34) fails decisively on the out-of-sample stability check**, which is
the more important test here: applying the *fixed* formation-period hedge
ratio to Validation+Final-OOS data, the estimated half-life explodes from
21.9 days (formation) to **555.5 days** (post-formation) — over two years to
revert halfway, practically indistinguishable from "doesn't mean-revert in
any tradeable sense." This is exactly the failure mode the literature review
flagged in §4 (OLS mean-reversion-speed bias, marginal in-sample significance
that doesn't survive out-of-sample) — a single pair barely clearing a 5%
threshold out of 10 tested is also consistent with what you'd expect from
chance alone at that significance level, not a robust discovery.

## Alpha05 is REJECTED because:

No candidate pair — including the two with the strongest a priori
correlation case (DAX-EU50, NAS100-SP500) and the one with the highest raw
correlation overall (SP500-US30, 0.992) — shows a formally cointegrated,
out-of-sample-stable spread. The single marginal pass (UK100-DAX) collapses
on the out-of-sample stability check specifically designed to catch this
failure mode. There is no surviving pair to build a strategy on, so per
protocol this stops at the screening stage — advancing any of these to a
costed z-score strategy would just be trading noise dressed up as a
"relationship."

## Classification: **REJECTED**

No strategy build, cost stress test, or permutation test is warranted —
consistent with how alpha04 was closed out at the descriptive stage when the
underlying phenomenon didn't survive first contact with the data.
