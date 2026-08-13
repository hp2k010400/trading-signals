# EDGE32 Risk-Overlay Pre-Registration

Frozen before any of variants A/B/C/D below have been run. The Gate 1
descriptive relationship (NQ volume shock → forward ES realized volatility,
established on real data: full-history corr +0.09 to +0.11, significant and
stable in all three periods) is preserved as-is and not re-tested here. This
document specifies exactly how it is converted into a risk-management
overlay, per the volatility-managed-portfolio framing (Moreira & Muir 2017).

## Primary hypothesis
Using the EDGE32 signal to scale a baseline long-ES exposure improves
risk-adjusted performance and/or drawdown characteristics relative to an
**equal-average-risk** constant-exposure benchmark — **not** a test of
standalone directional alpha.

## The four variants (A/B/C/D), all pre-specified

- **Target annualized volatility**: `TARGET_ANN_VOL = 15%` (a round,
  standard vol-targeting convention, not tuned).
- **Variant A — Constant exposure**: a fixed ES position fraction, calibrated
  **once**, using only the Discovery period's average realized ES
  volatility, such that its ex-ante expected annualized vol ≈
  `TARGET_ANN_VOL`. This fraction is then held fixed for the entire sample
  (Discovery/Validation/Final-OOS) — a genuine non-timed baseline with
  comparable long-run average risk, addressing the "fair comparison" concern
  directly (per instruction).
- **Variant B — ES-own-volatility-managed**: position fraction =
  `TARGET_ANN_VOL / ES_trailing_20d_annualized_vol`, i.e. the standard,
  "obvious" vol-targeting approach using only ES's own trailing realized
  volatility (no NQ information at all).
- **Variant C — EDGE32 NQ-volume-managed**: position fraction =
  `TARGET_ANN_VOL / predicted_vol_C`, where
  `predicted_vol_C = ES_trailing_20d_vol × (NQ_volume_shock_t / mean(NQ_volume_shock, expanding))`
  — i.e. ES's own trailing vol, adjusted up or down by how elevated/depressed
  today's NQ volume shock is relative to its own historical average. This
  directly incorporates the Gate 1 signal without fitting any regression
  coefficient (no parameter search), a deliberately simple, mechanical
  construction.
- **Variant D — Combined**: position fraction =
  `TARGET_ANN_VOL / geometric_mean(ES_trailing_20d_vol, predicted_vol_C)`
  — pre-registered now, before any variant has been run, specifically to
  answer whether NQ information adds value *on top of* (not merely instead
  of) ES's own volatility signal.

## Bounds
Every variant's position fraction is capped to **[0.5×, 2.0×] of Variant
A's fixed fraction** — bounds leverage/degenerate positions, a standard,
simple, round choice, not tuned.

## Rebalance frequency
**Daily** — recomputed each trading day from that day's available signal.

## Signal lag / execution timing
Identical to every prior candidate this session: signal known at close of
day `t`, 1-business-day publish lag, position adjusted at the next trading
day's close.

## Transaction costs
Turnover-based: each day's *change* in position fraction (increase or
decrease) is costed at `COST_POINTS_ES = 0.6` points on the changed notional
— the standard way to cost a continuously-rebalanced exposure, using the
same base cost figure established throughout this research programme.
Base stress `BASE_COST_MULT = 1.5`, additional stress levels `1.0/1.5/2.0/3.0`
on top of base, matching the convention used for EDGE30.

## Discovery / Validation / Final-OOS
50th/75th-percentile-of-date split, identical method used throughout.
Reported by year and by period for every variant, per instruction.

## Statistical tests
- Paired comparison of **daily excess return** (C minus B) — mean-difference
  test (accounts for the fact that both series share most of their
  variance, isolating the incremental effect of adding NQ information).
- Block-bootstrap (250 blocks of 20 trading days each, resampled with
  replacement, preserving short-run autocorrelation) on the C-minus-B daily
  return series, to build a confidence interval on the incremental Sharpe
  improvement.
- Circular-shift permutation (500 shifts) of the NQ volume-shock series
  specifically (not the whole signal construction), to test whether C's
  improvement over B is distinguishable from a randomly-timed vol-scaling
  overlay.

## Parameter robustness (pre-specified, not optimized)
`TARGET_ANN_VOL ∈ {10%, 15%, 20%}` — the single free construction parameter,
tested at three round, standard, pre-specified values. 15% is primary; 10%
and 20% are neighbors for the plateau check. No other parameter (lookback
window, bounds, cost) is varied.

## Acceptance criteria (frozen, per instruction)
EDGE32 qualifies as `VALIDATED_RISK_OVERLAY` / `PORTFOLIO_COMPONENT` only if
**all** of the following hold:
1. The Gate 1 descriptive relationship remains temporally robust (already
   established — not re-litigated here).
2. Variant C improves risk-adjusted performance and/or drawdown, fairly,
   versus Variant A (equal average-risk constant exposure).
3. The improvement (C vs B, and C/D vs A) holds independently in **both**
   Validation and Final-OOS, not just Discovery.
4. **C provides statistically meaningful incremental value over B** — this
   is the central question. If C ≈ B (NQ adds nothing beyond ES's own
   trailing vol), REJECT as a risk-overlay, regardless of how A compares.
5. Results survive realistic cost stress (up to 3.0x total multiplier).
6. Results are not carried by COVID/2020 or any single crisis period alone.
7. Parameter behavior across `TARGET_ANN_VOL ∈ {10,15,20}%` is a plateau,
   not a narrow spike.

If these hold: classify `VALIDATED_RISK_OVERLAY` / `PORTFOLIO_COMPONENT` —
explicitly not a standalone directional edge, valuable to the eventual
multi-edge portfolio in a different way. If C fails to add value over B (or
any other criterion fails): reject EDGE32 as a trading/risk-management
construct, while the Gate 1 descriptive relationship itself remains
documented as a genuine, real finding — not erased, just not actionable at
this stage.

Locked before any of variants A/B/C/D have been run.
