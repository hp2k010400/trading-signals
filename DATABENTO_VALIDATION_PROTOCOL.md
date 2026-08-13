# Databento Futures Volume/OI — Validation Protocol

Applies uniformly to H1 (`EDGE27`), H2 (`EDGE28`), H3 (`EDGE29`), tested
strictly in that pre-committed order. Ranking was fixed in
`DATABENTO_DATA_AUDIT.md` before any data existed and does not change based
on results. If a candidate fails an early gate, it is rejected immediately
and the next pre-ranked candidate is tested — no filters, no parameter
rescue.

## Gate 1 — Descriptive phenomenon
Real data, no strategy, no costs, no filters. Correlation + top/bottom
quintile spread between the signal and the forward target variable, at the
horizons specified in each hypothesis doc, reported broadly (not optimised
for the best horizon). Reject immediately if the full-history relationship
isn't in the pre-registered direction and reasonably stable — same standard
used throughout this research programme (alpha0X, E19–E26).

## Gate 2 — Simplest executable strategy
Direction = sign of the (z-scored) signal, applied to the primary instrument
(ES first, per each hypothesis doc). No threshold/deadzone, no magnitude
weighting unless the hypothesis's own pre-registered mechanism specifically
requires it (stated in advance, not decided after Gate 1 results).
Vol-scaled position sizing (RISK_PCT convention used throughout this
programme).

## Gate 3 — Realistic costs
GROSS and NET at BASE cost (1.5x, this programme's standing convention) plus
the standard stress levels (BASE×1.0/1.2/1.5/2.0). NET is decision-relevant.
Cost points for ES/NQ/GC/CL need to be established from real FTMO CFD spread
data (via the existing `COST_POINTS`-style convention) before this gate —
noted as a dependency, not assumed.

## Gate 4 — Discovery / Validation / Final-OOS + yearly breakdown
50th/75th-percentile-of-date split, identical method used throughout this
programme. Yearly breakdown reported explicitly to catch single-period
concentration (the exact failure mode that killed E24 and E26).

## Gate 5 — Permutation / bootstrap null test
Circular-shift null (500 shifts), same method as E19/E22, appropriate given
both the signal and the return series carry their own serial correlation
(shifting preserves each series' internal structure, destroys only the
specific temporal pairing).

## Gate 6 — Generalisation across ES / NQ / GC / CL
Identical construction applied to all four instruments, no per-instrument
re-tuning. A result that only survives on the instrument it was discovered
on is treated as unconfirmed, not as four independent edges (per the
"independence matters" principle from the portfolio-of-edges directive).

## Gate 7 — Parameter stability and cost stress
Sweep the signal's lookback/z-score window around its pre-registered value
(report all values, do not adopt the best one — same discipline as E19/E22's
Gate 7). Cost stress already covered in Gate 3, cross-referenced here per
the user's explicit 7-gate structure.

## Decision rule
A candidate that survives all 7 gates with even a modest edge (e.g. PF
~1.15–1.30, positive NET expectancy, stable across periods, cost-robust,
reasonable parameter stability, reasonable opportunity frequency) is FROZEN
and classified `VALIDATED_SMALL_EDGE` or `VALIDATED_CORE_EDGE` in
`EDGE_LIBRARY.csv` — it is not rejected for being slow or unable to pass
FTMO alone. Testing stops immediately at the first such result; remaining
candidates are not tested until directed. A candidate that fails is
rejected outright and the next pre-ranked candidate proceeds — never
rescued with filters or re-optimisation.
