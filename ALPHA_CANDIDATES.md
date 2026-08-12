# Alpha Candidates

Fresh-direction research per the pivot after TSM was downgraded toward "no robust edge
found." No code has been written yet. This document is the required output before any
testing begins.

**Data reality check first**, per the directive's Phase 13 (verify data exists before
researching, mark untestable rather than fabricate):

- **We have**: M1 OHLC bars for 28 instruments (equity indices, FX majors/crosses,
  commodities/metals), years of history for most. MT5 economic calendar (event times +
  actual/forecast/previous), confirmed real historical depth. Confirmed broker UTC+3
  offset.
- **We do NOT have, but could get with a small new MQL5 export**: tick volume and
  spread per bar. `MqlRates` (the struct our exporter already reads) includes
  `tick_volume` and `spread` fields — we simply never wrote them to CSV. This is a
  genuine, cheap opportunity, not a hard data gap.
- **We do NOT have and would need external data for**: interest rate differentials
  (for carry), VIX or a VIX-proxy instrument (not yet checked whether FTMO offers one),
  institutional positioning (CFTC COT reports — free/public but not via MT5).
- **We structurally cannot get via MT5 retail feeds**: options/implied volatility data,
  true order-book/Level 2 data, real (non-tick-proxy) traded volume.

Every candidate below is marked with its actual data status. Untestable candidates are
listed for completeness (per the directive) and not developed further.

---

## Literature-grounded candidates (searched, not assumed from training data)

### 1. Overnight vs Intraday Return Decomposition
- **Source**: Cooper, Cliff & Gulen (2008); Kelly & Clark (2011); Bondarenko &
  Muravyev (2023); Boyarchenko, Larsen & Whelan, NY Fed Staff Report 917. Also very
  recent: "The Disappearing Overnight Drift," Liberty Street Economics, 2026.
- **Mechanism**: the equity risk premium has historically accrued almost entirely
  overnight (close-to-open), not intraday (open-to-close). Proposed causes: resolution
  of uncertainty as European markets open before the US close-to-open window, or
  dealer/intermediary inventory management.
- **Market**: originally S&P 500; documented across other index futures.
- **Timeframe**: daily decomposition (one data point per trading day per instrument).
- **Data required**: daily open and close. **We already have this for every
  instrument.**
- **Known limitation**: the most recent (2026) research explicitly finds the effect
  **disappearing** in current data — a genuine, honest headwind, not omitted.
- **Why it might still exist**: even a "disappearing" published effect can still show
  a residual, smaller version, and testing it ourselves (not assuming the paper's
  US-equity-specific finding transfers to our FX/commodity-heavy universe) is exactly
  the kind of independent verification this research process is built on.
- **Testable now**: YES, zero new data.

### 2. Pre-Scheduled-Event Drift
- **Source**: Lucca & Moench (2015) — pre-FOMC drift accounted for ~80% of annual US
  equity excess returns 1994-2011 in the 24h window *before* the announcement. Also:
  "The Disappearing Pre-FOMC Announcement Drift" (PMC/NIH) — the effect has weakened
  for announcements without press conferences.
- **Mechanism**: pre-positioning/information leakage ahead of known, scheduled,
  high-impact events — NOT the instant reaction to the release itself (that's what
  `news_breakout_ftmo.py` already tested and rejected). This is a slower drift in the
  hours/day *before* the event.
- **Market**: originally US equity indices around FOMC; generalizable to any
  scheduled high-impact event we already have calendar data for.
- **Data required**: calendar event times (have) + price data (have).
- **Known limitation**: explicitly reported as weakening/disappearing in recent
  research — must be tested on our own recent data, not assumed to hold.
- **Testable now**: YES, zero new data — genuinely different time window from the
  news-breakout mechanism already tested, not a re-run of it.

### 3. Turn-of-the-Month Effect
- **Source**: multiple studies since the 1980s; most recent (data through Q3 2024)
  found it "the only calendar effect that is statistically and economically
  significant and persistent" in S&P 500 futures specifically.
- **Mechanism**: institutional cash flows (pension contributions, payroll-linked
  buying) concentrated around month-end/month-start.
- **Data required**: daily price data only. **Have it.**
- **Known limitation**: literature is explicit that the effect is small and
  transaction costs "eat most of it" when traded mechanically — low prior on this
  producing a standalone tradeable edge, but cheap to test honestly.
- **Testable now**: YES, zero new data.

### 4. Cross-Asset Lead-Lag (USD Index / Gold → FX and Indices)
- **Source**: cross-quantilogram research on VIX/gold/USD directional predictability;
  DXY-SPX correlation regime research (60-day correlation flipping positive as a
  USD-funding-stress / risk-off signal).
- **Mechanism**: broad risk-sentiment or funding-stress signals in one asset (USD
  strength, gold safe-haven flows) propagating with a lag into other assets.
- **Adaptation**: the published research uses VIX, which we don't have. We DO have
  USDINDEX and GOLD already collected — this tests the same economic mechanism with
  instruments we actually hold, not a blind reproduction.
- **Data required**: USDINDEX, GOLD, and the rest of the universe's price data. **Have
  it all.**
- **Testable now**: YES, zero new data.

### 5. Cross-Timezone Equity Index Lead-Lag
- **Source**: general market-contagion / information-transmission literature (global
  markets open sequentially; a large US close-to-close move is public information
  before Asian and European markets open).
- **Mechanism**: does a large SP500/NAS100/US30 move predict the next JP225/HK50/AUS200
  open, or the next DAX/FRA40/EU50 open? This is a real information-transmission
  question, not a technical pattern.
- **Data required**: index price data across time zones. **Have it** (we hold US,
  European, and Asian/Pacific indices already).
- **Testable now**: YES, zero new data.

### 6. Tick-Volume-Based Short-Term Reversal / Liquidity Effects
- **Source**: Da, Liu & Schaumburg (2014); Nagel (2012); NY Fed Staff Report 513
  ("Decomposing Short-Term Return Reversal"). Important honest caveat from the same
  literature: "the illiquidity effect, measured by short-term reversal, is absent or
  trivial in futures markets" — mixed evidence, not a slam dunk.
- **Mechanism**: liquidity shocks (abnormal volume/turnover) force temporary price
  dislocation that partially reverses once liquidity returns.
- **Data required**: `tick_volume` per bar — **not currently collected**, but
  available from the same MT5 API we already use (`MqlRates.tick_volume`). Small,
  well-scoped new export needed.
- **Testable with minor new export**: YES.

### 7. Spread-Regime Liquidity Effects
- **Source**: same liquidity literature as #6, adapted — spread widening is a classic,
  direct liquidity-stress signal, arguably more directly informative than volume for a
  retail/CFD context.
- **Data required**: `spread` field per bar — same situation as #6, not currently
  collected but available from the same API, same small new export.
- **Testable with minor new export**: YES.

---

## Additional candidates (literature-adjacent or exploratory, lower priority)

### 8. Cross-Sectional Residual Momentum
Rank instruments by momentum in *residual* returns (after regressing out a common
market-beta factor) rather than raw returns. Literature (Blitz et al. and others) finds
residual momentum has different, sometimes better, risk-adjusted properties than raw
cross-sectional momentum — which we already tested and rejected. Methodologically
distinct enough to be worth listing, but close enough to an already-rejected family that
it ranks below the top 5. **Testable now**, zero new data.

### 9. Commodity-Currency Lead-Lag
Does WTI/Brent Oil's move lead CAD-related pairs; does Gold lead AUD-related pairs —
grounded in real commodity-currency economic linkages (Canada/oil, Australia/gold-metals
exports). **Testable now**, zero new data. Narrower hypothesis space than #4/#5 above.

### 10. Weekend Gap Behavior in FX
FX-specific weekend gap (Friday close to Sunday/Monday open) — literature notes forex
weekend gaps behave differently from weekday gaps and may need distinct risk handling.
**Testable now**, zero new data. Modest prior given how thin weekend-only samples will
be.

### 11. Post-Large-Move Conditional Asymmetry
Not a re-test of the already-rejected ATR-expansion-continuation or Bollinger-reversion
strategies — a narrower descriptive question: does the market's response to a large move
*change* depending on the prevailing volatility/correlation regime (already-built regime
variables from the TSM post-mortem can be reused for this). Positioned explicitly as
research, not a strategy attempt, given the overlap risk with excluded families.

### 12. FX Carry Trade
Real, well-documented, still shows genuine (if volatile) performance in current
research (2024 out-of-sample study, Banque de France carry/volatility-risk research).
**Requires external data** (interest rate differentials) not available via MT5 — would
need manual curation of central bank rate histories. Moderate effort, real motivation.

### 13. Cointegration / Kalman-Filter Dynamic Hedge Ratio Statistical Arbitrage
Formal Engle-Granger/Johansen cointegration testing for pair selection (replacing the
"shares a currency leg" heuristic) plus a time-varying Kalman-filter hedge ratio
(replacing the static normalization) is a genuine, well-documented methodological
upgrade over what we already tested. **Flagged transparently**: this sits close to the
explicitly excluded "AUD/USD cross-pair strategy" and "generic mean reversion"
families. Listed for completeness and honesty about the tension, not prioritized,
given the directive's explicit instruction not to continue that family.

### 14. Dispersion / Breadth as a Standalone Signal
Trading index-vs-component divergence requires true constituent data we don't have;
only crudely approximable with our current instrument set. **Weak data support.**

---

## Untestable with current data (marked honestly per Phase 13, not fabricated)

### 15. Volatility Risk Premium (implied vs realized volatility)
Requires options/implied-volatility data. **UNTESTABLE — no options data available via
MT5 retail feeds.**

### 16. Volatility Term Structure / Vol-of-Vol
Requires a term structure of volatility futures/options. **UNTESTABLE.**

### 17. True Order-Flow / Order-Book Imbalance
Requires Level 2 / order-book data. **UNTESTABLE via MT5 retail feed.**

### 18. Institutional Positioning (COT-based)
CFTC Commitment of Traders reports are free and public but not available through MT5 —
would require a separate external data source and manual weekly updates.
**UNTESTABLE WITH CURRENT PIPELINE**, flaggable as a real future data investment.

### 19. Earnings-Related Effects (Post-Earnings-Announcement Drift)
Not applicable — none of our 28 instruments are single equities with earnings dates;
all are indices, FX, or commodities. **NOT APPLICABLE to our universe.**

### 20. Rebalance / Index-Reconstitution Effects
Requires knowledge of official index reconstitution dates and constituent-level data.
**UNTESTABLE with current data** (could investigate the PUBLIC reconstitution
calendar for major indices as a much smaller, targeted follow-up, but not with what
we have now).

---

## Selected Top 5 (ranked on plausibility, novelty, data availability, robustness
potential, trade frequency, cost feasibility, FTMO suitability — NOT expected PF)

1. **Overnight vs Intraday Return Decomposition** — strongest, most-replicated
   academic backing of any candidate here (multiple independent papers across 15+
   years), zero new data needed, completely untested by us, directly applicable to
   our index-heavy universe where the effect is most documented. Daily frequency
   across many instruments = real trade volume.

2. **Pre-Scheduled-Event Drift** — strong original backing (Lucca-Moench), directly
   testable with data we already collected specifically for a *different* purpose
   (the calendar dataset), and genuinely mechanistically distinct from the
   already-rejected news-breakout (pre-event drift vs instant reaction are different
   phenomena with different proposed causes).

3. **Cross-Asset Lead-Lag (USDINDEX/GOLD → rest of universe)** — grounded in real
   published cross-asset risk research, tests a relationship type (lead-lag) we have
   never once tested in ~20 strategies tonight (everything so far has been
   single-instrument or paired-instrument, never "does A predict B a step later").

4. **Cross-Timezone Equity Index Lead-Lag** — same novelty argument as #3 from a
   different angle (information transmission across sequential market opens), zero
   new data, and index markets are exactly where this kind of effect is best
   documented.

5. **Tick-Volume-Based Liquidity/Reversal** — the only candidate in the top 5 that
   requires new data, but that new data (`tick_volume`) opens an entirely new
   dimension we've never used once across the whole research programme so far (pure
   price action only, until now). Worth the small cost of one more MQL5 export given
   how much unexplored information content it represents. Honestly flagged mixed
   literature evidence (works in some markets, "absent or trivial" in futures) — a
   real test, not a foregone conclusion.

Candidates #6 (spread-regime) and #12 (FX carry) are the next tier if the top 5 don't
pan out — both real, well-motivated, but either lower-priority (spread, same new-data
cost as #5 but thinner literature) or higher-effort (carry, needs external rate data).

Next: for each of the top 5, define the phenomenon independently of profitability
(per Phase 5's explicit "BAD: find parameters that maximise PF / GOOD: determine
whether X produces predictable Y" instruction), before writing any test code.
