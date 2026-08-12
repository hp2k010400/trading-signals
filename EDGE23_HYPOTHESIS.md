# Edge #5 (E23) Hypothesis: COT Speculator Positioning FLOW (week-over-week change) → S&P 500 Forward Returns

## Why should this edge exist?
Distinct mechanism from E19/E22 (which both tested the *level* of
positioning): this tests the *rate of change* — rapid week-over-week
increases in speculative net length reflect fresh buying/momentum pressure
entering the market. The proposed story: fresh net positioning flow (as
opposed to a static crowded level) is more likely to reflect genuinely new
information or momentum-chasing flow that has near-term continuation power,
before any eventual over-extension/reversal sets in at longer horizons.

## Context: two related hypotheses already failed at Gates 2-7
E19 (commercial level) and E22 (speculator level) both passed Gate 1 cleanly
but failed Gates 2-7 identically — real, monotonic descriptive correlations
that didn't survive conversion into a symmetric long/short strategy against
persistently-trending US equity indices. This candidate uses the same data
source and same strategy-construction methodology (for controlled
comparability), so a similar Gates-2-7 outcome would not be surprising. It's
tested anyway because the *signal construction* (rate of change, not level)
is genuinely different, and Gate 1 is cheap to check before deciding whether
to invest in the full gate sequence.

## Exact data source
Same as E19/E22: CFTC Socrata API, `S&P 500 Consolidated - CHICAGO
MERCANTILE EXCHANGE`, `Combined`. Non-commercial category (as in E22).

## Exact signal definition
`net_noncomm_frac` as before, then `flow = net_noncomm_frac.diff()`
(week-over-week change), then a 156-week causal rolling z-score of `flow`
(not of the level) — genuinely different construction from E19/E22.

## Signal availability / no-lookahead
Identical to E19/E22: `signal_available_date = report_date + 3 calendar
days`.

## Expected direction
**Positive.** Fresh net speculative buying flow (positive, high z) predicts
above-average forward returns (momentum); fresh net selling flow predicts
below-average forward returns.

## Horizons tested
1 week, 2 weeks, 4 weeks — identical to E19/E22 for comparability.

## Instruments
S&P 500 only for Gate 1.

## Falsification criterion
Same standard: reject at Gate 1 if full-history correlation is not positive
and reasonably stable across Discovery/Validation/Final-OOS.

Locked before any correlation has been computed.
