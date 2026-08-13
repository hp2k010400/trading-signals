# EDGE33 Hypothesis: Own-Instrument Volume Shock → Own Forward Volatility

Last remaining pre-ranked Databento hypothesis pursued this round (H6 from
`DATABENTO_DATA_AUDIT.md`, reformulated to use **pure real exchange volume,
no open interest** — the original audit description mixed volume/OI; this
strips it to volume only, per the explicit steer). H4 (price×OI "four-way"
folklore) is **explicitly deprioritized/retired, not tested** — it is
centrally an OI-interaction hypothesis with the weakest evidentiary prior of
all 7 original candidates (no academic support found, only trading lore),
cutting directly against "genuinely different mechanisms using real exchange
volume/participation information." Documented here so it isn't silently
dropped: if the current round's queue is exhausted, H4 remains a known,
deliberately-skipped candidate, not a forgotten one.

## Relationship to EDGE32 (stated honestly, not hidden)
EDGE32 established (Gate 1) that a volume shock in one equity index future
predicts elevated forward volatility in a *different*, closely-correlated
equity index future (cross-market spillover). EDGE33 tests the **same-
instrument** version: does ES's *own* volume shock predict ES's *own*
forward volatility — a within-market liquidity/participation mechanism, not
a cross-market information-diffusion one. These are related in flavor but
economically distinct questions. If EDGE33's Gate 1 also passes, that is
not surprising given EDGE32's result and should not be over-credited as
independent confirmation — it will still need to clear its own full Gates
2-7 (particularly an incremental-value-style scrutiny at the strategy stage,
learning directly from why EDGE32 failed there) before being treated as
actionable.

## Mechanism (frozen, ex-ante)
A sudden shock in an instrument's own trading volume (relative to its
recent history) plausibly reflects a liquidity-regime change or fresh
information arriving specific to that market. This is the most basic,
most directly microstructure-supported version of "volume predicts
volatility" — well-established as a *contemporaneous* relationship in the
literature; the genuinely testable empirical question is whether it also
has *predictive* (forward-looking) power.

## Exact instruments
**ES primary** for Gates 1-5. NQ/GC/CL for Gate 6 — generalization is
expected here (a general microstructure relationship, not instrument-
specific), consistent with how EDGE31/EDGE32 were scoped.

## Exact data / construction (frozen)
Daily bars, `databento_ohlcv_1h_v2.csv`.
- `volume_shock_t = ES_volume_t / rolling_60d_median(ES_volume)` (causal),
  identical convention used throughout this research programme.
- **Target**: `fwd_vol_h` = realized volatility (std of ES daily log
  returns) over the following `h` trading days.

## Expected direction
**Positive.**

## Horizons tested
5, 10, 20 trading days.

## No-lookahead
Signal known at close of day `t` (ES's own volume, already public/settled).
1-business-day publish lag before the forward-volatility measurement window
begins.

## Falsification criterion (Gate 1)
Reject immediately if the full-history correlation is not positive and
reasonably stable across Discovery/Validation/Final-OOS.

## If Gate 1 passes: strategy-stage plan (stated now, before any Gate 1 result)
Per the lesson directly learned from EDGE32: a volatility PREDICTION is not
itself an executable directional edge. If EDGE33 clears Gate 1, it will be
tested the same way EDGE32 was — as a volatility-managed-exposure overlay,
benchmarked against an ES-own-trailing-vol baseline (Variant B equivalent)
for INCREMENTAL value, not raw performance — since a same-instrument volume
shock and an instrument's own trailing realized vol are likely to be highly
correlated signals in the first place, making a genuine incremental-value
bar even harder (and more meaningful) to clear than EDGE32's.

Locked before any correlation has been computed.
