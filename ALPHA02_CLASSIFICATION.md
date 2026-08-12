# Alpha02 (Pre-Scheduled-Event Drift) — Phase 12 Classification

Applying the decision rule locked in `ALPHA02_PRE_REGISTRATION.md` §Decision rule,
against the real results from `alpha02_strategy_ftmo.py` (13 instruments,
N=169,040, 2016-08-15 → 2026-08-10).

## Checklist against the pre-registered rule

| Requirement | Result | Met? |
|---|---|---|
| Reasonable sample size | N=169,040 (caveat: many events share a calendar day, so effective N is smaller — documented in `ALPHA02_HYPOTHESIS.md`) | Yes |
| Positive NET (after-cost) expectancy | PF 1.04, R +2,547 at BASE cost (1.5x) | Yes, but thin |
| No obvious lookahead | Confirmed — event schedule known in advance, drift window never touches post-event data | Yes |
| Profitable in multiple independent periods, not concentrated in one | 6/11 years profitable; total survives removing best year (2021: +1,326) → still +1,221 | Partially — see below |
| Reasonable robustness to cost stress | Breaks even between +20% and +50% additional stress (PF 1.02 at 1.8x total, PF 0.99 at 2.25x, PF 0.94 at 3.0x) | **No** |

## What the evidence actually shows

**For the edge being real, not noise:**
- The Phase 10 permutation test is the strongest single piece of evidence here: the real event-anchored result (PF 1.037) beats **100/100** randomly-reanchored 24h-window permutations in the same instruments/price data (null mean PF 0.986, std 0.006 — real result is ~8+ standard deviations above the null mean). Randomly-timed 24h windows lose money after cost, as expected; pre-event windows specifically don't. This directly answers "is this just generic market drift" — no, event timing specifically matters.
- The 4 losing instruments (AUS200, HK50, AUDCAD, AUDNZD) are exactly the Asia-Pacific/FX instruments already flagged as "weakest" in the descriptive hypothesis *before* the strategy was run — not a post-hoc rationalisation, a prediction that held.
- Validation (+2,435) and Final OOS (+711) — the two periods that come after Discovery — are both independently positive.

**Against it being a currently deployable edge:**
- Discovery (2016-08-15 → 2023-05-31, the majority of the data, N=84,509) is net **negative** (-599). The whole positive total is carried by the last ~3.5 years. This isn't overfitting (the rule was never tuned on Discovery — it's fixed from literature), but it does mean the costed rule lost money over more than half the tested history.
- Year-to-year results swing hard between large winners and large losers (2021 +1,326, 2022 -1,761) rather than showing a small, repeatable edge — more consistent with a couple of dominant regime years than a stable phenomenon.
- The edge does not survive realistic cost stress: it flips net-negative once total costs reach ~2.25x (BASE+50%). Per-trade net Sharpe is very thin (0.0136).
- Worst realised month (cluster-risk-sized) is -21.33% — large for an FTMO-style account if it landed in a bad month early in a challenge.

## Classification: **B — Promising but insufficient evidence for standalone deployment**

Same tier as TSM. The permutation test is genuinely compelling evidence that pre-event
windows are statistically different from random windows — this is a real, economically
grounded, literature-consistent phenomenon, not noise. But the tradeable version fails
the pre-registered cost-stress robustness requirement, and half the test history
(Discovery) was a net loser. This is not an A (would require robustness across the full
cost stress test and no multi-year losing sub-period) and not a C/D rejection (the
permutation evidence is too strong to call it "no effect" — there clearly is one).

Per the pre-registration's own rule: **do not add filters or tune parameters now to try
to rescue the cost-stress failure.** That would be exactly the p-hacking the whole
protocol was designed to prevent. If this is pursued further, it should be as a new,
separately pre-registered hypothesis (e.g., "does restricting to the equity-index subset
only, decided for the economically-grounded reason already stated in the hypothesis doc,
survive cost stress" — not "which filter makes PF go up").
