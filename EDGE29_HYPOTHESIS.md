# Edge #9-H3 (E29) Hypothesis: Volume/Open-Interest Turnover Ratio

Rank 3 of 3 pre-committed Databento candidates. Tested only if both E27 and
E28 are rejected, in this order regardless of outcome. Follows
`DATABENTO_VALIDATION_PROTOCOL.md`.

## Why should this edge exist?
Volume relative to *outstanding* open interest ("turnover" — how much of
the existing position base is being actively traded) is a genuinely
distinct construct from E27 (OI level/change alone) or E28 (volume alone):
it captures position *churn*. High turnover could reflect information-
driven repositioning (bullish, per Blume-Easley-O'Hara's information-
quality framing) or capitulation/panic (contrarian). No single direct
citation for this exact ratio-as-predictor was found in the literature
search behind `DATABENTO_DATA_AUDIT.md` — this is a principled combination
of E27/E28's underlying theories, tested with a correspondingly weaker
evidentiary prior than either of them individually.

## Exact data source
Databento `GLBX.MDP3`, `ohlcv-1d` (volume) + `statistics` (open interest),
ES/NQ/GC/CL continuous front-month (`.n.0` roll).

## Exact signal definition
`turnover = volume[t] / OI[t]`, then a 36-month (≈756 trading day) causal
rolling z-score of `turnover` — same lookback convention as E27/E22/E19 for
cross-candidate comparability.

## Signal availability / no-lookahead
Same 1-business-day lag as E27 (statistics data publish timing governs
here, since OI is the slower-updating of the two inputs).

## Expected direction
**Positive** — elevated turnover (high z) predicts above-average forward
returns, per the information-driven-repositioning framing (chosen, per the
audit's own note, as the single pre-committed direction rather than testing
both bullish and contrarian framings and picking whichever the data
supports — that would be exactly the kind of post-hoc direction selection
this programme's discipline exists to prevent).

## Horizons tested
5, 10, 20 trading days — matching a short-to-medium framing between E27's
monthly horizon and E28's short-horizon continuation test.

## Instruments
ES primary for Gates 1–5; NQ/GC/CL as Gate 6 generalisation, identical
construction.

## Falsification criterion
Reject at Gate 1 if full-history correlation is not positive and reasonably
stable across Discovery/Validation/Final-OOS.

Locked before any Databento data has been pulled or purchased.
