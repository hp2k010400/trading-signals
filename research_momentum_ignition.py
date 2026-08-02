"""
research_momentum_ignition.py

HYPOTHESIS 4: Momentum Ignition (post-shock continuation).

MARKET LOGIC
------------
Occasionally a single M1 bar shows an unusually large range AND volume
spike relative to its own recent local activity — well beyond normal
noise. This is typically driven by a large informed order, a news
release, or a stop cascade crossing a liquidity void. Market
microstructure research on price impact shows that moves carrying real
informational content tend to keep drifting in the same direction for
a short period afterward, because the market needs time to fully
reprice around new information (the order can't all be absorbed
instantly) — as opposed to a pure noise spike, which has no reason to
persist.

This is a DIFFERENT mechanism from hypothesis 1 (liquidity sweep),
which explicitly bets a level-break FAILS and reverts. Momentum
ignition bets a genuine shock, once confirmed as unusually large on
BOTH range and volume (not just one noisy metric), CONTINUES. No
reference level required, no compression precursor required — this is
about the shock itself, not what preceded it.

FALSIFIABLE PREDICTION: if this is real, entering in the direction of
a genuine (large range + large volume) shock should show positive
expectancy over the following minutes/hours, clearing well above the
already-disproven baseline. If the "genuine shock" filter doesn't do
better than an ordinary big-range bar with no volume confirmation,
that's evidence volume isn't adding real information here and the
whole thing is likely noise-chasing.

SIGNAL DEFINITION
------------------
1. M1 bars only (no H1/H4 resampling — this is a fast, short-horizon
   effect).
2. Rolling thresholds computed via pandas' native `.rolling().quantile()`
   (vectorized, not a Python-level rolling apply — that would be far
   too slow at M1 resolution over 8 years) and SHIFTED by 1 bar so the
   threshold never includes the bar being tested (no look-ahead).
3. Ignition bar = range > rolling RANGE_PCTL threshold of trailing
   LOOKBACK bars AND tick_volume > rolling VOL_PCTL threshold of the
   same window (volume confirmation is the whole point — a big range
   bar on thin volume is just a gap/noise, not a genuine shock).
4. Only scanned during the liquid window 06:00-20:00 UTC — outside
   that, a "big" bar is more likely a liquidity-void artifact than a
   real informed shock.
5. Direction = sign(close - open) of the ignition bar.
6. Entry = close of the ignition bar, in that direction.
7. Stop = opposite extreme of the ignition bar (its low if long, high
   if short) plus a small buffer — a genuine informational move
   shouldn't fully retrace through its own origin bar.
8. Exit = fixed R target (TP_GRID) or TIME_STOP_MIN minutes (short —
   this is a fast-decaying drift, not a multi-hour trend trade).
9. Max MAX_PER_DAY signals per instrument per day.

If tick_volume isn't available in a given file, this script says so
explicitly and falls back to range-only (clearly weaker, flagged in
output) rather than silently pretending volume was checked.

COSTS: round-trip price cost / each trade's actual stop distance, same
convention as the other three research scripts.

Run in Codespaces (needs *_M1_ftmo.csv):
    python -u research_momentum_ignition.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
LOOKBACK        = 500     # M1 bars (~8h of trailing local activity)
RANGE_PCTL_GRID = [0.95, 0.98]
VOL_PCTL        = 0.95
SESSION_START_UTC = 6
SESSION_END_UTC   = 20
STOP_BUFFER_FRAC  = 0.10  # fraction of the ignition bar's own range
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
        direction = 1 if cl[i] > op[i] else (-1 if cl[i] < op[i] else 0)
        if direction == 0:
            continue
        entry = cl[i]
        buf = rng[i] * STOP_BUFFER_FRAC
        stop = lo[i] - buf if direction == 1 else hi[i] + buf
        sl_dist = abs(entry - stop)
        if sl_dist <= 0:
            continue

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

        cost_price = COST_PRICE[k] * SLIPPAGE_MULT.get(k, 1.0)
        cost_r = cost_price / sl_dist
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
print(f'\n{"="*78}\n  HYPOTHESIS 4 - MOMENTUM IGNITION (POST-SHOCK CONTINUATION)\n{"="*78}')

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
print('  at least one (range_pctl, time_stop, TP) combination, that result is')
print('  part of a plateau across neighbouring cells (not an isolated spike in')
print('  a 12-cell grid), AND >=6/9 instruments individually OOS-profitable at')
print('  that combination.')
print('  Otherwise: discard, do not cherry-pick the best cell.')
print(f'{"="*78}')
