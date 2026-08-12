# Alpha05 — Literature Review: Statistical Arbitrage / Residual (Spread) Relationships

Phase 10 priority 2 from the alpha04 close-out. Genuine web research before any
hypothesis or code. This is a fundamentally different mechanism from anything
tested so far this research programme: rather than betting on the direction of
a single instrument (TSM, news breakout, pre-event drift) or one instrument
predicting another's *direction* (alpha03/04's lead-lag), stat-arb bets on the
**relationship between two correlated instruments reverting to its historical
norm**, market-neutral in the underlying direction of either leg. This is not
a return to the prohibited "generic mean-reversion" family (that referred to
single-instrument RSI/Bollinger-style reversion) or the prohibited "AUD/USD
cross-pair strategy" (a directional cross-pair bet, not a cointegrated spread) —
it's a distinct methodology with its own literature, explicitly on the user's
own approved priority list.

## 1. Core methodologies

Three established approaches, in order of how rigorously the "will this spread
actually revert" question is answered:
- **Distance method** (Gatev, Goetzmann, Rouwenhorst 1999/2006): pick pairs by
  minimizing sum-of-squared-deviation between *normalized price series* over a
  formation period, then trade the spread when it diverges. Simple, no formal
  statistical test that the spread is actually mean-reverting.
- **Cointegration method** (Engle-Granger two-step, or Johansen for >2 legs):
  formally test whether a linear combination of the two price series is
  stationary. If it is, the spread has a genuine statistical basis for
  mean-reversion, not just a "looks correlated" assumption.
- **Time-series / Ornstein-Uhlenbeck method**: model the spread directly as a
  mean-reverting stochastic process, estimate its mean-reversion speed and
  half-life, and size/time trades around that.
  ([survey paper](https://www.wne.uw.edu.pl/download_file/6095/0), [Krauss 2017 review](https://onlinelibrary.wiley.com/doi/abs/10.1111/joes.12153), [Hudson & Thames intro](https://hudsonthames.org/an-introduction-to-cointegration/))

We should use the cointegration method as the primary screen (formally test
stationarity of the spread, don't just eyeball correlation), consistent with
this research programme's standing discipline of not treating "looks
consistent" as equivalent to "is statistically real."

## 2. The seminal result — and its decay, which matters a great deal here

Gatev, Goetzmann & Rouwenhorst (Review of Financial Studies, 2006): a simple
distance-method pairs trading rule on US equities, 1962–2002, produced average
annualized excess returns up to 11% for self-financing portfolios, exceeding
conservative transaction cost estimates through most of the period.
([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=141615), [NBER](https://www.nber.org/papers/w7032))

**The critical caveat, and it is a big one for this specific research
programme**: subsequent research found pairs trading profitability was
strongest *before 1989* and **declined from the 1990s onward — substantially
less profitable after 2002, and often unprofitable once realistic costs were
applied.** The mechanism is well-understood and not disputed: decimalization
of US quotes (2001) compressed spreads, and rising computing power / cheap
data meant more participants crowding the same convergence trades, arbitraging
the premium away over time. ([search synthesis](https://navnoorbawa.substack.com/p/de-shaw-citadel-and-renaissance-run))

Our test period (2016–2026 FTMO broker data) falls entirely *after* the
documented decay window. This is not a reason to skip the research — the
user's own priority list put it here — but it is a reason to go in with
calibrated expectations and to treat "classic stat-arb no longer works as well
as the 1962-2002 textbook number" as the honest prior, not a surprising
failure if that's what we find.

## 3. Candidate pairs, grounded in real, cited correlation facts (not guesses)

Our universe is equity **indices**, not individual stocks — most of the
academic literature is stock-pairs-within-an-industry. The closest real-world
analogue for indices: same-region index pairs, which are documented to be
highly correlated:
- DAX correlates most strongly with the Euro Stoxx 50 (**typical correlation
  0.85–0.95**), second-strongest with CAC 40 — both explained by shared
  Eurozone economic exposure. ([search synthesis](https://derivativesjournal.com/indices/dax-vs-euro-stoxx-correlation))
- This gives concrete, literature-grounded candidate pairs from our own
  13-instrument universe: **DAX–EU50, DAX–FRA40, FRA40–EU50** (Eurozone
  cluster) and, by the same within-region logic, **NAS100–SP500, SP500–US30,
  NAS100–US30** (US mega-cap cluster). UK100 is a weaker candidate leg (UK
  outside the Eurozone, historically lower correlation to DAX than DAX-to-CAC)
  — worth testing but expect a lower baseline correlation, not necessarily a
  worse pair.
- US2000 (small-cap Russell) is a genuinely different case from the mega-cap
  US trio — small caps historically show *lower* correlation to large caps
  than large caps show to each other, which could mean either a more genuine
  arbitrageable spread (less redundant, more information in the residual) or
  simply a non-cointegrated pair that shouldn't be traded as one — this needs
  the formal cointegration test, not an assumption either way.

## 4. Known methodological pitfall: OLS hedge-ratio / mean-reversion-speed bias

A specific, technical, real pitfall directly relevant to how we must build
this: **OLS-estimated mean-reversion speed (κ) in an Ornstein-Uhlenbeck-style
spread model is systematically biased toward appearing faster than it truly
is** — a pair with a true half-life of ~46 days can look fast enough to pass a
tradeability filter purely from estimation bias, and a genuinely fast-reverting
pair can get an underestimated half-life that fires the exit signal before
most of the convergence has actually happened. Also: **plain OLS hedge ratios
are sensitive to which instrument is chosen as the dependent variable** — not
a symmetric, unique answer the way a "hedge ratio" is often casually treated.
([Hudson & Thames caveats](https://hudsonthames.org/caveats-in-calibrating-the-ou-process/), [search synthesis](https://navnoorbawa.substack.com/p/de-shaw-citadel-and-renaissance-run))

**Direct implication for our design**: the hedge ratio and cointegration test
must be estimated on a fixed formation/Discovery period and then held fixed
(not re-fit) when generating trades in Validation/Final-OOS — exactly the
pre-registration discipline already established for alpha02, applied here for
a different, spread-specific reason (re-fitting introduces exactly the kind of
in-sample-flattering bias documented above, on top of being a lookahead
concern).

## 5. Standard practical implementation (what "the trade" actually is)

Compute the spread's z-score (spread minus its rolling/formation-period mean,
divided by its rolling/formation-period standard deviation); the field
convention is entry around z ≈ ±1 to ±2, exit around z ≈ 0 (full mean
reversion) or a smaller threshold. ([search synthesis](https://medium.com/@writeronepagecode/quant-trading-mastering-mean-reversion-and-pure-arbitrage-in-python-c92b9b438981))
This is genuinely different from alpha01/02's approach (those bet on an
unconditional directional drift in a single instrument); here the position is
long one leg, short the other, sized to be approximately market-neutral to the
common factor — profit comes only from the *spread* reverting, not from either
leg's absolute direction. This should also make it structurally less
correlated with the FTMO account's existing risk than any directional
strategy tested so far, which is worth noting as a portfolio-construction
positive independent of whether it clears the bar on its own.

## Summary: what this means for the next phases

- Use the **cointegration method** (formal stationarity test on the spread),
  not just "looks correlated," as the pair-selection screen.
- Test candidate pairs grounded in real correlation facts: DAX–EU50,
  DAX–FRA40, FRA40–EU50 (Eurozone cluster, expect high correlation);
  NAS100–SP500, SP500–US30, NAS100–US30 (US mega-cap cluster); UK100 vs the
  Eurozone cluster and US2000 vs the US mega-cap cluster as weaker/more
  uncertain candidates worth testing rather than assuming.
- **Calibrate expectations downward from the 1962-2002 textbook number** —
  the documented decay/crowding of classic stat-arb since the 1990s-2000s is
  a real, literature-supported headwind for a 2016-2026 test period, not a
  reason to suspect a bug if results are weaker than the seminal paper.
- **Estimate hedge ratio and cointegration on a fixed formation period only**,
  never re-fit during Validation/Final-OOS — both for lookahead discipline
  (established already) and to avoid the documented OLS mean-reversion-speed
  bias specifically.

## Sources
- [A Survey of Statistical Arbitrage Pairs](https://www.wne.uw.edu.pl/download_file/6095/0)
- [Statistical Arbitrage Pairs Trading Strategies: Review and Outlook (Krauss 2017)](https://onlinelibrary.wiley.com/doi/abs/10.1111/joes.12153)
- [An Introduction to Cointegration for Pairs Trading (Hudson & Thames)](https://hudsonthames.org/an-introduction-to-cointegration/)
- [Pairs Trading: Performance of a Relative-Value Arbitrage Rule (Gatev, Goetzmann, Rouwenhorst, SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=141615)
- [Pairs Trading: Performance of a Relative Value Arbitrage Rule (NBER)](https://www.nber.org/papers/w7032)
- [D.E. Shaw, Citadel, and Renaissance Run Statistical Arbitrage — OLS bias discussion](https://navnoorbawa.substack.com/p/de-shaw-citadel-and-renaissance-run)
- [Caveats in Calibrating the OU Process (Hudson & Thames)](https://hudsonthames.org/caveats-in-calibrating-the-ou-process/)
- [DAX vs Euro Stoxx 50 Correlation: Spread Trading the Two Indices](https://derivativesjournal.com/indices/dax-vs-euro-stoxx-correlation)
