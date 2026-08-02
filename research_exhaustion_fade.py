"""
research_exhaustion_fade.py

HYPOTHESIS 5: Post-Shock Exhaustion Fade — the direct mirror of
hypothesis 4 (momentum ignition), same shock-detection criteria,
direction flipped.

WHY THIS, WHY NOW
-------------------
Two independent "continuation" hypotheses have now failed with the
same unusual signature: win rates well under 50% (hypothesis 2's
post-open continuation: 30-50% WR; hypothesis 4's momentum ignition:
30-45% WR), not just "no edge" (~50% WR, PF~1.0 before costs) but
actively losing more than chance would predict. That pattern itself is
informative: a real coin-flip should land near 50%. Seeing it
consistently below that across two unrelated mechanisms points toward
genuine short-horizon mean reversion being present in this data, not
just noise.

This hypothesis tests that directly: a large range+volume shock bar is
often a liquidity-taking / exhaustion event — an aggressive order or
stop cascade that temporarily pushes price further than genuine
supply/demand supports, which liquidity providers then fade, producing
a short-term reversion. This is the classic "climax bar" concept, and
it has a real mechanism behind it (liquidity provision economics), not
just "hypothesis 4 lost so try the opposite."

DEVIL'S ADVOCATE CONCERN — STATED BEFORE RUNNING, NOT AFTER
--------------------------------------------------------------
The most likely alternative explanation for hypothesis 4's losses is
NOT genuine exhaustion reversion — it's bid-ask bounce: consecutive
1-minute closes can show artificial negative autocorrelation purely
from price oscillating between bid and ask, which would make
"continuation loses" look identical to "fading wins" without either
being a real, tradeable edge. The realistic cost model already in use
(actual spread+slippage+commission / actual stop distance) is exactly
the test that should kill a bid-ask-bounce artifact once you have to
pay the spread to trade it. If this hypothesis clears PF>1.3 AFTER
that realistic cost model, that's meaningful evidence against the
bounce explanation. If it only works with costs stripped out, that
confirms the bounce explanation and this gets discarded too.

SIGNAL DEFINITION
------------------
Identical shock detection to hypothesis 4 (range + volume both in top
percentile of trailing local activity, liquid session hours only,
vectorized rolling().quantile().shift(1) thresholds, no look-ahead).
Only the trade direction is flipped: fade the shock bar's own
direction instead of following it. Stop sits beyond the ignition bar's
OWN extreme in the trade's risk direction (i.e. for a fade-short after
an up-shock, stop is above the ignition bar's high, since a genuine
reversal shouldn't need to revisit the shock's own extreme).

Includes the same MIN_SL_COST_MULT stale-data guard added to
research_momentum_ignition.py after NATGAS showed WR=0.7%/Exp(R)=-5.76
in the first coarse run — a near-zero-range stale bar exploding into a
huge R-multiple once divided by its own tiny stop distance, not a real
result.

COSTS: round-trip price cost / actual stop distance, same convention
as every other research script here.

Run in Codespaces (needs *_M1_ftmo.csv):
    python -u research_exhaustion_fade.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── Config (identical to research_momentum_ignition.py for a clean A/B) ──────
LOOKBACK        = 500
RANGE_PCTL_GRID = [0.95, 0.98]
VOL_PCTL        = 0.95
SESSION_START_UTC = 6
SESSION_END_UTC   = 20
STOP_BUFFER_FRAC  = 0.10
MIN_SL_COST_MULT  = 3.0
TIME_STOP_MIN     = [60, 120]
TP_GRID           = [1.5, 2.0, 3.0]
MAX_PER_DAY       = 3

FILES = {
    'DAX':    'GER40_M1_ftmo.csv',
    'NAS100': 'US100_M1_ftmo.csv',
    'SP500':  'US500_M1_ftmo.csv',
    'US30':   'US30_M1_ftmo.csv',
    'EURUSD': 'EURUSD_M1_ftmo.csv',
    'GBPUSD': 'GBPUSD_M1_ftmo.csv',
    'USDJPY': 'USDJPY_M1_ftmo.csv',
    'GOLD':   'XAUUSD_M1_ftmo.csv',
    'NATGAS': 'NATGAS_M1_ftmo.csv',
}

COST_PRICE = {
    'DAX': 2.0, 'NAS100': 2.0, 'SP500': 0.8, 'US30': 4.0,
    'EURUSD': 0.00020, 'GBPUSD': 0.00026, 'USDJPY': 0.026,
    'GOLD': 0.50, 'NATGAS': 0.010,
}
SLIPPAGE_MULT = {'NATGAS': 3.0}

IS_OOS_SPLIT = '2024-01-01'

_m1 = {}
_has_volume = {}


def load(k):
    fn = FILES[k]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    cols = {c.lower(): c for c in df.columns}
    need = ['time', 'open', 'high', 'low', 'close']
    if not all(c in cols for c in need):
        print(f'  {k}: UNEXPECTED SCHEMA {list(df.columns)} — skipping, needs mapping')
        return False
    rename = {cols[c]: c for c in need}
    vol_col = cols.get('tick_volume') or cols.get('volume')
    if vol_col:
        rename[vol_col] = 'volume'
    df = df.rename(columns=rename)
    ts = pd.to_numeric(df['time'], errors='coerce')
    if ts.notna().mean() > 0.99:
        df['time'] = pd.to_datetime(ts, unit='s', utc=True)
    else:
        df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df['range'] = df['high'] - df['low']

    has_vol = 'volume' in df.columns
    _has_volume[k] = has_vol
    if has_vol:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)

    _m1[k] = df
    return True


def detect_and_simulate(k, range_pctl, tp_r, time_stop_min):
    df = _m1[k]
    has_vol = _has_volume[k]
    n = len(df)

    range_thresh = df['range'].rolling(LOOKBACK).quantile(range_pctl).shift(1)
    ignite = df['range'] > range_thresh
    if has_vol:
        vol_thresh = df['volume'].rolling(LOOKBACK).quantile(VOL_PCTL).shift(1)
        ignite = ignite & (df['volume'] > vol_thresh)

    idx = df.index
    hrs = idx.hour
    ignite = ignite & (hrs >= SESSION_START_UTC) & (hrs < SESSION_END_UTC) & (idx.dayofweek < 5)

    op = df['open'].values; hi = df['high'].values; lo = df['low'].values
    cl = df['close'].values; rng = df['range'].values
    ignite_pos = np.where(ignite.values)[0]

    day_count = {}
    trades = []

    for i in ignite_pos:
        d = idx[i].date()
        if day_count.get(d, 0) >= MAX_PER_DAY:
            continue
        shock_dir = 1 if cl[i] > op[i] else (-1 if cl[i] < op[i] else 0)
        if shock_dir == 0:
            continue
        direction = -shock_dir  # FADE the shock, not follow it

        entry = cl[i]
        buf = rng[i] * STOP_BUFFER_FRAC
        # stop beyond the ignition bar's OWN extreme, on the trade's risk side
        stop = hi[i] + buf if direction == -1 else lo[i] - buf
        sl_dist = abs(entry - stop)
        cost_price_i = COST_PRICE[k] * SLIPPAGE_MULT.get(k, 1.0)
        if sl_dist < cost_price_i * MIN_SL_COST_MULT:
            continue  # stale/near-zero-range artifact guard, see docstring

        tp = entry + sl_dist * tp_r if direction == 1 else entry - sl_dist * tp_r
        end = min(i + 1 + time_stop_min, n)
        if i + 1 >= end:
            continue
        r_gross = None
        for j in range(i + 1, end):
            if direction == 1:
                if lo[j] <= stop: r_gross = -1.0; break
                if hi[j] >= tp:   r_gross = tp_r;  break
            else:
                if hi[j] >= stop: r_gross = -1.0; break
                if lo[j] <= tp:   r_gross = tp_r;  break
        if r_gross is None:
            r_gross = (cl[end-1]-entry)/sl_dist if direction == 1 else (entry-cl[end-1])/sl_dist

        cost_r = cost_price_i / sl_dist
        day_count[d] = day_count.get(d, 0) + 1
        trades.append({'instrument': k, 'time': idx[i], 'r_net': r_gross - cost_r})
    return trades


def stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0, total_r=0.0)
    w = r[r > 0]; l = r[r <= 0]
    pf = round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else float('inf')
    return dict(n=len(r), wr=round(len(w)/len(r)*100, 1), pf=pf,
                exp=round(r.mean(), 3), total_r=round(r.sum(), 1))


def fmt(label, s, width=24):
    return (f'  {label:<{width}}  N={s["n"]:>5}  WR={s["wr"]:>5.1f}%  '
            f'PF={s["pf"]:>6.2f}  Exp(R)={s["exp"]:>+6.3f}  TotalR={s["total_r"]:>+9.1f}')


# ── Load ─────────────────────────────────────────────────────────────────────
print('Loading FTMO M1 data...')
loaded = [k for k in FILES if load(k)]
missing = [k for k in FILES if k not in loaded]
print(f'Loaded {len(loaded)}/9: {loaded}')
if missing:
    print(f'MISSING or unreadable *_M1_ftmo.csv: {missing}')
for k in loaded:
    vol_note = 'volume OK' if _has_volume[k] else 'NO VOLUME — range-only fallback, weaker signal'
    print(f'  {k}: {_m1[k].index[0].date()} -> {_m1[k].index[-1].date()}  ({len(_m1[k]):,} bars)  [{vol_note}]')

# ── Coarse pass ───────────────────────────────────────────────────────────────
print(f'\n{"="*78}\n  HYPOTHESIS 5 - POST-SHOCK EXHAUSTION FADE\n{"="*78}')

for range_pctl in RANGE_PCTL_GRID:
    for time_stop_min in TIME_STOP_MIN:
        for tp_r in TP_GRID:
            print(f'\n=== range>={int(range_pctl*100)}th pctl (+vol conf), '
                  f'time_stop={time_stop_min}min, TP={tp_r}R ===')
            all_oos = []
            for k in loaded:
                trades = detect_and_simulate(k, range_pctl, tp_r, time_stop_min)
                oos_r = [t['r_net'] for t in trades if str(t['time'].date()) >= IS_OOS_SPLIT]
                all_oos += oos_r
                print(fmt(f'{k} OOS', stats(oos_r)))
            print(fmt('ALL INSTRUMENTS OOS', stats(all_oos)))

print(f'\n{"="*78}')
print('Coarse pass done. Decision rule (frozen before running):')
print('  ACCEPT for full validation pipeline only if OOS combined PF > 1.3 for')
print('  at least one (range_pctl, time_stop, TP) combination, part of a')
print('  plateau across neighbouring cells (not an isolated spike), AND >=6/9')
print('  instruments individually OOS-profitable at that combination.')
print('  If it only clears 1.3 with costs stripped out but not with them,')
print('  that confirms the bid-ask-bounce concern above -- reject.')
print(f'{"="*78}')
