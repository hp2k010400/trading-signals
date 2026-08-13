# EDGE30: ES Open Interest — Pre-Registration

Frozen per `ES_OI_MECHANISM_REVIEW.md` (Phase 1: credible mechanism
established) and `ES_OI_DATA_CONTAMINATION.md` (Phases 2–3: 2010–2026 is
contaminated by direct prior observation; no already-available genuinely
independent dataset exists; forward collection is the only unambiguously
clean validation path). This is a **new, independent hypothesis** — E27
remains permanently REJECTED and is not being modified, revisited, or
rescued by anything below.

## Design principle (Phase 5 compliance)
Every parameter below is chosen for a reason stated *before* any EDGE30
result exists, independent of E27's observed 8-week / 756-day / ES-only
findings. Where a choice could plausibly be suspected of being backed into
from E27's numbers, the simpler or literature-derived alternative was taken
instead, and the reasoning is stated explicitly.

## Exact OI calculation
**Total open interest, summed across all active ES contract months**
(Databento `GLBX.MDP3`, `statistics` schema, `stat_type=9`, `stype_in=parent`,
symbol `ES.FUT`) — not the single front-month label E27 used. This directly
fixes the roll-artifact contamination documented in
`ES_OI_DATA_CONTAMINATION.md` §3. Chosen because it is the methodologically
correct construction, not because of anything about E27's performance.

## Exact signal direction
**Positive.** Same theoretical direction as E27 (rising aggregate OI reflects
increased institutional commitment / reduced risk-absorption slack, per
`ES_OI_MECHANISM_REVIEW.md`) — this is a property of the *mechanism*, not of
E27's specific result, so it is legitimately carried forward unchanged.

## Exact lookback (z-score standardization window)
**Expanding window** (all available history up to and including the
signal date), not a fixed rolling window. This is a deliberate, more
conservative choice than E27's 756-day rolling window specifically *because*
756 days was observed (in the Gate 7 sweep) to sit inside a stable-looking
plateau — reusing any fixed value from that sweep, however "reasonable" it
looks, would be exactly the re-selection Phase 5 prohibits. An expanding
window has no free lookback parameter to (consciously or not) back into.

## Exact entry / exit / holding period
Signal computed from total OI as of the close of day `t`. **1-business-day
publish lag** (unchanged from E27 — this is a data-availability constant,
not a tuned parameter, so carrying it forward is not a Phase 5 violation).
Entry at the close of day `t+1` (first trading day at or after the lag).
**Holding period: 1 calendar month**, matching Hong & Yogo's own primary
specification (`ES_OI_MECHANISM_REVIEW.md` §2) directly — chosen from the
cited literature, not from E27's 8-week finding (E27 tested 2/4/8-week
horizons; 1 month is a different, literature-anchored choice, not a
re-selection from that set).

## Exact position sizing
Vol-scaled sizing, `RISK_PCT = 0.30%` of equity per trade — the same
convention used across this entire research programme (E19 through E29),
kept for cross-candidate comparability, not because of anything specific to
E27's ES result.

## Exact costs
Same standing convention: `COST_POINTS['ES'] = 0.6` (confirmed FTMO-CFD-
equivalent spread, already established), `BASE_COST_MULT = 1.5`, stress
levels `1.0 / 1.2 / 1.5 / 2.0` on top of base (Phase 10).

## Exact execution timing / no-lookahead
Identical discipline to every prior candidate: signal must only use OI data
whose `ts_event` (message publish time) is at or before the signal date,
with the 1-business-day lag applied on top as a conservative buffer beyond
that. To be explicitly re-verified against the corrected (parent-symbology,
summed) data before any test runs, not assumed to carry over automatically
from E27's front-month construction.

## Exact validation dataset — this is the central, non-negotiable point of this pre-registration
**Primary validation: forward data only, from 2026-08-13 onward** (today,
the date this pre-registration is frozen). This is the only dataset
identified in Phase 3 that is genuinely, unambiguously independent of
everything already observed. **No test of EDGE30 will be described as
"validation" or used for a VALIDATED classification unless it runs on data
from this date forward.**

A **separate, explicitly-labeled, non-validating sanity check** may
optionally be run on the existing 2010–2026 window using the corrected
(total-OI, expanding-window) construction — solely to confirm the corrected
signal isn't obviously broken, reversed, or degenerate. Any such check:
- Must be labeled "SANITY CHECK — NOT VALIDATION" in every output.
- Cannot by itself upgrade EDGE30 past WATCHLIST, regardless of result.
- Must be interpreted through the Phase 13 multiple-testing / false-discovery
  lens (this ES window has already motivated one follow-up hypothesis; a
  second pass at the same window is even weaker evidence than the first).

## Exact statistical tests
Pearson and Spearman correlation (Phase 6), block-bootstrap or
circular-shift permutation preserving autocorrelation (Phase 8, pre-
specified as the circular-shift method used throughout this programme,
not switched later if it doesn't pass), parameter robustness across a
small pre-specified neighboring set (Phase 9: e.g. 1/2/3-month holding
periods, not re-optimized after seeing results), cost stress (Phase 10),
temporal-robustness by year/regime (Phase 11), and an explicit equity-
drift control (Phase 12: strategy return vs. buy-and-hold ES and vs.
matched random-entry/similar-net-exposure benchmarks).

## Exact acceptance / rejection criteria
Per the classification rules already specified in the directive:
`VALIDATED_SMALL_EDGE` requires genuine forward (not same-window) evidence,
no lookahead/timing problem, positive net expectancy, temporal robustness
not dependent on one period/regime, an edge that survives the equity-drift
control, a reasonable parameter plateau, survival of realistic costs, and
evidence materially stronger than chance — with PF magnitude explicitly
*not* the deciding factor either way. Failing any one of these on the
forward dataset is a permanent REJECTED, not a WATCHLIST or a retry.

## Status
**Frozen. No test has been run under this pre-registration.** Per
instruction, EDGE30 does not proceed to Phase 5+ execution until directed —
and given Phase 3's own conclusion, genuine validation requires either (a)
waiting for forward ES data to accumulate, or (b) explicit authorization to
run the clearly-labeled, non-validating sanity check on the old window in
the meantime. This choice is not made unilaterally here — flagged back for
direction.
