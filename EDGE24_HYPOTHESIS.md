# Edge #6 (E24) Hypothesis: COT Commercial Positioning Divergence → NAS100 vs SP500 Relative Value

## Why should this edge exist?
A structurally different construction from E19/E22/E23: **relative value**
(long one index, short a correlated other) rather than a symmetric
directional bet on a single trending index. NAS100 and SP500 are two highly
correlated US equity index futures (E19's generalization check showed
correlated but non-identical commercial-positioning dynamics). If commercial
(hedger) positioning in one diverges from the other relative to their
historical relationship, that divergence may predict a subsequent
*relative* (not absolute) return: NAS100 outperforming/underperforming
SP500. Being long one and short the other largely cancels the common equity
market drift that sank E19 and E22 at Gates 2-7 — this is a genuine
structural difference in the strategy construction, motivated by that
observed failure mode, not a modification of either rejected edge.

This also revisits the same instrument pair space as `E05` (cointegrated
index spreads, rejected — no formal cointegration found in NAS100-SP500
price spread), but with a **genuinely different information layer**
(positioning, not price) — explicitly the kind of "same pair, new
information source" test flagged as worth trying in
`ALPHA05_LITERATURE.md`/`NEW_EDGE_CANDIDATES.md`.

## Exact data source
CFTC Socrata API, same as E19, for both `S&P 500 Consolidated` and
`NASDAQ-100 Consolidated` (both `CHICAGO MERCANTILE EXCHANGE`, `Combined`).
Commercial category (`comm_positions_long_all`, `comm_positions_short_all`,
`open_interest_all`) — same trader category as E19, for theoretical
consistency with the original hedging-information mechanism, not chosen
because it performed better in unrelated tests.

Price series: Yahoo Finance `^NDX` (NAS100) and `^GSPC` (SP500).

## Exact signal definition
`net_comm_frac` computed separately for each instrument (as in E19), then
`divergence = net_comm_frac_NAS100 - net_comm_frac_SP500`, then a 156-week
causal rolling z-score of `divergence`.

## Signal availability / no-lookahead
Identical to E19: `signal_available_date = report_date + 3 calendar days`
(both series share the same weekly CFTC report date).

## Expected direction
**Positive.** NAS100 commercial positioning becoming relatively more bullish
than SP500's (high z) predicts NAS100 *outperforming* SP500 (positive
relative return = log(NAS100 fwd) − log(SP500 fwd)) going forward.

## Horizons tested
1 week, 2 weeks, 4 weeks — identical to E19 for comparability.

## Strategy construction (if Gate 1 passes)
Long NAS100 / short SP500 (or reverse) sized to be dollar/vol-neutral
between the two legs, direction = sign(z) applied to the pair as a unit —
this is a genuine methodological difference from E19/E22 (paired relative-
value position, not a single-instrument symmetric long/short), motivated
by the pre-registered relative-value mechanism itself, decided before
running Gate 1.

## Falsification criterion
Same standard: reject at Gate 1 if full-history correlation (divergence
z-score vs. relative forward return) is not positive and reasonably stable
across Discovery/Validation/Final-OOS.

Locked before any correlation has been computed.
