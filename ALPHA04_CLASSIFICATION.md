# Alpha04 — Descriptive Test Result and Classification

Real data, `alpha04_leadlag_descriptive_ftmo.py`, 2016–2026 (~1,150–1,350 daily
observations per case depending on data availability).

## The core hypothesis (genuine closed-market handoffs) is REJECTED

Three of the five cases tested are genuine closed-to-open handoffs (per
`ALPHA04_MARKET_CLOCK.md`) — this is what alpha04 actually set out to test:
does one region's *closed* session return predict the *next* region's open
reaction. All three show the same failure signature:

| Case | Full-history session corr | Discovery spread | Validation spread | Final OOS spread |
|---|---|---|---|---|
| SP500 → AUS200 | +0.0037 | +4.20bp | +10.92bp | **−11.24bp** |
| SP500 → JP225 | −0.0149 | +0.16bp | +6.43bp | **−12.41bp** |
| JP225 → DAX | +0.0202 | +5.36bp | −0.07bp | **+24.12bp** |

Full-history correlations are all essentially zero (|corr| < 0.03 at the
session horizon). Sign and magnitude are unstable across horizons within the
same case (no horizon dominates — the pattern the directive explicitly warned
against optimising for isn't even there to optimise). Critically, the period
breakdown **flips sign between Validation and Final OOS in both SP500-led
cases**, and JP225→DAX's Final OOS spread (+24bp) is an outlier relative to
its own Discovery (+5bp) and Validation (~0bp) — more consistent with a few
large days dominating a modest sample than a repeatable phenomenon.

This is a clean, decisive negative result on the actual hypothesis under test.
Per the pre-registered discipline (measure descriptively first, only advance to
a costed strategy if the raw phenomenon survives): **it does not survive.**
No stop-loss/filter/costed-strategy phase is warranted — advancing this to
Phase 5+ would just be dressing up noise.

**Alpha04 (cross-timezone closed-market equity index lead-lag) is REJECTED
because: the three genuine closed-to-open handoff cases (US→Asia ×2,
Asia→Europe) all show near-zero full-history correlation and sign-flipping
across Discovery/Validation/Final-OOS periods — no stable, repeatable
directional relationship exists in the tested horizons (5m–session).**

## The fourth case is a different phenomenon, not a rescue

The fifth case tested — DAX's return from its own open up to the moment SP500
opens, predicting SP500's open reaction — was explicitly labeled in
`ALPHA04_MARKET_CLOCK.md` as an **overlap** case, not a closed-market handoff
(SP500 opens ~2-3h before DAX closes). It showed a materially different,
more consistent signature: positive spread and positive correlation (+0.07 to
+0.10) at **every single horizon tested**, and consistent positive spreads in
both Discovery (+9.46bp) and Validation (+7.89bp) — the only case in this batch
that didn't sign-flip between those two periods. It decayed to near-zero in
Final OOS (−0.91bp, corr −0.01).

This is **not** evidence for alpha04's actual hypothesis (it's same-session
overlap momentum, not cross-timezone information transmission — matches the
"overlapping hours dominate price discovery" literature caution noted in
`ALPHA04_LITERATURE.md` §6, not the COTSM-style closed-handoff mechanism this
research was chasing). Per the same rule applied when alpha02 closed: this is
not something to chase right now by reframing alpha04 around it. If pursued,
it would need its own fresh, separately pre-registered hypothesis ("does
intraday momentum from Europe's session into the US open survive costs" — a
real, distinct, literature-supported question) rather than being smuggled in
as a save for the rejected alpha04 hypothesis.

## Classification: **REJECTED**

No permutation test, cost analysis, or strategy build is warranted for the
core hypothesis — it failed at the descriptive stage, which is exactly what
that stage is for. Archiving alpha04 as tested.
