# Alpha04 — Literature Review: Cross-Timezone Equity Index Lead-Lag

Phase 1 of the alpha04 protocol. Genuine web research (not training-data recall),
covering the topics specified: international lead-lag, price discovery across time
zones, overnight information transmission, futures-vs-cash price discovery,
asynchronous/non-synchronous trading, global spillovers, cross-market momentum,
market opening effects. Goal: establish what's actually known before writing a
single line of hypothesis or strategy code, including the negative/cautionary
evidence — not just the flattering studies.

## 1. The core established finding: sequential price discovery, US-led

Markets open and close in a fixed daily sequence (Asia → Europe → US → Asia...).
Multiple independent literatures converge on the same basic fact: **information
that arrives while a market is closed shows up in that market's return once it
reopens, and the market that was open most recently before you tends to carry the
most explanatory power** — not just "the US" unconditionally.

- Lead-lag relationships between the US industry index and six other major
  countries (1973–2021): US weekly returns, especially materials/energy,
  significantly Granger-cause other countries' industry returns — the US plays a
  leading international role. ([Springer/Financial Innovation](https://link.springer.com/article/10.1186/s40854-022-00439-1))
- US-to-Asia-Pacific return spillover has *increased* over time, particularly
  after 1997, 2008, 2015, and COVID — i.e., this is not a static, stable-forever
  relationship, its strength has been regime-dependent. Developed Asia-Pacific
  markets are more exposed to US shocks than emerging ones. ([PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC10721036/))
- A given index is "mostly affected by the indices which open/close just before
  it" — i.e., the *most recently active* market matters most, not simply "the US"
  as a universal leader. This is an important nuance for alpha04: for Europe, the
  most recently active market before European open is **Asia**, not the US
  (Wall Street closed hours earlier and Asia has already digested and re-priced
  a chunk of that information by the time Europe opens).

## 2. Cross-market overnight/intraday momentum — the closest match to our hypothesis

The most directly relevant and most recent finding:

- **"Cross-market overnight time-series momentum" (COTSM)**, Journal of
  International Financial Markets, Institutions and Money, Oct 2025: the US
  market's **last half-hour return predicts the next day's first half-hour
  return** in international markets. Statistically significant in-sample and
  out-of-sample. Reported to **remain profitable after transaction costs**,
  strongest when the international market's spread is low or information
  uncertainty is high. ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1042443125001295), [SSRN companion](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4651331))
  — full text is paywalled; exact magnitude/Sharpe figures could not be
  independently verified, only the abstract-level claims above. This should be
  treated as a *plausibility signal*, not a number to target.
- Broader intraday time-series momentum literature: statistically and
  economically significant in **12 of 16** developed international markets
  tested, stronger on high-volatility/high-volume days and around major news.
  Notably **not pervasive in Asia-Pacific** — evident in some markets (China,
  Japan) but weaker than the US evidence. ([Reading repository](https://centaur.reading.ac.uk/95566/1/Accepted-Version.pdf), [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S138641812100001X))
  — this directly warns against assuming the effect is uniform across our
  13-instrument universe; it should be tested per-market, not pooled and
  assumed.

## 3. The specific mechanical reason Asia is the "cleanest" test case

Research using index futures across 12 countries (2000–2011) found Asian markets'
trading performance on US-overnight-based strategies **surpassed** European
markets' performance, with the explicit reason given: **the US return is the
only overnight information Asia receives** before it opens (nothing else trades
in between). Europe, by contrast, opens *after* Asia has already reacted to the
same US information — so a naive "US closed higher → buy Europe at Europe's
open" signal is contaminated by Asia's own intervening reaction, diluting or
reversing the raw relationship. ([search synthesis](https://eprints.qut.edu.au/60251/1/Byeongung_An_Thesis.pdf))

**Implication for Phase 2/3**: US→Asia is mechanically the cleanest test of the
lead-lag hypothesis (single, uncontaminated hop). US→Europe and Asia→Europe are
both plausible but are testing a different, noisier, two-hop relationship.
This should shape which pairs get tested first, not be discovered after the
fact by seeing which one "works."

## 4. Known criticism #1: non-synchronous trading is a real but partial confound

Lo & MacKinlay's foundational work on non-synchronous trading shows that when
markets/securities don't trade at literally the same moment, **mechanical,
non-information-based autocorrelation appears in the data purely from the
staggered sampling** — this can masquerade as a "lead-lag" effect that has
nothing to do with genuine information transmission. ([NBER](https://www.nber.org/papers/w2960), [ResearchGate](https://www.researchgate.net/publication/38007980_An_Econometric_Analysis_of_Nonsynchronous_Trading))

Important nuance, not just a caveat to wave away: one estimate (Atchison et al.)
found non-synchronous trading predicts only ~4 percentage points of daily
autocorrelation, against an observed ~30% — i.e., **non-synchronous trading is a
real contributor but does NOT fully explain observed cross-market
predictability**. This cuts both ways for alpha04: it means the artifact is real
and must be actively ruled out (Phase 8's random-pairing permutation test is
partly designed for exactly this), but it also means "it's just non-sync
trading" is not automatically the correct null hypothesis either — genuine
information transmission is the more literature-supported explanation for the
residual.

## 5. Known criticism #2: costs can flip a good-looking pre-cost result to negative

The most important cautionary, non-flattering data point found: a documented
strategy going long S&P 500 futures in a specific overnight window (2:00–3:00
window) earned a **pre-transaction-cost Sharpe of 1.1**, which **became −0.5**
once realistic bid-ask spread costs were applied. ([search synthesis, overnight linkages literature](https://eprints.qut.edu.au/60251/1/Byeongung_An_Thesis.pdf))

More generally: intraday/overnight momentum returns are frequently "too low to
cover bid-ask spreads, transaction costs, and costs from trades with
insufficient volume" — when researchers simulate buying at the offer and selling
at the bid (rather than the mid), average results turn negative across size
categories. ([search synthesis](https://arxiv.org/pdf/1005.3535))

This is directly relevant given our own alpha01/alpha02 experience this
research programme: both had real, statistically-distinguishable-from-noise
raw effects that were fragile or failed once realistic costs were applied.
Alpha04 should be expected, on priors from the literature itself, to face the
same risk — this is not a strategy family where "small effect, big cost
sensitivity" would be surprising.

## 6. Futures-vs-cash price discovery (contextual, not the primary hypothesis)

Separately from cross-timezone lead-lag, there's a well-established literature
that index *futures* lead the *cash* index for the same market by roughly
0–25 minutes (varies by study/period), because new information is priced into
the more liquid, lower-friction futures market first. ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S1544612322002008), [research synthesis](https://www.tandfonline.com/doi/full/10.1080/1331677X.2022.2090404))
This is a *same-market, same-timezone* effect and is **not** what alpha04 is
testing (we don't have separate futures vs. cash feeds for the same index in
our data — our CFD price series is a single feed per instrument) — noted here
only so it isn't confused with the cross-timezone hypothesis, and to flag that
"lead-lag" in the literature sometimes refers to this unrelated phenomenon.

## 7. Summary: what this means for Phases 2–4

- **Direction is not obvious and should not be assumed.** The literature
  supports "most recently active market leads," which for our universe likely
  means: US leads Asia (clean), Asia leads Europe (clean-ish), US leads Europe
  (two-hop, likely contaminated/weaker) — this needs to be measured, not
  assumed, per the user's explicit instruction not to presuppose the direction.
- **Effect is not literature-guaranteed to be uniform.** 12/16 markets in one
  study, weaker in Asia-Pacific in another — expect heterogeneity by instrument,
  and don't average it away.
- **Realistic costs are a live, literature-documented threat**, not a
  formality — a real precedent exists of a pre-cost Sharpe 1.1 becoming −0.5.
- **Non-synchronous trading is a real, partial mechanical confound** that must
  be actively tested for (Phase 8 permutation test), not assumed away, but the
  literature also doesn't support "it's 100% just an artifact."
- **Relationship strength is time-varying** (US→Asia-Pacific spillover
  documented to have strengthened after 1997/2008/2015/COVID) — Phase 4's
  Discovery/Validation/Final-OOS split and Phase 7's multi-period robustness
  check are directly relevant, not boilerplate.

## Sources
- [Industry return lead-lag relationships between the US and other major countries](https://link.springer.com/article/10.1186/s40854-022-00439-1)
- [Market return spillover from the US to the Asia-Pacific Countries](https://pmc.ncbi.nlm.nih.gov/articles/PMC10721036/)
- [Cross-market overnight time-series momentum (ScienceDirect)](https://www.sciencedirect.com/science/article/abs/pii/S1042443125001295)
- [Cross-Market Intraday Time-Series Momentum (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4651331)
- [Intraday time series momentum: global evidence and links to market characteristics](https://www.sciencedirect.com/science/article/abs/pii/S138641812100001X)
- [Intraday Time Series Momentum: International Evidence (Reading repository)](https://centaur.reading.ac.uk/95566/1/Accepted-Version.pdf)
- [International Stock Market Linkages: Are Overnight Returns on the U.S. Market... (QUT thesis)](https://eprints.qut.edu.au/60251/1/Byeongung_An_Thesis.pdf)
- [An Econometric Analysis of Nonsynchronous Trading (NBER, Lo & MacKinlay)](https://www.nber.org/papers/w2960)
- [Intraday Patterns in the Cross-section of Stock Returns](https://arxiv.org/pdf/1005.3535)
- [Measuring the dynamic lead–lag relationship between the cash market and stock index futures market](https://www.sciencedirect.com/science/article/abs/pii/S1544612322002008)
- [The time-varying lead-lag relationship between index futures and the cash index](https://www.tandfonline.com/doi/full/10.1080/1331677X.2022.2090404)
