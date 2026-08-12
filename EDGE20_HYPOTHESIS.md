# Edge #2 (E20) Hypothesis: Yield Curve Slope (10y-3m) → S&P 500 Forward Returns

## Why should this edge exist?
Textbook mechanism: the 10-year minus 3-month Treasury spread is the most
validated recession-lead indicator in the macro literature (inverts before
essentially every US recession since the 1970s). The conventional theoretical
chain: a flat/inverted curve signals the market pricing in future Fed cuts in
response to a weakening economy → embedded recession/growth risk → should
predict below-average subsequent equity returns (risk-off). This is the
consensus *popular and theoretical* direction, pre-registered here as the
prediction before looking at any results.

## Honest counter-evidence (stated up front, per this programme's standing discipline)
This is a case where genuine, credible research argues *against* the
hypothesis holding up empirically, not just an abstract caveat:
- Fama & French found **no evidence that inverted yield curves predict
  stocks will underperform T-bills** across the periods they tested.
- In 10 of 14 historical yield-curve inversions, equity markets were
  **positive 36 months later** — statistically similar to the base rate of
  positive 3-year returns regardless of curve shape.
- Stocks have historically **"done very well" 12 and 24 months after the
  initial inversion** — i.e. if anything, the naive "flat curve = sell" rule
  has a poor empirical track record even though the recession-prediction
  power of the spread itself is real and well-established.
([search synthesis](https://www.dimensional.com/us-en/insights/is-a-yield-curve-inversion-bad-for-stock-returns))

This candidate is entering testing with a real, credible chance of failing —
consistent with going in honestly rather than cherry-picking supportive
priors. Note also this literature is mostly about 12-36 month horizons; this
test uses much shorter horizons (1-4 weeks, for direct comparability with
EDGE19), which is a genuinely different question the cited studies don't
directly answer either way.

## Exact data source
FRED, series `T10Y3M` (10-Year Treasury Constant Maturity minus 3-Month
Treasury Constant Maturity), via the public no-auth CSV export endpoint
`https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y3M` — confirmed
reachable, daily, 1982-01-04 → present.

Price series: same as EDGE19 (Yahoo Finance `^GSPC` for Gate 1/descriptive
work; a costed strategy phase would eventually need real FTMO CFD prices from
Codespace, same caveat as EDGE19).

## Exact signal definition
Causal rolling z-score of the T10Y3M level over a **756-trading-day (~3
calendar year) lookback** — matching EDGE19's ~3-year lookback in spirit
(156 weeks ≈ 756 trading days), for direct cross-candidate comparability
within this research programme, not because 3 years is uniquely justified on
its own for this series.

## Signal availability / no-lookahead
Treasury constant-maturity yields are published same-day. Conservative
1-business-day lag applied regardless: `signal_available_date = FRED
observation_date + 1 business day`. Forward returns measured from the S&P
500 close on the first trading day at or after that date.

## Expected direction
**Negative** correlation between the T10Y3M z-score and forward returns is
the theoretically-motivated prediction being tested — i.e., a flatter/more
inverted curve (low z) should predict *higher* subsequent returns under this
framing is WRONG; restating precisely: **high z-score (steep, normal curve)
predicts positive forward returns; low z-score (flat/inverted curve)
predicts negative/reduced forward returns.** This is committed before
running anything.

## Horizons tested
1 week, 2 weeks, 4 weeks forward return — identical to EDGE19, for direct
comparability, not re-chosen per-candidate.

## Instruments
S&P 500 primary (Gate 1). NAS100/US30/US2000 as a generalization check if
Gate 1 passes — the macro-regime mechanism is arguably universal across US
equity indices, not index-specific, so generalization is economically
justified here (unlike a positioning-specific mechanism).

## Strategy construction (if Gate 1 passes)
Identical methodology to EDGE19 for controlled, consistent comparison across
candidates in this research programme: direction = sign(z-score) [inverted
per the negative-correlation prediction, i.e. long when z is high/steep,
short when z is low/flat-inverted], vol-scaled position sizing (RISK_PCT
convention), same cost table and stress levels. This is a deliberate,
pre-committed methodological choice made before seeing Gate 1 results, not
adapted after the fact to make this candidate easier or harder to pass than
EDGE19 was.

## Period split
Discovery / Validation / Final-OOS at 50th/75th percentile of date, same
method used throughout this research programme.

## Falsification criterion
Same standard as EDGE19: reject at Gate 1 if the full-history correlation is
not in the predicted (negative) direction and reasonably stable across
Discovery/Validation/Final-OOS. A modest-but-genuine effect is not rejected
for being small (per the portfolio-of-edges philosophy) — but a near-zero or
sign-unstable effect, or a positive-sign effect (contradicting the
theoretical prediction, matching what Fama-French actually found), is
rejected exactly as any other failed hypothesis in this programme.

Locked before any correlation has been computed.
