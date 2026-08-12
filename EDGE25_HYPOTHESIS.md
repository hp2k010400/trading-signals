# Edge #7 (E25) Hypothesis: Gold Speculator Positioning (Risk-Sentiment Proxy) → S&P 500 Forward Returns

## Why should this edge exist?
Cross-asset mechanism: gold is a classic "fear gauge" / safe-haven asset.
Extreme speculative (non-commercial) net-long positioning in gold futures
may reflect elevated risk aversion in the broader market — a real,
economically distinct signal from the SP500's own positioning (unlike
E19/E22/E23/E24, which all used SP500's or a correlated index's own
positioning). If risk aversion measured via gold-market flows is genuinely
informative about broad risk sentiment, that should predict *equity*
returns, not just gold's own.

## Honest counter-evidence
No direct citation for this specific combination was found in
`ALPHA_DATA_SOURCES` research (`NEW_EDGE_CANDIDATES.md` flagged this as
"more speculative mechanism," no direct empirical citation, unlike E19's or
E21's more literature-grounded mechanisms). This is a plausibility-argument
hypothesis, not one with a specific prior study behind it — going in with
correspondingly moderate confidence.

## Exact data source
CFTC Socrata API, market `GOLD - COMMODITY EXCHANGE INC.`, `Combined`.
Non-commercial category (`noncomm_positions_long_all`,
`noncomm_positions_short_all`, `open_interest_all`) — speculative
positioning, matching the "fear gauge" framing (retail/fund flows into gold
as a sentiment indicator, not hedgers' economic positioning).

Price series: Yahoo Finance `^GSPC` (S&P 500), same as E19/E20/E22/E23.

## Exact signal definition
`net_noncomm_frac_gold = (noncomm_positions_long_all - noncomm_positions_short_all) / open_interest_all`,
156-week causal rolling z-score — identical construction convention to
E19/E22/E23, applied to gold's own positioning instead of SP500's.

## Signal availability / no-lookahead
Identical to E19: `signal_available_date = report_date + 3 calendar days`.

## Expected direction
**Negative.** Extreme gold speculative long positioning (high z, elevated
fear/risk-aversion) predicts *below*-average forward S&P 500 returns
(risk-off spillover into equities).

## Horizons tested
1 week, 2 weeks, 4 weeks — identical to prior candidates.

## Falsification criterion
Same standard: reject at Gate 1 if full-history correlation is not negative
and reasonably stable across Discovery/Validation/Final-OOS.

Locked before any correlation has been computed.
