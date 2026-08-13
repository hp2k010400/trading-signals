# EDGE31 Hypothesis: Volume Confirmation of Large Price Moves (Informed-Trading Proxy)

Next pre-ranked, genuinely independent Databento hypothesis (H3 from
`DATABENTO_DATA_AUDIT.md`), selected specifically because it uses **pure
exchange volume/participation data — no open interest at all** — a
genuinely different information source from EDGE27–30 (all OI-based).
EDGE30 remains permanently REJECTED, not revisited.

## Mechanism (frozen, ex-ante)
Microstructure theory in the Easley–O'Hara/PIN lineage: a large price move
accompanied by disproportionately high volume plausibly reflects genuine
informed trading (real information being impounded into price), and should
continue; a large move on low/normal volume plausibly reflects a liquidity-
driven or noise-driven move, more likely to revert. This is conceptually
related to but **distinct from EDGE28** (which tested *all* days' abnormal-
volume-weighted moves for continuation/reversal, not conditioned on move
*size*): EDGE31 specifically isolates the subset of already-large moves and
asks whether volume *confirmation* on those specific days predicts what
happens next — an extreme-event-conditional test, not a general day-to-day
relationship.

## Exact instruments
**ES primary** for Gates 1–5. NQ/GC/CL for Gate 6. Per the updated
acceptance criteria: generalization is **expected but not automatically
disqualifying** — the PIN/informed-trading mechanism is a general
microstructure theory with no principled reason to be ES-specific, so if it
fails to generalize that is genuinely informative (unlike EDGE27/30, where
generalization was mandatory because the original hypothesis was framed as
cross-asset from the start). This distinction is stated now, before any
result exists, not decided after seeing which instruments "work."

## Exact data / construction (frozen)
Daily bars (aggregated from `databento_ohlcv_1h_v2.csv`, front-month
continuous — price continuity via front-month is the standard, correct
convention; this is unaffected by the OI roll/discontinuity issues found in
EDGE27–30, which were specific to *open interest*, not price/volume).

- `daily_ret = log(close_t / close_{t-1})`
- `move_pctile_t` = causal rolling percentile rank of `|daily_ret|` over the
  trailing 252 trading days.
- **Large-move day**: `move_pctile_t >= 80` (top quintile of trailing move
  magnitude — a threshold inherent to the hypothesis itself, defining what
  "large" means, not a post-hoc rescue parameter).
- `volume_pctile_t` = causal rolling percentile rank of daily volume over
  the trailing 252 trading days.
- **Signal** (defined only on large-move days): `volume_pctile_t` itself,
  continuous.
- **Target**: `fwd_ret_signed_h = sign(daily_ret_t) * log(close_{t+h} / close_t)`
  — does the original move's direction continue?

## Expected direction
**Positive.** Higher volume confirmation on a large-move day (`volume_pctile`)
predicts more continuation in the original move's direction
(`fwd_ret_signed` positive and larger).

## Horizons tested
5, 10, 20 trading days — tested broadly, none pre-selected as "the best."

## No-lookahead
Signal fully known at close of day `t` (uses only that day's own
volume/return and trailing history). 1-business-day publish lag applied
before entry, consistent with every prior candidate.

## Falsification criterion (Gate 1)
Reject immediately if the full-history correlation between `volume_pctile`
and `fwd_ret_signed` (restricted to large-move days) is not positive and
reasonably stable across Discovery/Validation/Final-OOS. A modest, genuine
effect (per the updated portfolio-of-edges standard) is not rejected for
being small — but a near-zero, sign-unstable, or single-period-concentrated
effect is rejected exactly as every other failed candidate this session.

Locked before any correlation has been computed.
