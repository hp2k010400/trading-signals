# Alpha06 — Liquidity Proxy Descriptive Result and Classification

Real data, `alpha06_liquidity_descriptive_ftmo.py`, 13 instruments, 2016–2026.

## The tool works; the hypothesis doesn't

**Sanity check passed**: CS-spread and Roll-spread agree in rank across all 13
of 13 instruments (rank correlation +0.09 to +0.20, universally positive) —
the two independently-derived liquidity proxies are measuring something real
and consistent, not noise. This confirms the estimator itself is sound.

## The cross-sectional Amihud test — the primary, most literature-faithful test — is null

Pooling all 13 instruments, ranking by estimated illiquidity each day: mean
daily spread (high-illiquidity group minus low-illiquidity group) = **−1.38bp,
t-stat ≈ −0.86** — not significant, and the average sign is *opposite* the
Amihud illiquidity-premium direction (illiquid should earn *more*, not less).
It also flips sign between periods (Discovery −4.22bp, Validation +2.02bp,
Final OOS +0.93bp) — no stable pattern.

## The time-series test — mostly the same story, one exception

Within-instrument (does an instrument's own estimated illiquidity predict its
own next-day return): correlations are small (|corr| mostly < 0.12) and
**sign-unstable across Discovery/Validation/Final-OOS for most instruments** —
e.g. US30 (−0.184 → +0.052 → +0.118), AUS200 (−0.158 → +0.056 → −0.030),
JP225 (−0.043 → +0.013 → −0.116). Several European/large-cap-US instruments
(UK100, EU50, FRA40, SP500, NAS100) show a mild directional *drift* toward
positive (Amihud-consistent) correlation into Final OOS, but full-history
magnitudes stay tiny (corr < 0.06 in all of those cases) — worth noting as a
loose pattern, not evidence of anything tradeable. One instrument, HK50,
looks cleaner (corr rising monotonically 0.040 → 0.067 → 0.106, full-history
quintile spread +18.55bp, the largest in the batch) — but one out of 13
looking decent is well within multiple-comparison noise, and it wasn't a
pre-registered primary target, so it doesn't carry much weight on its own.

## This matches the literature review's own advance caveats

`ALPHA06_LITERATURE.md` flagged two reasons a null result here would be
legitimate and expected, not a bug: (1) our CS-spread proxy is a *spread*
estimate, not the original *volume-scaled price-impact* Amihud measure, and
the literature specifically notes the premium has been shown to depend on the
volume component; (2) our universe of 13 fairly liquid CFD instruments has
far less illiquidity dispersion than the original cross-sectional stock
studies. Both caveats look directly relevant to what happened here.

## Classification: **REJECTED**

The primary, most decision-relevant test (cross-sectional) shows no
significant premium and the wrong average sign. The secondary time-series
test shows small, mostly sign-unstable relationships with no single
instrument strong enough (pre-registered or otherwise) to justify advancing
to a costed strategy. No strategy build, cost-stress, or permutation test is
warranted — consistent with how alpha04 and alpha05 were closed at their
respective descriptive/screening stages.
