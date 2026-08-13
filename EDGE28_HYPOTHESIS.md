# Edge #9-H2 (E28) Hypothesis: Volume-Conditioned Continuation vs. Reversal

Rank 2 of 3 pre-committed Databento candidates. Tested only if E27 is
rejected, in this order regardless of outcome. Follows
`DATABENTO_VALIDATION_PROTOCOL.md`.

## Why should this edge exist?
Blume, Easley & O'Hara (1994, *Journal of Finance*): trading volume carries
information about signal *quality* that price alone cannot reveal — a
foundational microstructure-theory basis for price-and-volume being jointly
informative. Separately, the abnormal-trading-volume (ATV) literature finds
that price moves on abnormally high volume show strong short-run
continuation, but that continuation itself predicts a *reversal* once
volume normalizes — a genuine two-stage pattern, not a single-horizon
correlation.

## Honest counter-evidence / caveats
The ATV literature's largest cited effects come from equities broadly, not
futures specifically — this is a plausible extension, not a directly
futures-validated result. The two-stage (continuation-then-reversal) shape
means a naive single-horizon Gate 1 correlation could look weak/mixed even
if the underlying phenomenon is real — Gate 1 is explicitly designed below
to check both stages, not just one.

## Exact data source
Databento `GLBX.MDP3`, `ohlcv-1d` (price + real traded volume), ES/NQ/GC/CL
continuous front-month (`.n.0` roll).

## Exact signal definition
`abnormal_volume = volume[t] / rolling_median(volume, 60 trading days)`,
causal. `price_move = daily log return[t]`. Signal = `abnormal_volume ×
sign(price_move)` — i.e., a volume-weighted directional push, high when a
move happens on unusually heavy volume.

## Signal availability / no-lookahead
Signal is fully known at the close of day `t` (uses only data through and
including day `t`). Entry at the next trading day's open-equivalent (first
available price at or after `t + 1 business day`), same lag convention used
throughout this programme.

## Expected direction — two stages, both pre-registered
**Stage A (continuation, short horizon)**: positive correlation between the
signal and forward return at short horizons (3, 5 trading days).
**Stage B (reversal, longer horizon)**: negative correlation (or at minimum,
a decaying/reversing coefficient relative to Stage A) once volume has had
time to normalize, tested at a longer horizon (15, 20 trading days). Both
directions are committed now, before any data is examined — Stage B is not
a fallback invented after Stage A's result is seen.

## Horizons tested
3, 5, 10, 15, 20 trading days — spans both the predicted continuation
window (Stage A) and the predicted reversal window (Stage B), reported for
all horizons without cherry-picking.

## Instruments
ES primary for Gates 1–5; NQ/GC/CL as Gate 6 generalisation, identical
construction.

## Falsification criterion
Reject at Gate 1 if Stage A's short-horizon correlation is not positive and
reasonably stable across Discovery/Validation/Final-OOS. Stage B's reversal
pattern is reported and used to inform Gate 2's strategy design (e.g.
whether a hold-to-exit rule is needed) but a Stage-A pass is the primary
Gate 1 bar — Stage B failing alone does not reject the candidate, since
continuation without measurable reversal is still a usable phenomenon.

Locked before any Databento data has been pulled or purchased.
