# Edge #9-H1 (E27) Hypothesis: Open Interest Change → Forward Returns

Rank 1 of 3 pre-committed Databento candidates (`DATABENTO_DATA_AUDIT.md`).
Tested first, in this order, regardless of how it turns out. Follows
`DATABENTO_VALIDATION_PROTOCOL.md`.

## Why should this edge exist?
Hong & Yogo (NBER working paper, published in *Journal of Financial
Economics*): the 12-month change in futures open interest predicts
commodity, bond, currency, and (more weakly) equity returns. A standard-
deviation increase in commodity market open interest raises expected
commodity returns by ~0.72%/month — economically large, statistically
significant, and it holds after controlling for other known predictors.
Mechanism: OI changes reflect shifts in hedging demand and the market's
risk-absorption capacity, information not fully contained in price alone.

## Honest counter-evidence / caveats
The cited effect is strongest for commodities specifically (GC, CL are a
direct match); the equity-index legs of this test (ES, NQ) are explicitly
noted in the source literature as showing a *weaker* effect than
commodities/bonds/currencies — going in with a lower prior for ES/NQ than
for GC/CL, not a uniform expectation across all four instruments.

## Exact data source
Databento `GLBX.MDP3`, `statistics` schema (open interest) + `ohlcv-1d`
(price), for ES, NQ, GC, CL continuous front-month contracts (roll rule:
open-interest-based, `.n.0`, per Databento's own continuous-symbology
convention — chosen because it's the rule most consistent with the
open-interest mechanism itself, decided before any data is pulled).

## Exact signal definition
Monthly open interest change: `oi_change = OI[t] - OI[t-21 trading days]`
(≈1 month), expressed as a fraction of `OI[t-21]`, then a 36-month (≈756
trading day) causal rolling z-score — matching the lookback convention
used throughout the COT queue (E19–E26) for cross-candidate comparability.

## Signal availability / no-lookahead
CME statistics data is published same/next business day. Conservative
1-business-day lag: `signal_available_date = date + 1 business day`.

## Expected direction
**Positive** — rising open interest (high z) predicts above-average
forward returns.

## Horizons tested
2 weeks, 4 weeks, 8 weeks — broader than the COT queue's 1/2/4-week set,
matching Hong & Yogo's own ~1-month framing rather than reusing the equity-
positioning queue's horizons by default.

## Instruments
ES primary for Gates 1–5 (per protocol); NQ/GC/CL as Gate 6 generalisation,
tested with identical construction, no re-tuning.

## Falsification criterion
Per `DATABENTO_VALIDATION_PROTOCOL.md` Gate 1: reject if full-history
correlation is not positive and reasonably stable across Discovery/
Validation/Final-OOS.

Locked before any Databento data has been pulled or purchased.
