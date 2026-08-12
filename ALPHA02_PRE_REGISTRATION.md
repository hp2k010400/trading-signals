# Alpha02 Pre-Registration

Locked before the strategy backtest runs. Not modified after seeing results, per the
directive's explicit rule.

## Entry
Long (direction is fixed, not conditional — the observed effect was unconditionally
positive, not direction-dependent on the event) at the first available M1 bar at or
after `event_time - 24h`.

## Exit
At the first available M1 bar at or after `event_time` itself — i.e., the position is
closed right as the event happens, capturing ONLY the pre-event drift, not the
reaction to the release (that's a different, already-tested phenomenon —
`news_breakout_ftmo.py`).

## Instruments
The same 13 used in the descriptive measurement: DAX, NAS100, SP500, US30, UK100,
FRA40, JP225, AUS200, EU50, US2000, HK50, AUDCAD, AUDNZD. No instruments added or
removed based on which ones "look good" — same universe as the hypothesis was
measured on.

## Holding period
Fixed at ~24 hours (until the event). No early exit, no stop-loss, no target — per
the directive's explicit instruction that the first strategy must be "the purest
expression of the phenomenon," not an engineered risk-management wrapper around it.

## Position sizing
Volatility-scaled: each trade's raw log-return is divided by the instrument's own
20-day realized volatility (scaled to the ~24h holding period), the same convention
used throughout this research programme (`time_series_momentum_ftmo.py`,
`alpha03_strategy_*`) for cross-instrument comparability. Risk budget: 0.30% of
account equity per trade (the standard used throughout).

## Costs
Real spread costs (`COST_POINTS`, already used throughout this research programme)
with the standard 1.5x stress multiplier as the BASE case. Stress-tested additionally
at BASE+20%, BASE+50%, BASE+100% per Phase 9 — reported separately, not used to
select a "best" cost assumption.

## Discovery / Validation / Final OOS split
Computed as the 50th and 75th percentile of event dates by calendar time (identical
method to the descriptive measurement) — locked by this method BEFORE running the
strategy backtest, not chosen after seeing which split produces a better result.

## Decision rule
Per Phase 12: classification is NOT based on PF alone. Requires reasonable sample
size, positive NET (after-cost) expectancy, profitability in multiple independent
periods (not concentrated in one), no obvious lookahead, and reasonable robustness
to the cost stress test. If net expectancy is non-positive or concentrated in a
single period, REJECT — no filter-adding, no parameter search to rescue it.
