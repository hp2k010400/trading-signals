# Edge #1 (E19) Hypothesis: COT Commercial Net Positioning → S&P 500 Forward Returns

## Why should this edge exist?
Commercial traders on CFTC reports are entities using futures to hedge real
economic exposure (as opposed to leveraged speculators). For a financial
index future like the S&P 500, "commercial" in practice captures dealers,
broker-dealers, and institutions running hedging books against real cash
positions. The literature's proposed mechanism: this group either (a) has
genuine informational advantages from being closer to real economic activity
than pure speculators, or (b) mechanically absorbs speculative excess by
selling into strength / buying into weakness as part of routine hedging flow,
which can itself create a statistical pattern even without an information
edge per se. Either mechanism is a real, economically grounded story — not
"pattern in price that happened to work."

## Who is paying us / what risk are we compensated for?
If real: either a genuine information rent (commercials know something
before it's in the price) or a liquidity-provision rent (commercials are
compensated for absorbing order-flow imbalance that speculators create).

## Honest counter-evidence (stated up front, not discovered after testing)
Directly contradicting research exists: "no consistent evidence that trader
positions predict future market returns," and extreme positioning specifically
does not reliably predict reversals (cited in `NEW_DATA_SOURCES_INVESTIGATION.md`).
This hypothesis is going in with a real chance of failing, and that's an
accepted, expected possible outcome — not something to torture the data to
avoid.

## Exact data source
CFTC Public Reporting Socrata API, dataset `jun7-fc8e`, market
`market_and_exchange_names = 'S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE'`,
`futonly_or_combined = 'Combined'` (the only variant this dataset publishes
for this market — confirmed via direct query, no ambiguity/choice involved).
Fields used: `report_date_as_yyyy_mm_dd`, `comm_positions_long_all`,
`comm_positions_short_all`, `open_interest_all`.
Available range confirmed: 2010-06-15 → present, weekly.

Price series: Yahoo Finance `^GSPC` (S&P 500 index), daily close, via the
public chart API — used for the descriptive/Gate-1 test only. (A costed
strategy phase, if this reaches that stage, would need to switch to the real
FTMO SP500 CFD price series from Codespace for realistic execution/cost
modeling — noted now so it isn't forgotten later, not treated as
interchangeable with the index-level series used here.)

## Exact signal definition
`net_comm = comm_positions_long_all - comm_positions_short_all`, expressed as
a fraction of `open_interest_all` (to normalize for open interest growing
substantially over 16 years): `net_comm_frac = net_comm / open_interest_all`.
Signal = the trailing z-score of `net_comm_frac` over a 156-week (3-year)
rolling lookback, computed causally (only using data up to and including the
current report).

## Signal availability / no-lookahead
CFTC publishes the report ~3 days after `report_date` (Tuesday data,
published Friday). `signal_available_date = report_date + 3 calendar days`.
Forward returns are measured from the S&P 500 close on the first trading day
at or after `signal_available_date` — not from `report_date` itself, which
would be a lookahead violation.

## Expected direction
Per the hedging-informed / liquidity-provision mechanism: commercials are
conventionally net SHORT equity index futures on average (using futures to
hedge long cash equity exposure), so the hypothesis is framed on the
DEVIATION from their normal net-short baseline, not the raw sign. Expected
direction: when commercial net positioning is *less short than usual* (high
z-score, i.e., unwinding hedges / turning relatively bullish), that's the
hypothesized bullish signal — i.e., we predict **positive correlation between
net_comm z-score and forward S&P 500 returns.** This is a genuine directional
prediction made before looking at any results, not a placeholder to be
flipped after seeing the sign.

## Horizons tested (broad, not optimized for the best one)
1 week, 2 weeks, 4 weeks forward return from `signal_available_date`.

## Instruments
S&P 500 only for Gate 1. If the phenomenon survives Gate 1, NAS100/US30/
US2000 (all CFTC-covered) get tested as a generalization check per Gate 4/7 —
not folded into Gate 1 to avoid diluting a clean first read with multiple
instruments' worth of researcher choices.

## Period split
Discovery / Validation / Final-OOS at the 50th/75th percentile of
`report_date` by calendar time, computed over the full 2010-2026 available
range — identical method to every prior alpha0X hypothesis this research
programme.

## Falsification criterion
If the full-history correlation is not positive and stable in sign across
Discovery/Validation/Final-OOS (allowing the same "not concentrated in one
period" standard used throughout this programme, not requiring literally all
three positive), REJECT at Gate 1. Given the new portfolio philosophy, a
small-but-genuine effect (e.g. modest correlation, positive but unexciting
quintile spread) is NOT automatically rejected for being unspectacular — but
a near-zero or sign-unstable effect is rejected exactly as alpha04/05/06 were.

This is locked before any correlation has been computed.
