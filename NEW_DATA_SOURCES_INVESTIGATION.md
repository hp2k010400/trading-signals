# New Data Sources Investigation

Per the directive: don't just say "COT data would be useful" — determine
whether we can actually obtain it now, and exactly how. This covers every
data source realistically usable to test the Edge Family B/D/E/F hypotheses
(relative value, futures information, volatility, cross-asset) without
waiting for the tick data collection currently running in the background.

## 1. CFTC Commitment of Traders (COT) — the strongest candidate

- **Exact source**: CFTC (US Commodity Futures Trading Commission), official
  government publisher. Public Socrata API:
  `https://publicreporting.cftc.gov/resource/jun7-fc8e.json` (Traders in
  Financial Futures / TFF report — the relevant one for us, since it covers
  stock index futures, currencies, and Treasuries, as opposed to the Legacy
  report which is agriculture/metals/energy-focused). Also downloadable as
  flat historical files (`HistoricalCompressed`) for full-history bulk pulls.
- **Exact dataset**: Traders in Financial Futures (TFF), Futures-Only and
  Combined (futures+options) variants. ~30 fields/row: long/short/spread
  positions broken out by trader category (Dealer, Asset Manager, Leveraged
  Money, Other Reportable, Non-Reportable), open interest, trader counts,
  top-4/top-8 concentration.
- **Instruments covered relevant to our universe**: CME E-mini S&P 500
  (**SP500**), E-mini Nasdaq-100 (**NAS100**), E-mini Dow (**US30**), E-mini
  Russell 2000 (**US2000**), COMEX Gold/Silver/Platinum (our **GOLD/SILVER/
  PLATINUM**, if we re-add them — not in the current 13-instrument set but
  easy to add back), and CME currency futures for AUD/CAD/NZD/EUR/GBP/JPY
  (covers the currency legs of **AUDCAD/AUDNZD**). **Not covered**: DAX,
  UK100, FRA40, EU50, JP225, AUS200, HK50 — these trade on Eurex/ICE
  Europe/OSE/HKEX/ASX, outside CFTC jurisdiction. This materially narrows
  the testable universe to the US-listed instruments + metals + AUD-linked
  FX, not all 13.
- **Historical depth**: TFF report back to 2006-06-13 (weekly). Legacy
  report (different category breakdown, agriculture-focused) back to 1986.
- **Granularity**: Weekly, as-of Tuesday close, published Friday — this is
  the report's own native granularity, not something we can make finer.
- **Real vs derived**: Genuinely different information — actual reported
  positioning by real market participants, not derived from our own price
  series.
- **Cost**: Free.
- **Access method**: `sodapy` Python client against the Socrata API, or
  direct CSV/JSON download via `requests` — both trivial to integrate into
  the existing pandas-based research scripts. No auth required for basic
  rate limits; a free Socrata app token raises rate limits if needed.
- **Limitations**: Weekly frequency is a hard ceiling — no intraday or even
  daily signal is possible from this alone, which caps realistic trade
  frequency low (matches the "modest edge" philosophy of the new directive,
  not a blocker). Reporting lag (data is ~3 days stale by the time it's
  published, and reflects Tuesday's positions). Trader-category definitions
  have shifted over time (noted below).
- **Licensing**: Public US government data, no restriction on research or
  commercial use.
- **Integration**: Straightforward — output is a clean, well-structured
  weekly time series joinable to our existing daily price data on date.
- **Verdict: DATA AVAILABLE NOW, free, high quality.**

### Honest literature check (not just "COT would be useful")
Evidence is genuinely mixed, not uniformly supportive:
- **Supporting**: "On the predictive role of large futures trades for
  S&P500 index returns: An analysis of COT data as an informative trading
  signal" finds real predictive content in large-trader positioning for
  S&P 500 returns. ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1042443113000723))
- **Against**: Other research finds "no consistent evidence that trader
  positions predict future market returns," and that extreme positioning
  (top/bottom 5%) does **not** reliably predict reversals — position-based
  sentiment signals largely fail to show reliable statistical significance.
  ([search synthesis](https://epub.jku.at/download/pdf/12001095.pdf))
- **Structural caution**: the mix of traders *within* each CFTC category has
  shifted over time (more hedge funds got reclassified as "commercial"
  post-2008), meaning the same category label doesn't mean the same thing
  across our whole 2016-2026 test window — a real regime-stability risk to
  flag up front, not discover after testing.
- Net read: this is a genuine, literature-debated hypothesis with real data
  behind it, not a slam dunk — appropriately modest-edge material, which
  fits the new "don't need PF 2+" philosophy better than most of what's been
  tested so far.

## 2. FRED (Federal Reserve Economic Data) — interest rate / yield curve

- **Exact source**: Federal Reserve Bank of St. Louis, official.
  `https://fred.stlouisfed.org`, free API.
- **Exact dataset**: Treasury constant-maturity yields (DGS3MO, DGS2, DGS10,
  DGS30, etc.), yield curve spread series, Fed Funds rate, and hundreds of
  other macro series.
- **Instruments covered**: Not instrument-specific — this is a macro
  regime/context input, usable across the whole universe (e.g., "does yield
  curve slope regime change equity index behavior").
- **Historical depth**: Many series back to the 1950s-1980s; certainly full
  coverage of our 2016-2026 window.
- **Granularity**: Daily for most yield series.
- **Real vs derived**: Genuinely different, official primary-source data.
- **Cost**: Free.
- **Access method**: `fredapi` Python package (`pip install fredapi`),
  requires a free API key (instant signup, no approval wait).
- **Limitations**: Macro/regime-level, not a direct trade signal — would
  need to be combined with a price-based execution rule, so on its own this
  is more of a *conditioning variable* for other edges than a standalone
  edge.
- **Licensing**: Public, unrestricted.
- **Integration**: Trivial, well-documented, extremely reliable API.
- **Verdict: DATA AVAILABLE NOW, free, best used as a regime filter/context
  input rather than a primary signal on its own.**

## 3. Real futures volume / open interest (genuinely different from our tick-less CFD data)

- **Free option**: CME Group's own Volume & Open Interest reports
  (`cmegroup.com/market-data/volume-open-interest.html`) are free but
  **aggregate daily/monthly summaries**, not a clean continuous historical
  series suitable for systematic backtesting — usable for spot-checks, not
  for building a time series to join against 10 years of daily data.
- **Paid, low-cost option**: **Databento** — official licensed CME/ICE/CBOT/
  NYMEX/COMEX data distributor, **$125 in free credits** for new accounts,
  pay-as-you-go pricing after that (no subscription commitment). Covers
  genuine real exchange volume, open interest, and even full order-book/tick
  data for CME futures (ES/NQ/YM/RTY — the futures underlying our SP500/
  NAS100/US30/US2000 CFDs — plus GC/SI/PL for metals). This is a realistic,
  bounded-cost way to get real volume/OI data for the US-listed instruments
  specifically (not the European/Asian indices, which trade on different
  exchanges Databento may or may not cover as fully).
- **Paid subscription option**: **Norgate Data** — continuous futures with
  volume/OI, reasonably priced retail subscription (historically ~$20-30/mo
  range for a futures-focused plan) — a subscription commitment rather than
  pay-as-you-go, worth considering only if Databento's pay-as-you-go doesn't
  fit the actual usage pattern.
- **Limitations across all of these**: none of them cover DAX/UK100/FRA40/
  EU50/JP225/AUS200/HK50 with the same free-credit-friendly ease — European/
  Asian futures volume data tends to sit behind pricier institutional
  packages. This is the same universe-narrowing problem as COT.
- **Verdict: NOT free, but realistically obtainable at low/bounded cost for
  the US-listed subset of our universe.** Given the "prioritise free" and
  "don't recommend expensive institutional data" instructions, this is
  ranked below COT/FRED, but flagged as a real, actionable option if a
  volume-based hypothesis clears the earlier gates on economic plausibility
  and looks worth the modest spend.

## 4. Economic release actual-vs-forecast (surprise) data

- **Paid APIs**: Apify's economic calendar scraper (~$8/1,000 results,
  pulls actual/forecast/previous from Investing.com), FinanceFlowAPI,
  Trading Economics — all viable but paid, and several are third-party
  scrapers of a source site's data (Investing.com), which raises a real
  ToS/reliability question for anything beyond light research use, not
  just a cost question.
- **Free option**: An Apify "ForexFactory Economic Calendar Parser" scraper
  is described as free/no-API-key — but still a scraping-based dependency
  on a third-party site's layout, which is fragile for building a reliable
  multi-year historical dataset (site changes silently break it, and
  large-scale historical backfilling via scraping is a genuine gray area on
  ToS grounds even when a tool technically allows it).
- **DIY alternative**: FRED/BLS/BEA publish the **actual** released values
  for most major US series (CPI, NFP, GDP, etc.) directly and reliably, but
  **not** the paired historical consensus/forecast figure — without a
  forecast to compare against, there's no "surprise" to compute. Building a
  genuine surprise series this way would require sourcing historical
  consensus forecasts from somewhere else regardless.
- **Verdict: DATA CURRENTLY UNAVAILABLE at a genuinely free, reliable,
  multi-year-backfillable standard.** The existing MT5 calendar export
  (already used for alpha02) gives event *timing* for free, which is why
  that hypothesis was testable — but *surprise magnitude* specifically is
  not cleanly obtainable right now without either paying for a scraper
  service or accepting real reliability/ToS risk. Deprioritized accordingly.

## 5. Term structure / futures curve shape

- Same providers as futures volume/OI (Databento covers multiple contract
  months for CME products, enabling a real curve-shape/contango-backwardation
  signal for GC/SI/ES/NQ). Same cost/coverage profile and same limitation
  (US-listed instruments only). Not pursued as the first candidate given COT
  and FRED are free and available immediately, but flagged as a realistic
  paid option for a later edge if the US-instrument subset proves fertile.

## Summary ranking of data sources by "obtainable now"

| Source | Cost | Depth | Coverage | Verdict |
|---|---|---|---|---|
| CFTC COT (TFF) | Free | 2006-now, weekly | SP500/NAS100/US30/US2000 + metals + AUD/CAD/NZD FX | **Use now** |
| FRED | Free | Decades, daily | Macro/regime context, universe-wide | **Use now** (as conditioning variable) |
| Databento (futures vol/OI/curve) | ~$125 free credit then pay-as-you-go | Full CME history | US-listed instruments only | Realistic paid fallback |
| Norgate Data | ~$20-30/mo | Full history | US-listed + broader | Realistic paid fallback |
| Economic surprise (scraped) | Free-$8/1k, ToS risk | Varies | Global | DATA CURRENTLY UNAVAILABLE at a reliable free standard |
