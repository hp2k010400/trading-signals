# Databento Data Audit — Candidate #9 (Futures Volume/OI Information)

Data audit only. No purchase, no download, no strategy test. Genuine web
research against Databento's public documentation/pricing pages (their
account-gated cost API was checked directly and confirms auth is required —
`hist.databento.com/v0/metadata.list_unit_prices` returns 401 Unauthorized
without an API key — so exact $/GB figures below are reasoned estimates from
public tier documentation, not a live quote; see the recommendation at the
end for how to get an exact number for free before spending anything).

## 1. What each data type actually is — not interchangeable

| Term | What it measures | Databento schema | CME MDP3 tier |
|---|---|---|---|
| **Trade (real) volume** | Contracts *actually transacted* in a period — genuine economic turnover. The "V" in OHLCV. | `ohlcv-1s/1m/1h/1d` (aggregated) or `trades` (every individual print) | L0 (OHLCV) / L1 (trades) |
| **Tick volume** | An MT5/retail-CFD-broker concept: the *count of quote-update events* in a bar. Not real traded volume — this is what our existing FTMO M1 data has always lacked (confirmed back in `ALPHA_CANDIDATES.md`) and what the currently-running `TickExporter.mq5` will eventually collect. Databento's real trade volume is a fundamentally different, more informative measure than tick volume. | N/A (not a Databento concept) | — |
| **Open interest (OI)** | Total *outstanding* (not yet closed) contracts at a point in time — a **stock**, not a flow. Reported once/day by the exchange. Completely separate from volume, which measures turnover *during* a period. | `statistics` (stat_type for open interest, alongside settlement price and other daily reference stats) | L0 |
| **Bid/ask quotes** | Best bid/best offer (top of book) — pre-trade pricing, not transacted activity. | `mbp-1`, `tbbo`, `bbo` | L1 |
| **Order-book/depth data** | Resting limit-order quantities at multiple price levels (MBP-10 = top 10 levels aggregated) or every individual order (MBO = full book) — measures standing *liquidity*, not activity that has occurred. | `mbp-10`, `mbo` | L2 / L3 |

Confirmed via Databento's own docs: continuous-contract symbology is
natively supported (`ES.c.0` = calendar-roll lead month, `ES.n.0` =
open-interest-roll lead month, plus a volume-roll variant) — we would not
need to build our own futures-roll logic.

## 2. Historical depth — the constraint that actually matters more than price

This is the single most important finding of this audit, more consequential
than the exact $/GB rate: **usage-based (pay-as-you-go, what the $125 credit
applies to) historical depth is capped by schema tier, regardless of budget**:

| Tier | Schemas | Usage-based history available |
|---|---|---|
| **L0** | OHLCV (1s/1m/1h/1d), statistics (incl. open interest), definitions, status | **16+ years** |
| **L1** | trades, mbp-1, tbbo, bbo | **1 year only** |
| **L2** | mbp-10 | **1 month only** |
| **L3** | mbo (full order book) | **1 month only** |

Deeper L1/L2/L3 history exists but is **not purchasable via usage-based
credit at any price** — it requires a subscription plan: Standard ($199/mo,
1yr L1 + 1mo L2/L3 included), Plus ($1,750/mo, 16+yr L1), Unlimited
($4,500/mo, full depth all tiers). A LinkedIn post from Databento advertised
CME data at $179/mo, possibly an older/promotional Standard-tier price —
noted as unverified, not relied on.

**Direct implication: "10 years of tick data" or "10 years of order-book
data" is not something $125 (or any usage-based amount) can buy — only 16+
years of OHLCV/volume/open-interest (L0), or 1 year of individual trades/
quotes (L1), or 1 month of order-book depth (L2/L3).**

## 3. Cost estimate — reasoned, not a live quote

Without an account, Databento's cost API 401s (confirmed directly, not
assumed) — this section is a reasoned estimate from their published tier
structure, not an exact figure.

Bar-level (OHLCV) and daily-statistics data are, by construction, many
orders of magnitude smaller than trade-by-trade or order-book data — a
decade of hourly OHLCV bars for one symbol is on the order of tens of
thousands of rows (roughly comparable in scale to the M1 CSV files already
used throughout this research programme, which are themselves only a few
hundred MB for 10 years at 1-minute resolution — hourly bars would be ~60x
smaller again). Four symbols (ES, NQ, GC, CL) × 16 years of OHLCV-1h +
daily statistics is very likely a **small fraction of $125** — plausibly
low single-digit dollars given Databento's own positioning of bar/reference
data as their cheapest usage-based tier.

By contrast, `trades` (every individual print) for four highly liquid
futures (ES and NQ especially trade millions of contracts/day) even over
just the maximum usage-based year of history could plausibly run into real
money — potentially consuming a meaningful share or all of the $125 credit
for a single year across all four symbols, though this is a directional
warning, not a verified number.

`mbp-10`/`mbo` (order book) is capped at 1 month via usage-based access
regardless — not a meaningful option for a multi-year backtest at all
without the $4,500/mo Unlimited plan, which is far outside the "prioritise
free/cheap" mandate.

**Recommended concrete next step for an exact number, at zero cost**:
create a free Databento account (the $125 credit is issued automatically,
no card charge to sign up) and call `metadata.get_cost()` for the exact
OHLCV-1h + statistics request across ES/NQ/GC/CL — this is Databento's own
free, no-obligation price-quote mechanism, and would replace this section's
estimate with a real number before any actual download. Not done here per
the "no purchase/download" instruction — flagged as the natural first paid-
account action if you want to proceed further before I do so.

## 4. Recommended minimum-cost dataset

**OHLCV-1h + statistics (open interest), for ES, NQ, GC, CL, full available
history (16+ years), all L0 tier.**

This is the cheapest possible Databento product that still contains
genuinely new information versus our existing FTMO M1 OHLC data — real
traded volume and open interest, neither of which exist anywhere in our
current dataset. It fully supports the top-ranked hypotheses below (H1, H2,
H4, H5, H7) and partially supports H3/H6 (which would benefit from, but
don't strictly require, finer granularity than 1h). Comfortably within
$125 on the reasoning above. `trades`/`mbp-1` are not recommended at this
stage — capped at 1 year of history regardless of spend, and the
top-ranked hypotheses don't need trade-level granularity to be tested
properly.

---

# 5. Ranked Pre-Test Hypotheses (none tested — literature + design only)

## H1 — Open Interest Change → Forward Returns (RANK 1)
- **Mechanism**: OI changes reflect shifts in hedging demand and the
  market's risk-absorption capacity. Hong & Yogo (NBER working paper,
  published in *Journal of Financial Economics*): 12-month change in
  futures open interest predicts commodity, bond, currency, and (to a
  lesser extent) equity returns — a standard-deviation increase in
  commodity market open interest raises expected commodity returns by
  ~0.72%/month, economically large and statistically significant, and this
  holds even controlling for other known predictors. This is the single
  most directly-cited, cross-asset-validated finding in this whole audit.
- **Exact data required**: `statistics` (open interest) + `ohlcv-1d` (price),
  ES/NQ/GC/CL.
- **Granularity**: daily (aggregated to monthly change, matching the
  original study).
- **Required history**: as much as available (16+ years, L0).
- **Prediction/holding horizon**: ~1 month (matching Hong & Yogo), tested
  broadly at multiple horizons (e.g. 2/4/8 weeks) per this programme's
  standing practice of not cherry-picking one horizon.
- **Opportunity frequency**: low — monthly-refresh signal, ~4 decision
  points/month across 4 instruments.
- **Transaction-cost sensitivity**: LOW — monthly holding period makes
  fixed per-trade costs a small fraction of typical move size, structurally
  more cost-robust than anything tested in the COT queue (E19–E26).
- **Falsification criteria**: same standard as the whole programme —
  reject if full-history correlation isn't in the predicted (positive)
  direction and reasonably stable across Discovery/Validation/Final-OOS.
- **FTMO CFD execution path**: direct — ES→US500/SP500, NQ→US100/NAS100,
  GC→GOLD/XAUUSD, CL→OIL, using the existing vol-scaled sizing convention.

## H2 — Volume-Conditioned Continuation vs. Reversal (RANK 2)
- **Mechanism**: Blume, Easley & O'Hara (1994, *Journal of Finance*):
  volume carries information about signal *quality* that price alone
  cannot reveal. Separately, the abnormal-trading-volume (ATV) literature
  finds high-ATV moves show strong short-run continuation, but that
  continuation itself predicts a *reversal* once volume normalizes — a
  real, nuanced, two-stage pattern, not a simple one-shot correlation.
- **Exact data required**: `ohlcv-1d` (price + real volume), ES/NQ/GC/CL.
- **Granularity**: daily (hourly as a secondary check).
- **Required history**: full available (16+ years).
- **Prediction/holding horizon**: short (days to ~2 weeks), with an
  explicit second test for the volume-normalization reversal effect at a
  longer horizon — must be designed into Gate 1, not bolted on after.
- **Opportunity frequency**: moderate — abnormal-volume days are common
  enough to occur roughly weekly per instrument.
- **Transaction-cost sensitivity**: MODERATE — short holding period, but
  daily-bar granularity (not intraday scalping) keeps this more tolerable
  than M1-level strategies tested earlier this programme.
- **Falsification criteria**: standard, plus must show the predicted
  continuation-then-reversal shape, not just a single-horizon correlation.
- **FTMO CFD execution path**: direct, same instrument mapping as H1.

## H7 — Volume/Open-Interest Turnover Ratio (RANK 3)
- **Mechanism**: Volume relative to *outstanding* open interest ("churn" of
  the existing position base) is a genuinely distinct construct from either
  H1 (OI level/change alone) or H2 (volume alone) — high turnover could
  reflect information-driven repositioning (bullish per Blume-Easley-O'Hara)
  or capitulation/panic (contrarian). No single direct citation for this
  exact ratio was found; it's a principled combination of H1 and H2's
  underlying theories, not an independently validated result on its own.
- **Exact data required**: `ohlcv-1d` (volume) + `statistics` (OI),
  ES/NQ/GC/CL.
- **Granularity**: daily.
- **Required history**: full available.
- **Prediction/holding horizon**: short-to-medium (days to a few weeks).
- **Opportunity frequency**: moderate.
- **Transaction-cost sensitivity**: MODERATE.
- **Falsification criteria**: standard; direction not pre-committed as
  confidently as H1/H2 given the weaker direct evidentiary base — the
  pre-registration itself would need to commit to one direction (bullish-
  turnover vs. contrarian-turnover) before testing, not decide after.
- **FTMO CFD execution path**: direct, same instrument mapping.

## H3 — Volume Concentration Around Large Price Moves (RANK 4)
- **Mechanism**: Microstructure theory in the Easley–O'Hara lineage
  (informed-trading/PIN-style models): large price moves accompanied by
  *disproportionately* high volume (relative to the move's size) may
  reflect genuine informed trading and predict continuation; large moves on
  *low* relative volume may reflect liquidity-driven noise likely to revert.
- **Exact data required**: `ohlcv-1h` (price range + volume) — hourly
  recommended over daily, since a true PIN-style measure normally needs
  finer granularity than daily bars to distinguish "large move, high
  volume" from "large move, low volume" cleanly.
- **Granularity**: hourly (still L0/cheap — the reason `ohlcv-1h` is the
  recommended base dataset over `ohlcv-1d` alone).
- **Required history**: full available.
- **Prediction/holding horizon**: short (days).
- **Opportunity frequency**: LOW — only fires on genuinely large moves,
  plausibly a handful of times per month per instrument.
- **Transaction-cost sensitivity**: LOW-MODERATE — larger moves generate a
  bigger edge relative to fixed costs than most candidates in this queue.
- **Falsification criteria**: standard.
- **FTMO CFD execution path**: direct, same instrument mapping.

## H5 — Cross-Market Futures Activity Spillover (RANK 5)
- **Mechanism**: An abnormal volume/OI shock in one market (e.g. ES) may
  precede information diffusion into a correlated market (NQ) with a short
  lag; alternatively, CL (energy) activity shocks may proxy macro/inflation
  repricing relevant to equity indices.
- **Exact data required**: `ohlcv-1d` + `statistics` for both legs of each
  tested pair.
- **Granularity**: daily.
- **Required history**: full available.
- **Prediction/holding horizon**: short (days).
- **Opportunity frequency**: moderate.
- **Transaction-cost sensitivity**: moderate.
- **Falsification criteria**: standard, PLUS the same non-synchronous-
  trading/genuine-information-transmission-vs-simultaneous-correlated-
  reaction caution already learned the hard way in `ALPHA04_LITERATURE.md`.
- **FTMO CFD execution path**: two-legged relative-value or simple
  directional spillover, same instrument mapping.
- **Ranked lower deliberately**: this is the same *lead-lag/spillover*
  mechanism family already tested and decisively rejected twice this
  research programme (alpha03 cross-asset, alpha04 cross-timezone) — the
  *information layer* here (volume/OI, not price) is genuinely different,
  but the structural pattern that failed twice before is a real reason for
  caution, not exclusion.

## H4 — Price × Open-Interest Interaction ("four-way" classification) (RANK 6)
- **Mechanism**: Popular trading heuristic — rising price + rising OI = new
  longs entering (bullish confirmation); rising price + falling OI = short
  covering (weaker signal); falling price + rising OI = new shorts
  (bearish confirmation); falling price + falling OI = long liquidation.
  **Explicitly flagged**: genuine web research found this described only as
  general market/trading-lore knowledge, not as a rigorously validated
  academic classification (a specific "Chen/Strong/Rutledge" framing
  referenced in earlier internal notes could not be verified in the
  literature search) — testing this is explicitly a "does the folklore
  survive scrutiny" exercise, going in with a weaker evidentiary prior than
  H1/H2/H3/H7.
- **Exact data required**: `ohlcv-1d` (price direction) + `statistics` (OI
  change).
- **Granularity**: daily.
- **Required history**: full available.
- **Prediction/holding horizon**: short-to-medium (days to weeks).
- **Opportunity frequency**: moderate — daily classification, though only 2
  of 4 quadrants are the folklore's "confirming" cases.
- **Transaction-cost sensitivity**: LOW-MODERATE.
- **Falsification criteria**: standard; explicit low prior stated in
  advance given the lack of found academic support.
- **FTMO CFD execution path**: direct, same instrument mapping.

## H6 — Volume/OI Participation Shocks → Forward Volatility (RANK 7, lowest)
- **Mechanism**: Sudden shifts in genuine participation (real volume/OI,
  not the CFTC trader-count concentration metric) may signal a liquidity-
  regime change, predicting elevated near-term volatility.
- **Exact data required**: `ohlcv-1d`/`ohlcv-1h` (volume) + `statistics`
  (OI).
- **Granularity**: daily or hourly.
- **Required history**: full available.
- **Prediction/holding horizon**: short (days to ~2 weeks), targeting
  forward realized VOLATILITY, not direction.
- **Opportunity frequency**: low-moderate.
- **Transaction-cost sensitivity**: N/A directly as a standalone
  directional trade — would need a genuinely different execution design
  (position-sizing/risk overlay rather than a directional bet), not solved
  here.
- **Falsification criteria**: standard, target = forward realized vol
  (same target-variable choice as `E26`).
- **FTMO CFD execution path**: risk-sizing overlay, not a standalone trade
  — the least directly executable of the seven.
- **Ranked lowest deliberately**: `E26` (COT trader-concentration →
  volatility) was just tested and rejected this session with a stark
  single-period-concentration failure (the whole full-history result was
  carried by the COVID/2022 window alone). H6 uses genuinely different data
  (real volume/OI shocks, not CFTC trader counts) so it is not a re-run of
  E26 — but the *mechanism family* (concentration/participation → forward
  vol) just failed once already, a real reason for lower confidence, stated
  honestly rather than ignored.

---

# Summary

- **Data available now, free**: OHLCV (real trade volume) + statistics
  (open interest), 16+ years, ES/NQ/GC/CL — genuinely new information vs.
  our existing FTMO OHLC data, comfortably within the $125 credit on a
  reasoned estimate.
- **Data NOT realistically obtainable within budget**: multi-year
  trade-by-trade or order-book history — usage-based access caps these at
  1 year (trades/quotes) or 1 month (order book) regardless of spend; deep
  history requires a $199–$4,500/month subscription, well outside the
  "prioritise free/cheap" mandate and not needed for the top-ranked
  hypotheses anyway.
- **Recommended purchase** (not yet made): OHLCV-1h + statistics, ES/NQ/GC/CL,
  full history — supports H1/H2/H4/H5/H7 fully and H3/H6 adequately.
- **Top-ranked hypothesis**: H1 (open interest change → forward returns),
  grounded in a specific, cited, cross-asset-validated academic result
  (Hong & Yogo), low cost-sensitivity, direct FTMO execution path.

Stopping here per instruction — no purchase, no download, no strategy test.
Awaiting direction before proceeding to an actual Databento account/cost
quote or any Gate 1 testing.
