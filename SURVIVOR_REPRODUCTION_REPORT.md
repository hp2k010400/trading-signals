# Survivor Reproduction Report

**Phase 1 of the post-mortem research directive.** Independent code audit of the two
surviving strategies (AUD/USD cross-pair mean reversion, Time-Series Momentum) before
any further validation work proceeds on top of them. Previous code was NOT assumed
correct — read in full, checked line by line against the audit checklist below.

Date: 2026-08-12

---

## 1. AUD/USD Cross-Pair Strategy (`lesser_traded_pairs_ftmo.py`)

### Findings

| Item | Status | Notes |
|---|---|---|
| Data / timestamps | OK | Broker UTC+3 offset confirmed directly against MT5 (`TimeCurrent()-TimeGMT()`) earlier in this research programme, not assumed. |
| Signal generation / lookahead | OK | Z-score at day `i` uses `rolling().sum()`/`rolling().mean()`/`rolling().std()` of returns through day `i` only (pandas default right-aligned window). Entry executes at day `i+1`'s **open** — decision made on day `i`'s close-derived signal, executed the next day. No lookahead. |
| Same-day exit logic | OK, but worth naming | A position entered at day D's open can exit the same day D at that day's **close**, if the z-score (computed from day D's close) has reverted below `EXIT_Z`. This uses information from later in day D (the close) than the entry (the open) to make a same-day exit decision — realistic, not lookahead, but worth stating explicitly since it's a less common pattern than next-day-only exits. |
| **Cost realism** | **BUG — FIXED** | Every other script in this research programme applies a 1.5x stress multiplier (`COST_MULT`) to real spread costs. This script never did — `cost_r` was computed on raw, un-stressed cost estimates while every other strategy was held to the conservative standard. Fixed: added `COST_MULT = 1.5`, applied to `cost_r`. **All previously reported PF figures for this strategy (full-history PF 1.70, holdout PF 7.03) were computed under this inconsistency and must be re-run.** |
| Position sizing / normalization | OK | R normalized by `spread_std` at entry (fixed for the life of the trade), matching the same denominator used to define the entry z-score. Reasonable, standard practice. |
| Overlapping trades — within a pair | OK | Single `state` variable per pair; a new entry cannot occur while `state is not None`. Correctly serialized. |
| Overlapping trades — across pairs | **Not a bug, but a real structural note** | `AUDCAD` appears in both `AUDCAD/AUDCHF` and `AUDNZD/AUDCAD`. Nothing prevents simultaneously holding opposing exposure to AUDCAD via two different pair trades at once. The R-multiple math for each pair is independently correct, but the 4 "independent" pairs are **not fully diversified from one another** — some of their returns share a common underlying instrument. This matters for portfolio-level risk sizing (Phase 12) and should not be treated as 4 uncorrelated return streams. |
| Leverage / margin | Not modeled | Position sizing is purely R-multiple × equity fraction; no explicit check that the implied notional is affordable under real margin requirements. Low risk given 0.30% risk/trade is conservative, but unmodeled. |
| Cost calibration | **Known, already-flagged limitation** | `COST_POINTS` for all 5 lesser-traded FX crosses are explicitly documented as uncalibrated estimates — never pulled from live MT5 Market Watch. This was already acknowledged in the code comments; restating here because it directly bears on how much to trust the PF magnitude (not just its sign).|
| Survivorship / scope | Note | The 5 instruments tested (AUDNZD, AUDCAD, AUDCHF, USDCHF, USDCAD) were chosen because they had real long-history data available and shared a currency leg — not because every possible FX cross was tested and these were the survivors. This is a scoped hypothesis test, not a scan of the full cross universe. Relevant to Phase 9/10 (does the mechanism generalize to more pairs).|
| Selection/holdout sample size | **Already flagged, restated for the record** | The most recent real run selected 3 pairs and produced a holdout of only **N=20 trades** — far below the script's own 80-trade reliability warning threshold. PF values as extreme as 10-14 on individual pairs in that holdout are small-sample artifacts, not trustworthy point estimates. This is exactly why Phase 6 (multi-period OOS) matters more here than almost anywhere else in this research programme. |

### Reproducibility verdict
**Reproducible in mechanism, but the previously reported PF numbers are invalid** due to
the missing cost multiplier. Must be re-run with the fix before being used as a baseline
for any further phase.

---

## 2. Time-Series Momentum (`time_series_momentum_ftmo.py`)

### Findings

| Item | Status | Notes |
|---|---|---|
| Data / timestamps | OK | Same confirmed UTC+3 offset. |
| **Signal generation / lookahead** | **BUG — FIXED** | `trail_ret` at row `i` was `log(close[i] / close[i-252])` — using **that row's own closing price**. `find_trades()` enters the position at `daily['open'].iloc[i]` — **the opening price of that same row**. This is a genuine lookahead: the entry decision (executed at day `i`'s open) was conditioned on information (day `i`'s close) that does not exist yet at the moment of entry. Fixed by shifting both `trail_ret` and `vol20` by one additional day, so the signal acted on at day `i`'s open reflects only information through day `i-1`'s close. |
| Execution (exit) | OK | Exits at the next rebalance date's open — consistent with entering the next position at the same time (implicit rollover), not a separate bug. |
| Cost realism | OK | `COST_MULT = 1.5` correctly applied, unlike the pairs script (see above). |
| Position sizing | OK, faithful to source | Inverse-volatility scaling (`period_vol = vol × sqrt(holding_days)`), matching the original Moskowitz/Ooi/Pedersen methodology's stated approach, not a simplification. |
| Overlapping trades — within an instrument | OK | Sequential loop over `rebalance_positions`, one position at a time per instrument. |
| Overlapping trades — across instruments | By design, not a bug | Multiple instruments hold simultaneous positions — this is a portfolio strategy. Directly relevant to Phase 3's question of whether the edge is genuine trend persistence or a diversification/portfolio-construction effect — not resolved by this audit, flagged for Phase 3. |
| Leverage / margin | Not modeled | Same as pairs script. |
| Survivorship / universe scope | Note | 27 instruments = everything collected during this research programme (majors + keyword-search-discovered indices/commodities), not an exhaustive scan of everything FTMO offers. The universe itself has a collection boundary. |
| Selection/holdout | Already flagged by the user, correctly | Only ONE holdout window (2025-01-01 onward) has been tested. This is the central gap Phases 6-7 are designed to close. |

### Reproducibility verdict
**Not reproducible as previously reported** — the lookahead bug means the previously
quoted PF 1.47 holdout result was generated by a backtest that could not have been
traded in real time. The magnitude of the bug's impact is unknown until re-run (a
252-day trailing-return signal is unlikely to flip sign from a single day's difference
most of the time, so the impact may be small — but "likely small" is a hypothesis to
verify, not an assumption, consistent with the standard applied to every other result
in this research programme).

---

## 3. Required Next Action

Both fixes are committed and pushed. **Both scripts must be re-run on real data before
any subsequent phase (ablation, multi-period OOS, permutation testing) uses their
output as a baseline.** Proceeding with the old numbers would mean building six more
layers of validation on top of results already known to be wrong.
