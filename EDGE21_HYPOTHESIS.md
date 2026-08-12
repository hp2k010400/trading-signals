# Edge #3 (E21) Hypothesis: Interest Rate Differential (Carry) → AUDCAD / AUDNZD Forward Returns

## Why should this edge exist?
Uncovered Interest Rate Parity (UIP) theoretically predicts a higher-rate
currency should depreciate by enough to equalize expected returns across
currencies. Empirically, UIP fails persistently — this is the "forward
premium puzzle" (Fama 1984), one of the most replicated anomalies in
international finance: currencies with higher interest rates tend to **not**
depreciate as much as parity predicts, and often appreciate instead. This is
the economic basis of the "carry trade." Unlike the yield-curve candidate
(E20), this mechanism has decades of consistent, mainstream academic support
— though the well-documented risk is negative skew / crash risk (carry
trades grind out small gains then suffer sharp losses during risk-off
episodes), which the descriptive Gate 1 test won't capture directly but
should be kept in mind for Gate 4/6.

## Who is paying us / what risk are we compensated for?
Classic explanation: compensation for bearing crash/liquidity risk that
materializes during global risk-off episodes — carry trades are a
short-vol-like exposure. A genuine risk premium, not a free lunch.

## Exact data sources
- **AU 3-month interbank rate**: FRED `IR3TIB01AUM156N`, monthly, confirmed
  reachable, 1968-01 → 2026-06.
- **NZ 3-month interbank rate**: FRED `IR3TIB01NZM156N`, monthly, confirmed
  reachable, 1973-12 → 2026-06.
- **CA 3-month interbank rate**: FRED `IR3TIB01CAM156N`, monthly, confirmed
  reachable, 1956-01 → 2026-06.
- **Price data**: Yahoo Finance `AUDCAD=X` and `AUDNZD=X`, confirmed
  reachable, daily, 2003-12 → present.

## Exact signal definition
`diff_AUDCAD = AU_rate - CA_rate`, `diff_AUDNZD = AU_rate - NZ_rate`, each as
a rolling 36-month causal z-score (matching the ~3-year lookback convention
used in E19/E20, adapted to monthly frequency since that's this data's
native granularity — not an arbitrary re-choice).

## Signal availability / no-lookahead
OECD-sourced monthly rate series carry real publication lag. Conservative
45-day lag applied: `signal_available_date = month-end of the rate
observation + 45 days`.

## Expected direction
**Positive.** Higher AU rate relative to CA (or NZ) — i.e., a positive,
above-average differential — predicts AUD *appreciation* against that
currency (AUDCAD / AUDNZD rising), per the carry-trade/forward-premium-puzzle
literature. Committed before running anything.

## Horizons tested
1 month, 2 months, 3 months forward return — scaled to the signal's monthly
native frequency (analogous role to E19/E20's 1/2/4-week horizons, adapted
because this data updates monthly, not weekly/daily).

## Instruments
AUDCAD and AUDNZD, tested and reported **separately** (not pooled) — they
share the AUD leg, so results will be correlated, but the CAD/NZD legs are
genuinely different currencies with different economic drivers, and pooling
them would obscure whether the effect is a general carry phenomenon or
specific to one cross.

## Strategy construction (if Gate 1 passes)
Same controlled methodology as E19/E20: direction = sign(z), vol-scaled
position sizing (RISK_PCT convention), same cost-stress framework
(AUDCAD/AUDNZD cost points already established at 0.0004 in this research
programme's cost table).

## Period split
Discovery / Validation / Final-OOS at 50th/75th percentile of date, same
method throughout.

## Falsification criterion
Same standard as E19/E20: reject at Gate 1 if full-history correlation is
not positive and reasonably stable across Discovery/Validation/Final-OOS. A
modest genuine effect is acceptable (portfolio-of-edges philosophy); a
near-zero, sign-unstable, or wrong-signed effect is rejected.

Locked before any correlation has been computed.
