# Edge #4 (E22) Hypothesis: COT Speculator (Non-Commercial) Positioning Extremes → S&P 500 Reversal

## Why should this edge exist?
The classic "fade the crowd" heuristic: non-commercial (leveraged
speculator) positioning is often characterized as trend-following and
sentiment-driven. When speculative positioning becomes extremely one-sided
(crowded), the informal trading heuristic is that the trade is "exhausted"
and due for a reversal — either because there are few remaining buyers/
sellers left to extend the move, or because extreme positioning itself
signals a sentiment extreme rather than new information.

## Honest counter-evidence (stated up front)
This is the **weakest-supported** candidate tested so far in this
sub-programme. Directly cited in `NEW_DATA_SOURCES_INVESTIGATION.md`:
"extreme trader positions (top or bottom 5% of historical net positions) do
not reliably predict price reversals," and position-based sentiment signals
"do not show reliable statistical significance." This candidate is being
tested next only because it was next in the pre-committed ranking from
`NEW_EDGE_CANDIDATES.md`, not because the evidence looks promising — going in
with a real, literature-supported expectation of failure.

## Exact data source
Same as E19: CFTC Socrata API, dataset `jun7-fc8e`, market `S&P 500
Consolidated - CHICAGO MERCANTILE EXCHANGE`, `futonly_or_combined =
'Combined'`. Fields: `noncomm_positions_long_all`,
`noncomm_positions_short_all`, `open_interest_all` (the non-commercial/
speculator category this time, not commercial).

Price series: Yahoo Finance `^GSPC`, same as E19/E20.

## Exact signal definition
`net_noncomm_frac = (noncomm_positions_long_all - noncomm_positions_short_all) / open_interest_all`,
156-week causal rolling z-score — identical construction to E19, different
trader category.

## Signal availability / no-lookahead
Identical to E19: `signal_available_date = report_date + 3 calendar days`.

## Expected direction
**Negative** correlation between the speculator z-score and forward returns
— i.e., extreme speculative long positioning (high z) predicts *below*
-average forward returns (fade the crowd); extreme short positioning (low z)
predicts *above*-average forward returns. This is the mirror-image
prediction to E19's commercial-positioning hypothesis (which predicted
positive correlation for the opposite trader category) — both cannot be
simultaneously "the informed group," which is itself part of why this
candidate is weaker: it requires speculators to be systematically wrong at
extremes, a stronger and less well-supported claim than commercials simply
reflecting real hedging information.

## Horizons tested
1 week, 2 weeks, 4 weeks — identical to E19, for direct comparability.

## Instruments
S&P 500 only for Gate 1 (matching E19's primary-instrument-first approach).

## Falsification criterion
Same standard as prior candidates: reject at Gate 1 if full-history
correlation is not in the predicted (negative) direction and reasonably
stable across Discovery/Validation/Final-OOS. Given the extreme-crowding
framing, the quintile-spread (top20% vs bottom20%) statistic is reported
alongside the linear correlation specifically because a genuine
reversal-at-extremes effect could in principle show up in the tails even
with a weak overall linear correlation — both are reported honestly, neither
is used to rescue the other if one looks bad.

Locked before any correlation has been computed.
