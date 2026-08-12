# Tick Data Collection Guide

This is infrastructure, not a strategy. The point of this phase is to build a
trustworthy, genuinely higher-information dataset (real tick arrival times,
bid/ask, tick volume, trade-direction flags) before asking whether it
contains any tradeable signal — per the directive that closed out the
alpha02–alpha06 OHLC-based research programme. **Do not strategy-mine this
data yet.**

## 1. Compiling and attaching `TickExporter.mq5`

1. Copy `TickExporter.mq5` into your MT5 data folder's `MQL5\Experts\`
   directory (same folder the existing EAs like `SignalBotEA.mq5` live in).
2. Compile it in MetaEditor (F7). It has no external dependencies.
3. **Open one chart per instrument you want tick data for, and attach a
   separate instance of the EA to each chart.** This is not optional — MT5's
   `OnTick()` only fires for the symbol the chart/EA is actually watching.
   Trying to cover many symbols from one EA on a timer would silently miss
   ticks between polls, which defeats the entire point of collecting
   tick-level data instead of M1 bars.
4. Enable AutoTrading / algo trading in the terminal (the EA doesn't place
   any trades, but MT5 still gates `OnTick()`/file I/O behind that toggle).
5. Confirm it's running: each chart should show a smiley-face EA icon, and
   the "Experts" log tab should show `TickExporter started on <SYMBOL>`.

### Recommended starting symbol list

Start with the same 13-instrument core universe used throughout the
alpha02–alpha06 research (keeps broker/VPS load manageable, and keeps the
new tick data directly comparable to the existing OHLC-based findings):

```
GER40.cash  US100.cash  US500.cash  US30.cash  UK100.cash  FRA40.cash
JP225.cash  AUS200.cash EU50.cash   US2000.cash HK50.cash  AUDCAD  AUDNZD
```

(Use whatever exact symbol names your Market Watch shows — check against
`FILES` in `alpha02_strategy_ftmo.py` / `alpha06_liquidity_descriptive_ftmo.py`
if unsure of the naming convention this broker uses.)

## 2. Uptime matters — this is fundamentally different from the M1 bulk exports

The previous exporters (`ExportM1Data.mq5` etc.) pulled bulk *historical*
data from the broker in one shot — the terminal only needed to be open for a
few seconds. **Tick collection only captures ticks while the terminal is
open, connected, and the EA is running.** If the terminal is closed
overnight or the PC sleeps, that period's ticks are gone — there's no way to
backfill them later (real tick-level history isn't retrievable from MT5 the
way M1 bars are). If continuous, uninterrupted collection matters (and for
building a trustworthy dataset, it does), running this on a VPS or a machine
that stays on is worth doing rather than relying on a laptop that sleeps.
This is exactly the kind of gap the quality validator (`tick_data_quality
_validator.py`) is designed to surface, not something to just hope doesn't
happen.

## 3. Where the data lands, and getting it into the repo

Files are written to:
```
<MT5 data folder>\MQL5\Files\ticks_<SYMBOL>_<YYYYMMDD>.csv
```
One CSV per symbol per broker-server calendar day (new file at each day
rollover; safely append-only within a day, so terminal/EA restarts mid-day
don't lose or duplicate the day's data). Columns: `time, time_msc, bid, ask,
last, volume, volume_real, spread_price, flags, flags_decoded, symbol`.

Periodically (weekly is a reasonable cadence) copy the accumulated
`ticks_*.csv` files into the `trading-signals` repo root (or wherever you run
the validator/Codespace from), then run:

```
python -u tick_data_quality_validator.py
```

This produces `TICK_DATA_QUALITY_REPORT.md` and `TICK_DATA_MANIFEST.csv` —
review the report for flagged weekday gaps, negative spreads, flatline runs,
and abnormal jumps before trusting any given stretch of data. It's safe to
run repeatedly as more files accumulate; it always rescans everything found.

Given file volume (a single liquid index can produce tens of thousands of
ticks/day), consider `.gitignore`-ing the raw `ticks_*.csv` files and syncing
them out-of-band (e.g. a synced folder, cloud storage) rather than committing
them to git — commit the *reports* (`TICK_DATA_QUALITY_REPORT.md`,
`TICK_DATA_MANIFEST.csv`), not the raw tick dumps.

## 4. Estimated minimum data requirement before Phase 5 hypothesis testing

Two different thresholds, not one:

- **Bare minimum to catch collection problems (~4-6 weeks)**: enough to run
  the quality validator, confirm the EA is behaving correctly across at
  least one full weekend cycle and one weekday-to-weekday cycle, and catch
  any systematic issue (wrong symbol mapping, a broker feed quirk, a bug in
  the exporter itself) before it's baked into months of "clean-looking but
  wrong" data. Don't wait until month 3 to first look at the quality report.

- **Minimum for genuinely meaningful Phase 5 research (~3-6 months, ideally
  6-12)**: the tick-level hypotheses in the directive (arrival intensity,
  imbalance, activity-price divergence, etc.) need per-instrument *session*
  or *day*-level baselines to detect "abnormal" activity against — that
  requires weeks of history just to establish a stable baseline, before any
  Discovery/Validation/Final-OOS split can even begin. Applying this research
  programme's standing 50/25/25 split convention: 3 months gives roughly
  65 trading days total, ~16 each for Validation and Final-OOS — thin enough
  that a single unusual week could dominate either period, similar to the
  concentration problems that weakened TSM's and alpha02's results. 6 months
  (~33 each) is a meaningfully more robust minimum; 12 months is better still
  and would also span at least one full quarterly earnings/macro-calendar
  cycle per instrument.

This is a much shorter *calendar* requirement than the ~10 years of daily
bars used in the OHLC research — tick data has vastly higher intraday sample
density, so per-day statistical power arrives fast. But calendar breadth
still matters for *regime* robustness (different volatility regimes,
different macro conditions) in exactly the way tick density can't substitute
for — don't let a data-dense but calendar-short window create false
confidence the way a single good year did for TSM and alpha02 earlier in
this research programme.

## 5. What NOT to do yet

Per the directive: no RSI/MA/volume-threshold indicators, no feature-
combination search, no strategy code. The only two scripts that should exist
against this new data right now are `TickExporter.mq5` (collection) and
`tick_data_quality_validator.py` (trust-but-verify on the collected data).
Phase 5's hypothesis list (tick-arrival intensity, tick imbalance,
activity-price divergence, etc.) waits until there's enough clean data to
actually test them against, and each one gets its own literature review and
pre-registration doc before any code, exactly like alpha02–alpha06.
