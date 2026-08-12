# Edge #8 (E26) Hypothesis: COT Top-4 Trader Concentration → S&P 500 Forward Volatility

## Why should this edge exist?
Different target variable from every other candidate in this queue: this is
naturally a **fragility/crowding-risk** mechanism, not a directional one. If
a small number of large traders (top-4 by CFTC's own concentration metric)
hold an outsized share of gross positioning, a forced unwind (margin call,
risk-limit breach, single large fund de-risking) could trigger
outsized price moves. The natural, economically correct target is
**subsequent realized volatility**, not direction — forcing this into a
directional-return-correlation format (as all other candidates in this
queue used) would be testing the wrong thing for this specific mechanism.

## Honest counter-evidence
Flagged in `NEW_EDGE_CANDIDATES.md` from the start as the weakest-fit
candidate: concentration metrics are standard for exchange risk/margin
monitoring, not the standard use case in the return/volatility-prediction
literature. No direct citation found supporting concentration-predicts-
volatility specifically for equity index futures.

## Exact data source
CFTC Socrata API, `S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE`,
`Combined`. Fields: `conc_gross_le_4_tdr_long`, `conc_gross_le_4_tdr_short`
(top-4 trader gross concentration, % of open interest, each side).

Price series: Yahoo Finance `^GSPC`, same as prior SP500-based candidates.

## Exact signal definition
`concentration = conc_gross_le_4_tdr_long + conc_gross_le_4_tdr_short`
(combined gross concentration, both sides), 156-week causal rolling
z-score — same lookback convention as prior candidates.

## Target variable (not forward RETURN — forward REALIZED VOLATILITY)
`fwd_vol_h = std(daily log returns over the h-week forward window)`,
computed from the same signal-available-date entry point used throughout
this queue (`report_date + 3 calendar days`).

## Expected direction
**Positive.** Higher concentration (high z) predicts higher subsequent
realized volatility.

## Horizons tested
1 week, 2 weeks, 4 weeks — same convention as prior candidates.

## Falsification criterion
Reject at Gate 1 if full-history correlation (concentration z-score vs.
forward realized volatility) is not positive and reasonably stable across
Discovery/Validation/Final-OOS. Note: even if this clears Gate 1, it would
NOT be directly executable as a directional trading strategy the way other
candidates are — a volatility-prediction edge would need a genuinely
different Gate 2 construction (e.g. options, or a volatility-scaled
position-sizing overlay rather than a directional bet) — that design
question is deferred until/unless Gate 1 actually passes, not decided now.

Locked before any correlation has been computed.
