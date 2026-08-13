# ES Open Interest — Data Contamination Audit (Phase 2)

## 1. What ES history E27 used, and what we have already observed

E27 used Databento `GLBX.MDP3`, continuous symbol `ES.n.0` (open-interest
roll rule), `ohlcv-1h` + `statistics` schemas, **2010-06-06 → 2026-08-13**
(the entire available Databento history for this dataset — confirmed via
`metadata.get_dataset_range`, not assumed). We have directly observed, for
this exact window:
- Full-history and by-period (Discovery/Validation/Final-OOS) correlation
  signs and magnitudes at 2/4/8-week horizons.
- Year-by-year PF and R for a 2/4/8-week symmetric long/short strategy.
- Cost-stress behavior up to 3x total multiplier.
- A parameter-stability sweep across 5 lookback values (504–1008 days).
- Permutation-test percentile (83.8th).
- Cross-instrument (NQ/GC/CL) comparison at the same horizons.

This is an unusually complete picture of exactly how this signal behaves
across this specific 16-year window — far more than a casual glance. **Any
new test run on this same 2010–2026 ES window is not blind**, regardless of
how the signal itself is constructed or re-parameterized.

## 2. Which parameters/results influenced this follow-up

The follow-up was directly motivated by observing: the 8-week horizon
specifically outperforming 2-week/4-week; the specific lookback range
(504–1008 days) showing a stable PF 1.10–1.15 plateau; the specific
permutation percentile (83.8%); and the specific instrument (ES) being the
one that worked while NQ/GC/CL did not. **All of these are now observed
prior evidence, not independently chosen design decisions.** Per instruction,
none of them may be re-selected as if freshly chosen in Phase 4 — a new
specification must be committed to on grounds independent of having seen
these numbers (addressed in Phase 4's pre-registration).

## 3. Critical new finding: the front-month continuous OI series has a severe roll artifact

While researching Phase 1's mechanism, a direct check of the raw data
(`databento_statistics_v2.csv`, `ES.n.0`) found **65 roll events** across
the sample, each showing a mechanical, same-day jump in reported open
interest of roughly 500,000–700,000 contracts (30–50% of the pre-roll
level) — for example:

```
2010-06-15  instrument_id=6640    oi=1,482,925
2010-06-16  instrument_id=26714   oi=2,199,082   <- +48% in one day
```

This is **not** a market event — it is Databento's `.n.0` continuous symbol
switching which single expiration is labeled "front month" (based on
highest open interest), at which point the *reported* OI jumps from the
old front contract's (declining, as holders roll out) open interest to the
new front contract's (already-built-up, since participants roll in over the
preceding weeks) open interest. **The front-month-only OI series E27 used
does not track genuine aggregate market commitment — it tracks a
mechanically discontinuous relabeling that recurs on a fixed quarterly
calendar**, independent of any real information content.

E27's signal used a ~1-month (21 trading day) OI-change window. Since rolls
recur roughly every 63 trading days, a material fraction of E27's signal
observations plausibly straddled a roll date and captured this artifact
rather than a genuine change in market-wide positioning. **This means
E27's headline result cannot be trusted as evidence of the mechanisms
described in `ES_OI_MECHANISM_REVIEW.md`** — it may be partly or largely an
artifact of contract-relabeling mechanics. This does not change E27's
verdict (already permanently REJECTED, not being revisited), but it is
directly disqualifying evidence against treating E27's specific numbers as
a reliable prior for anything in EDGE30.

**Direct implication for Phase 4**: any new pre-registration must construct
open interest as the **sum across all active contract months** (not a
single "front month" label), which is the standard, artifact-free way this
is done in professional term-structure research — confirmed available from
Databento (`stype_in=parent`, symbol `ES.FUT`, cost ~$0.44 for the full
2010–2026 window) but **not yet pulled or used for any test**.

## 4. What data remains genuinely untouched

- **Nothing within 2010–2026** is untouched in the relevant sense — even a
  corrected (total-OI, roll-artifact-free) reconstruction over this same
  calendar window is still a re-examination of a period whose broad outcome
  (ES's price path, its volatility regimes, roughly how a naive long/short
  OI-based rule performed) has already been directly observed. Per
  instruction, this must **not** be described as blind out-of-sample data,
  no matter how the signal itself is reconstructed.
- **Genuinely untouched data**: ES trading activity from **2026-08-13
  onward** (today) has not been observed in any form. This is the only
  data that qualifies as truly blind for this specific hypothesis.
- Databento's `GLBX.MDP3` dataset itself does not extend earlier than
  2010-06-06 (confirmed directly via the API, not assumed) — there is no
  older Databento history to draw on as a pre-2010 "untouched" period.

This conclusion carries directly into Phase 3.

## Phase 3 — Search for genuinely new validation data (investigated in the ordered sequence requested)

1. **Older ES history not in E27**: Databento's `GLBX.MDP3` does not extend
   earlier than 2010-06-06 (confirmed directly via `metadata.get_dataset_range`,
   not assumed). No older Databento history exists to draw on.

2. **Additional Databento schema not yet used**: full-term-structure ES
   statistics (`stype_in=parent`, symbol `ES.FUT`) — confirmed available,
   costs ~$0.44 for the full 2010–2026 window. This would fix the
   roll-artifact construction problem (Section 3), but **does not solve the
   temporal-independence problem** — it is still the same already-partially-
   observed 2010–2026 calendar window.

3. **Equivalent ES data from another reliable source, specifically for the
   PRE-2010 period**: a promising but **unverified** lead — CFTC's own COT
   data (the same public, free API already used throughout the E19–E26
   queue) may contain S&P 500 futures open-interest history extending back
   to 2006 or earlier via a legacy (non-"Consolidated") category, per
   third-party (YCharts) sourcing claims. This was **not confirmed or
   pulled this session** — it needs direct verification (exact CFTC
   category name, confirmed start date, confirmed it doesn't collapse to
   the same 2010 start the "Consolidated" category showed in the E19 pull)
   before it could be trusted as genuinely independent data. If confirmed,
   it would be **weekly, trader-category granularity** (CFTC's native
   format), not daily aggregate OI — a materially different signal
   construction from E27's, requiring its own honest adaptation, not a
   drop-in reuse. Flagged as a real lead for potential follow-up, not
   acted on this session given scope.

4. **Related S&P 500 futures contracts (Micro E-mini, MES)**: launched
   2019 — only ~7 years of history, and shares the *same* underlying index
   and largely the *same* economic drivers as ES, so it would not be
   independent in the sense that matters (a common macro/equity-drift shock
   would move both together) — useful at most as a weak corroboration, not
   real independent evidence.

5. **Forward validation using newly arriving data**: the only source
   identified that is **unambiguously, completely clean** — no construction
   ambiguity, no partial-history questions, no provenance verification
   needed. ES trading activity from 2026-08-13 onward has not been observed
   in any form. Cost is trivial to continue collecting (already-established
   Databento access).

### Phase 3 conclusion
No already-available, unambiguously independent validation data exists.
The defensible path is **forward collection** (clean but requires waiting)
optionally supplemented by the **pre-2010 CFTC lead** (promising, requires
verification work not yet done, and a different-granularity signal). Phase
4's pre-registration is built around forward validation as the primary,
trustworthy test — not a same-window re-test dressed up as validation.
