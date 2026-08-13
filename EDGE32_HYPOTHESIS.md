# EDGE32 Hypothesis: Cross-Market Volume-Shock Spillover (NQ Activity → ES Volatility)

Next pre-ranked, genuinely independent Databento hypothesis (H5 from
`DATABENTO_DATA_AUDIT.md`, reformulated to use **pure volume/activity data,
not open interest** — per the explicit steer to avoid another OI variant).
EDGE27/EDGE30 remain permanently REJECTED, not revisited.

## Mechanism (frozen, ex-ante)
An abnormal volume/activity shock in one closely-correlated equity index
future plausibly signals genuine new information or a liquidity-regime
change entering the market. If that information/liquidity shock is
economically real (not instrument-idiosyncratic noise), it should also show
up as elevated *volatility* — not necessarily a directional move — in a
second, closely correlated equity index future shortly after, since both
instruments are exposed to substantially the same underlying risk factors
(broad US equity risk). This is deliberately framed as a **volatility**
target, not a directional one, because there is no principled ex-ante reason
to sign the *direction* of a pure activity shock (unlike EDGE31's
move-confirmation hypothesis, which had a natural direction via the
triggering move itself).

This differs from **EDGE26** (COT trader-concentration → SP500 volatility,
REJECTED): EDGE26 used CFTC trader-count concentration (a positioning-
structure metric); this uses genuine, real-time exchange trading volume in
a *different* instrument, testing spillover, not a same-instrument
structural-crowding story. Different data source, different mechanism.

## Exact instruments
**Leader: NQ. Follower: ES.** Chosen because NQ (Nasdaq-100, higher-beta,
more retail/momentum-influenced) is the more plausible "faster mover" on
fresh information relative to ES (broader, more institutionally-dominated) —
stated as a specific, falsifiable directional choice before testing, not
picked after seeing which pairing "worked." **GC and CL are not used as
leaders** for this specific pairing (no principled reason a commodity
volume shock should spill into equity-index *volatility* specifically,
as opposed to price — that would be a different hypothesis) — this is a
same-asset-class (equity-index-to-equity-index) spillover test only.

## Exact data / construction (frozen)
Daily bars, `databento_ohlcv_1h_v2.csv` (front-month continuous, unaffected
by the OI-specific discontinuity issue found in EDGE27-30).

- `nq_volume_shock_t` = NQ daily volume / trailing 60-day causal rolling
  median NQ daily volume (same "abnormal volume" convention used
  throughout, applied here to the *leader* instrument only).
- **Target**: `es_fwd_vol_h` = realized volatility (std of ES daily log
  returns) over the following `h` trading days from ES's own
  signal-available date.

## Expected direction
**Positive.** Higher NQ volume shock predicts higher subsequent ES realized
volatility.

## Horizons tested
5, 10, 20 trading days.

## No-lookahead
Signal known at close of day `t` (NQ's own volume, already public/settled
by end of day). 1-business-day publish lag before the ES volatility
measurement window begins, consistent with every prior candidate.

## Falsification criterion (Gate 1)
Reject immediately if the full-history correlation between `nq_volume_shock`
and `es_fwd_vol` is not positive and reasonably stable across Discovery/
Validation/Final-OOS.

## Generalisation note
This is inherently a single-pair hypothesis (NQ→ES specifically, motivated
by the stated beta/information-speed argument) — there is no clean symmetric
NQ/GC/CL cross-check the way EDGE27-30's asset-class-general OI hypothesis
had. If Gate 1 passes, the natural robustness check (Gate 6-equivalent) is
the **reverse pairing** (ES volume shock → NQ volatility) to see whether the
directional leader/follower claim is genuinely asymmetric as predicted, not
just a generic "any equity index volume shock predicts any other's vol."

Locked before any correlation has been computed.
