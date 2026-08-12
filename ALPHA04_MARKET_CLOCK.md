# Alpha04 — Phase 2: Market Clock Mapping

Explicit mapping of when each region's underlying cash exchange is actually open,
so Phase 3's descriptive test measures genuine sequential (closed-market-to-open)
lead-lag rather than accidentally measuring two markets that are simultaneously
open and just correlated in real time (which is a different, non-lead-lag
phenomenon and would misleadingly look like "prediction").

Note: our broker data (CFD-style) ticks for most of the 24h day for these
instruments, but what matters for a genuine lead-lag/information-transmission
hypothesis is the underlying cash exchange's real trading hours — that's when
new information actually gets impounded via real order flow and price
discovery, not just when a CFD happens to have a quote.

Instrument universe for alpha04 (equity indices only — this hypothesis is
specifically about equity index lead-lag; the two FX crosses used in alpha02 are
dropped here): **DAX, FRA40, EU50, UK100** (Europe) · **NAS100, SP500, US30,
US2000** (US) · **JP225, AUS200, HK50** (Asia-Pacific).

## Regular trading hours (local exchange time → UTC → broker time, UTC+3)

| Region | Instruments | Local hours | UTC (approx, ex-DST) | Broker time (UTC+3) |
|---|---|---|---|---|
| Australia (ASX) | AUS200 | 10:00–16:00 AEST | 00:00–06:00 | 03:00–09:00 |
| Japan (TSE) | JP225 | 9:00–15:00 JST (lunch 11:30–12:30) | 00:00–06:00 (lunch 02:30–03:30) | 03:00–09:00 (lunch 05:30–06:30) |
| Hong Kong (HKEX) | HK50 | 9:30–16:00 HKT (lunch 12:00–13:00) | 01:30–08:00 (lunch 04:00–05:00) | 04:30–11:00 (lunch 07:00–08:00) |
| Europe (Xetra/Euronext) | DAX, FRA40, EU50 | 9:00–17:30 CET/CEST | 07:00–16:30 (DST-dependent) | 10:00–19:30 |
| UK (LSE) | UK100 | 8:00–16:30 GMT/BST | 07:00–16:30 (DST-dependent) | 10:00–19:30 |
| US (NYSE/NASDAQ) | NAS100, SP500, US30, US2000 | 9:30–16:00 ET | 13:30–21:00 (DST-dependent) | 16:30–00:00(+1) |

DST shifts each region's UTC window independently (US/Europe/UK switch on
different calendar dates than each other), which mechanically shifts overlap
windows by up to an hour for a few weeks each spring/autumn — a real, literature
-acknowledged complication, not one we're the first to hit. Phase 3's script
should treat session boundaries as approximate and expect some noise right
around DST transition weeks rather than being surprised by it.

## The daily sequence (broker time, approximate)

```
02:00-03:00  AUS200 opens (first)
03:00        JP225 opens (~same time as AUS200, near-simultaneous, not sequential)
04:30        HK50 opens  (AUS200 + JP225 already trading ~1.5h)
06:00-09:00  AUS200 / JP225 close (JP225 has a lunch break 05:30-06:30)
10:00        DAX / FRA40 / EU50 / UK100 open  <- Asia (AUS200, JP225) is FULLY CLOSED,
                                                  HK50 still open for ~1h overlap
11:00        HK50 closes
16:30-17:30  NAS100 / SP500 / US30 / US2000 open  <- Europe is STILL OPEN (overlap,
                                                       not a clean closed-market handoff)
19:30        Europe closes (US has been open ~2-3h already)
23:00-00:00  US closes
00:00-02:00  <- DEAD ZONE: no major index in our universe has its underlying
                cash market open. CFDs still tick, but this isn't "a market."
02:00-03:00  AUS200/JP225 reopen -> cycle repeats
```

## Which pairs are genuinely "clean" lead-lag tests vs. contaminated/overlap

This directly answers the instruction not to accidentally treat overlapping
sessions as lead-lag:

1. **US close → Asia (AUS200, JP225) open — CLEANEST.** A true closed-market
   gap (~2-3h dead zone in between). Matches the COTSM literature's setup
   exactly (last-active-region close → next region's open). JP225/AUS200 open
   with zero intervening market having already reacted to the US session.
   HK50 opens 1.5h later, so its "open reaction" is contaminated by AUS200/JP225
   already having partially digested the same US information — HK50 should be
   tested as a secondary case, not pooled with AUS200/JP225 as if identical.

2. **Asia close (AUS200 + JP225 fully closed) → Europe open — CLEAN-ISH.** No
   dead zone (HK50 still open for ~1h into the European session), but AUS200 and
   JP225 are both fully closed and had several hours to fully price the prior
   US session plus their own local session before Europe opens. HK50's
   continued trading during the first hour of the European session is a minor
   contamination to note, not ignore.

3. **Europe → US open — NOT CLEAN, this is an overlap, not a lead-lag gap.**
   US opens ~2-3 hours *before* Europe closes. Any "Europe predicts US" test
   here is really testing "does Europe's return up to the moment US opens
   predict US's return after open" — a legitimate but different question
   (partial-session momentum into an already-open market), not a closed-to-open
   information-transmission test. Must not be conflated with case 1/2 in
   reporting.

4. **HK50 → Europe, JP225/AUS200 → HK50** — genuine but secondary/messier
   intra-Asia and Asia-to-Europe hybrid cases, worth testing per Phase 3's
   instruction to look at multiple horizons and pairs broadly, but not the
   primary clean test.

## What Phase 3 should test, given this

Per the directive's "look for a broad pattern, don't optimise for the best
horizon": test all of the following as separate, honestly-labeled cases rather
than pooling them or cherry-picking the cleanest one after seeing results:
- US close-window return → AUS200 open-window return (multiple horizons)
- US close-window return → JP225 open-window return (multiple horizons)
- US close-window return → HK50 open-window return (multiple horizons, flagged
  as contaminated by AUS200/JP225's prior reaction)
- Asia (AUS200+JP225) full-session return → Europe open-window return (multiple
  horizons)
- Europe pre-US-open return → US open-window return (multiple horizons,
  labeled as an overlap-momentum test, not a closed-market handoff test)

Each of these should also be tested in **both directions** (e.g., does Asia's
open ALSO get tested as leading nothing before it, as a negative control) and
against the **random-pairing/random-timing permutation null** in Phase 8, to
separate genuine sequential information transmission from non-synchronous-
trading artifacts (per the Lo-MacKinlay caution in `ALPHA04_LITERATURE.md`).
