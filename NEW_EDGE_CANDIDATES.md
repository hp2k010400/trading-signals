# New Edge Candidates — Ranked

10 hypotheses, each tied to a data source verified obtainable in
`NEW_DATA_SOURCES_INVESTIGATION.md`. Ranked by economic plausibility,
empirical support, data availability, cost feasibility, expected opportunity
frequency, novelty, and potential independence from existing WATCHLIST/
REJECTED edges. Not all need to be tested — this is a priority queue, not a
requirement to exhaust.

| # | Hypothesis | Data | Family | Plausibility | Empirical support | Cost | Freq. | Novelty | Independence |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **COT commercial (hedger) net positioning as a directional signal** for SP500/NAS100/US30/US2000 | CFTC COT, free | Futures info / positioning | Real hedging activity, informed-flow story | Mixed but real (ScienceDirect supportive, JKU paper against extreme-reversal specifically) | Free | Weekly signal, daily-applicable | High | High (new info source) |
| 2 | **Yield curve slope regime** (2s10s / 3m10y) conditioning equity index daily return distribution | FRED, free | Cross-asset / macro regime | Very strong (Estrella-Mishkin recession literature) | Very strong for recession prediction; weaker/more debated specifically for short-horizon equity return conditioning | Free | Daily-applicable | High | High |
| 3 | **COT speculator (non-commercial) positioning extremes → reversal** | CFTC COT, free | Futures info / positioning | Classic "crowded trade" story | Weakest of the COT variants — directly contradicted by cited research (extreme positions don't reliably predict reversal) | Free | Weekly | Medium (same data as #1) | Medium (correlated with #1) |
| 4 | **FX carry / short-rate differential** effect on AUDCAD/AUDNZD | FRED short rates, free | Cross-asset | Strong (uncovered interest parity failure / forward premium puzzle is one of the most replicated FX anomalies) | Strong, but narrow instrument scope (2/13 instruments) | Free | Daily-applicable | Medium | Medium |
| 5 | **COT week-over-week positioning change (flow, not level)** | CFTC COT, free | Futures info / positioning | Plausible (rate-of-change captures crowd momentum/exhaustion) | Less directly cited than level-based approaches | Free | Weekly | Medium (same data as #1) | Medium |
| 6 | **COT positioning divergence between correlated index pairs** (e.g. NAS100 vs SP500 speculative net position spread) as relative value | CFTC COT, free | Relative value | Plausible extension of alpha05's rejected price-cointegration idea using a genuinely different information layer on the same pairs | Untested combination, no direct citation found | Free | Weekly | High (novel combination) | Medium (same instruments as rejected alpha05) |
| 7 | **Gold COT positioning as cross-asset risk-sentiment proxy** for equity index returns | CFTC COT, free | Cross-asset | Plausible (gold as classic fear gauge) but more speculative mechanism | No direct citation found for this specific combination | Free | Weekly | High | High |
| 8 | **COT trader concentration (top-4/top-8) as a crowding/tail-risk signal** | CFTC COT, free | Futures info / positioning | More a risk/margin-monitoring metric than a documented return predictor | Weak — not the standard use case in the literature found | Free | Weekly | Medium | Medium |
| 9 | **Real futures volume/OI (Databento) validating or overturning alpha06's rejected illiquidity-premium finding** | Databento, ~$125 free credit then paid | Volume / microstructure | Directly resolves alpha06's own flagged caveat (spread proxy != real volume) | N/A — this is a methodological re-test, not a new literature claim | Paid (bounded) | Daily | Medium (re-test, not new) | Low (same hypothesis family as rejected E06) |
| 10 | **FRED macro regime filter applied to TSM** (already WATCHLIST) | FRED, free | Cross-asset / regime | Reuses a known-fragile edge with new conditioning info | N/A — exploratory | Free | N/A | Low (reuses existing edge) | Low (correlated with E01/TSM by construction) |

## Selected: #1 — COT commercial net positioning, US equity index futures

Chosen over #2 (yield curve) because it produces a naturally pre-specifiable,
single continuous signal (commercial net position, z-scored) with fewer
researcher degrees of freedom than deciding a yield-curve regime threshold
and a corresponding trading response — matters given how much of this
research programme's prior failures trace back to exactly that kind of
design flexibility. It also maps directly onto instruments this research
programme already knows well (SP500/NAS100/US30/US2000), and both COT and
yield-curve data remain in the queue regardless — #2 is the natural Edge #2
candidate if #1 clears or decisively fails the gates.

Explicitly not chosen: #3 (weaker literature support than #1, using the same
data), #9 (needs paid data and is a re-test rather than a fresh hypothesis —
good second-priority item once a budget decision is made), #10 (reuses an
existing fragile edge rather than searching for a genuinely independent one,
which cuts against the "independence matters" principle even though it's a
legitimate fresh pre-registration).
