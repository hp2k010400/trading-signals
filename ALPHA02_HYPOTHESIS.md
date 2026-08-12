# Alpha02 Hypothesis: Pre-Scheduled-Event Drift

## Exact event definition
Any row in `HighImpactCalendar.csv` (MT5 economic calendar) tagged importance HIGH or
MODERATE by the exporter (`ExportHighImpactCalendar.mq5`), deduplicated on
(currency, event_name, time) to remove revision re-listings of the same real-world
release.

## Exact timestamp
`event_time`, confirmed to use the same broker-server UTC+3 convention as M1 price
bars — independently verified against a known real-world fact (EIA Natural Gas
Storage releases every Thursday at 10:30am US Eastern) earlier in this research
programme, not assumed.

## Exact instruments
13 instruments, each included only for events in ITS mapped currency, using the same
currency-to-instrument mapping already used (and separately justified) by
`news_breakout_ftmo.py`:
`DAX, NAS100, SP500, US30, UK100, FRA40, JP225, AUS200, EU50, US2000, HK50, AUDCAD,
AUDNZD`. This is not an arbitrary universe — it is whichever instruments plausibly
react to a given release's currency, decided independently of this specific
hypothesis's profitability.

## Exact pre-event window
24 hours immediately preceding `event_time`. `PRE_WINDOW_HOURS = 24`, fixed, not
tuned.

## Exact observed behaviour (from the descriptive measurement, `alpha02_pre_event
_drift_ftmo.py`, real FTMO data, 2016-08-16 to 2026-08-11)
Price consistently drifts in a POSITIVE direction over the 24h window before a
high-impact release — **unconditional on the event's outcome or even which currency
it is**, not a directional call that depends on interpreting the release.

## Sample size and period breakdown
| Period | Date range | N | Mean | Sharpe-like ratio | % positive |
|---|---|---|---|---|---|
| Discovery | 2016-08-16 → 2023-05-19 | 85,449 | +3.70bp | +0.0314 | 50.0% |
| Validation | 2023-05-19 → 2024-12-10 | 42,765 | +6.94bp | +0.0715 | 55.3% |
| Final OOS | 2024-12-10 → 2026-08-11 | 42,741 | +3.29bp | +0.0291 | 52.5% |

Positive in all three chronologically separate periods — not a one-period artifact.

## By instrument (full history)
All 13 instruments positive. Strongest in equity indices (NAS100 +6.71bp, EU50
+6.35bp, SP500 +6.30bp), weakest in the two FX crosses tested (AUDNZD +0.97bp,
AUDCAD +1.97bp) — consistent with the original literature's finding that this is
specifically an equity-index-dominated phenomenon.

## Dispersion and approximate confidence interval
The script's Sharpe-like ratio is mean/std (unannualized, per-observation). Back-
solving std = mean / sharpe:
- Discovery: std ≈ 1.18%, SE ≈ 0.040bp, 95% CI on the mean ≈ **[2.91bp, 4.49bp]**
- Validation: std ≈ 0.971×10⁻¹... (computed the same way) — mean clearly bounded away
  from zero in the naive i.i.d. calculation.

**Important honest caveat, stated up front per the directive's own standard**: this
naive confidence interval assumes independent observations. It is NOT independent —
many high-impact events land on the same calendar day (e.g., multiple releases from
the same country), which creates overlapping, correlated 24h pre-event windows for
the same instrument. The TRUE effective sample size is smaller than 170,955, and the
real confidence interval is wider than the naive calculation above suggests. The
naive CI is reported because it's what the data supports computing directly; it should
be read as "clearly non-zero in the simplest calculation," not as a precise
statistical guarantee.

## Previous research supporting it
Lucca & Moench (2015): pre-FOMC drift (24h window before FOMC announcements)
accounted for ~80% of annual US equity excess returns 1994-2011. More recent
research ("The Disappearing Pre-FOMC Announcement Drift") finds the effect has
weakened for announcements without press conferences — an honest headwind, not
omitted. Our finding generalizes the original single-event-type (FOMC) result to
the full high-impact calendar, and finds it holds directionally, though we have not
separately verified whether it's driven primarily by FOMC-type events or spread
across the full calendar (a question for Phase 7's event-by-event breakdown).

## Potential economic/behavioural explanation
Pre-positioning ahead of known, scheduled uncertainty resolution — traders reducing
risk or adjusting exposure ahead of a release, with equity indices (the most liquid,
most-watched risk-sentiment barometer) showing the strongest effect, consistent with
the original FOMC-specific literature's proposed mechanism.

## No-lookahead confirmation
The event's existence and scheduled time are known in advance (that's what "scheduled"
means) — the calendar itself carries no lookahead. The drift measurement uses only
price data between `event_time - 24h` and `event_time`, never touching data from
after the event. Confirmed clean.
