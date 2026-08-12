# Alpha06 — Literature Review: Market Microstructure / Liquidity Proxies

Phase 10 priority 5 from the alpha04 close-out (chosen over priority 4,
volatility-related effects, because that would substantially overlap the
inconclusive vol-regime tercile work already done in the TSM ablation phase
of this research programme, and its cleanest form — implied-vs-realized vol
risk premium — needs options data we don't have). Genuine web research before
any hypothesis or code.

## 1. The core motivating fact: our data has no real volume

`ExportM1Data.mq5`-style exports across ~20+ prior strategies this research
programme never wrote `tick_volume`/`spread` to CSV, even though MT5's
`MqlRates` struct carries them (documented in `ALPHA_CANDIDATES.md`). Genuine
microstructure research normally uses trade volume, quoted spreads, or order
book depth — none of which we have. This phase is specifically about
**range-based estimators that reconstruct a liquidity/spread proxy from OHLC
data alone**, a well-established sub-literature that exists precisely because
volume/spread data isn't always available.

## 2. Corwin-Schultz: range-based bid-ask spread estimator (primary tool)

Corwin & Schultz (2012, Journal of Finance): estimates the effective bid-ask
spread using only daily high/low prices. The logic: a day's high is (almost
always) a buy trade, the low a sell trade, so the high-low range reflects both
the instrument's true volatility *and* the bid-ask bounce. Comparing the
expected squared range over a 1-day window (volatility + one bounce
contribution) against a 2-day window (volatility doubles, bounce contribution
stays fixed, since the spread is paid once per side regardless of the
interval) lets you solve two equations for two unknowns and isolate the
spread component. Documented to generally outperform other low-frequency
spread estimators. ([Ødegaard lecture notes](https://ba-odegaard.no/teach/notes/liquidity_estimators/corwin_schultz_high_low_estimator/lectures_high_low.pdf), [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1106193), [Journal of Finance](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2012.01729.x))

**Known bias, directly relevant to us**: the estimator is documented to be
**downward-biased for assets that don't trade continuously** — the fewer
trades within the "daily" window, the more the true range is underestimated.
Our CFD instruments trade close to 24h/day (unlike the individual stocks the
estimator was designed for, which have real market-hours-only sessions), so
this specific bias should be *less* severe for us than in the original
literature's typical application — worth confirming empirically rather than
assuming, since it cuts the other way from most applications.

## 3. Roll's implied spread: secondary/sanity-check tool, not primary

Roll (1984): even in an efficient market, trading between bid and ask
generates **negative serial covariance** in consecutive price changes — that
negative autocorrelation is the fingerprint of the spread itself. Implied
spread = 2 × √(max(0, −Cov(Δp_t, Δp_{t−1}))). Simple, well-known, but
**"severely biased by Jensen's inequality"** when there's genuine noise beyond
the pure bid-ask bounce mechanism — the max(0, ...) floor means any noisy
period where the true covariance is slightly positive just gets truncated to
zero, systematically distorting the average. ([search synthesis](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1984.tb03897.x), [arxiv survey](https://arxiv.org/pdf/1112.6169))
Given this documented fragility, Roll's estimator will be used only as a
cross-check against Corwin-Schultz's ranking, not as the primary signal.

## 4. The actual tradeable hypothesis: the Amihud illiquidity premium

Amihud (2002) and the large subsequent literature: **assets with higher
estimated illiquidity earn higher subsequent expected returns** — a
compensation-for-illiquidity-risk story, well-documented to have genuine
Granger-causal predictive power for aggregate market returns, not just a
cross-sectional correlation artifact. ([Oxford Academic](https://academic.oup.com/raps/article-abstract/3/1/133/1574887), [AEA](https://www.aeaweb.org/conference/2015/retrieve.php?pdfid=7476&tk=ESaTTBEz))

Important nuances from the literature, not omitted:
- The premium is concentrated in the **down-day component** of the Amihud
  measure specifically — up-day illiquidity doesn't carry the same premium.
  ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S106294082200211X))
- The premium has been shown to **depend heavily on the trading-volume
  component of the measure** — with volume variation removed, the premium
  disappears. This is a real problem for us: the classic Amihud measure is
  |return| / dollar-volume, and **we don't have real volume** — our
  Corwin-Schultz-based proxy is a *spread* estimate, not a *volume-scaled
  price-impact* estimate, so this is testing a related but not identical
  construct to the original Amihud premium. This should be stated plainly
  in results, not glossed over as "the same thing."
- Amihud illiquidity was originally documented cross-sectionally across many
  stocks of very different sizes/liquidity tiers — our universe is 13
  reasonably liquid, broadly comparable CFD instruments, a much narrower and
  more homogeneous illiquidity range than the original study. The effect may
  be structurally weaker or undetectable here simply because there isn't much
  illiquidity *dispersion* to exploit in the first place — a real, honest
  possibility to keep in mind before concluding anything about the mechanism
  if results come back null.

## 5. A related, well-documented, and more directly relevant literature: overnight-intraday reversal driven by liquidity provision

A large, more recent and more directly actionable literature: **close-to-open
("overnight-intraday") reversal delivers Sharpe ratios roughly 5x larger than
conventional short-term reversal strategies**, is consistent across
international equity markets and index/rate/commodity/currency futures, and
critically — **the cross-sectional dispersion of overnight returns predicts
the profitability of the reversal**, used as a proxy for market-maker
uncertainty at the open, with **liquidity provision as the proposed economic
driver**. Also documented: **the effect is stronger following high VIX**
(i.e., stronger in higher-uncertainty/lower-liquidity regimes).
([search synthesis](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/c953a0e6-e93e-4bf7-b839-45a90cedced4.pdf), [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0165188922000185))

**Important scope note**: this connects conceptually to alpha01's earlier
finding this research programme (intraday dominant over overnight in our
data, opposite of the "classic" literature) — but alpha01 was never given a
formal A/B/C/D classification, and reframing it now around a liquidity lens
would be exactly the kind of after-the-fact hypothesis-switching the
pre-registration discipline exists to prevent. Alpha06 will treat this as
background literature only (it justifies *why* a liquidity/spread proxy is a
plausible predictor of returns at all, and why VIX-style regime-conditioning
has real precedent) — not as license to go back and re-cut alpha01's already-
collected results through a new lens.

## Summary: what this means for the descriptive phase

- Primary tool: **Corwin-Schultz range-based spread estimator**, computed per
  instrument per day from OHLC only. Secondary cross-check: Roll's implied
  spread (flagged as more fragile).
- Primary hypothesis: does elevated estimated spread (illiquidity) predict
  subsequent returns — both **time-series** (within one instrument, does
  today's spread predict tomorrow's return) and **cross-sectional** (on a
  given day, do the more-illiquid instruments in our universe earn different
  subsequent returns than the more-liquid ones)?
- Go in with calibrated expectations: our proxy is spread-based, not
  volume-based, so it's testing a related-but-not-identical construct to the
  original Amihud premium; our universe has limited illiquidity dispersion
  compared to the original cross-sectional literature; and a null result here
  would be a legitimate, expected possibility given both of those honest
  caveats, not evidence of a bug.

## Sources
- [Analysis of the Amihud Illiquidity Premium (Oxford Academic)](https://academic.oup.com/raps/article-abstract/3/1/133/1574887)
- [Why is the Amihud (2002) Illiquidity Measure Priced?](https://www.aeaweb.org/conference/2015/retrieve.php?pdfid=7476&tk=ESaTTBEz)
- [Which stock price component drives the Amihud illiquidity premium?](https://www.sciencedirect.com/science/article/abs/pii/S106294082200211X)
- [A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices (Corwin & Schultz, SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1106193)
- [Corwin-Schultz estimator lecture notes (Ødegaard)](https://ba-odegaard.no/teach/notes/liquidity_estimators/corwin_schultz_high_low_estimator/lectures_high_low.pdf)
- [A Simple Implicit Measure of the Effective Bid-Ask Spread (Roll 1984)](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1984.tb03897.x)
- [Measuring market liquidity: An introductory survey](https://arxiv.org/pdf/1112.6169)
- [Overnight-Intraday Reversal Everywhere (Della Corte & Kosowski)](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/c953a0e6-e93e-4bf7-b839-45a90cedced4.pdf)
- [What drives intraday reversal? illiquidity or liquidity oversupply?](https://www.sciencedirect.com/science/article/abs/pii/S0165188922000185)
