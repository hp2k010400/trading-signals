"""
backtest_m1_vs_h1.py  -  Compare H1 vs M1 simulation accuracy
==============================================================
Runs the SAME strategies over the SAME date range (whatever the M1
CSVs cover) using two simulation methods:

  H1 SIM   Signal detected on H1 bars, trailing stop simulated on H1
  M1 SIM   Signal detected on H1 bars, trailing stop simulated on M1

The entry price, SL, direction are IDENTICAL in both.
Only the bar frequency used inside sim() differs.

This directly answers: is Trail_R=0.05 being overstated by H1 simulation?
If M1 avg_win << H1 avg_win, the H1 backtest is lying about the trail.

Run: python backtest_m1_vs_h1.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ACCOUNT  = 70_000
TRAIL    = 0.05

CSVSYMS_H1 = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}
CSVSYMS_M1 = {
    'EURUSD': 'EURUSD_M1.csv',    'GBPUSD': 'GBPUSD_M1.csv',
    'DAX':    'GER40_cash_M1.csv', 'NAS100': 'US100_cash_M1.csv',
    'SP500':  'US500_cash_M1.csv', 'UK100':  'UK100_cash_M1.csv',
    'GOLD':   'XAUUSD_M1.csv',
}

BASE_COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08
}

_cache = {}
def load(fn):
    if fn in _cache: return _cache[fn]
    if not os.path.exists(fn):
        _cache[fn] = None; return None
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    result = df.dropna() if len(df) > 100 else None
    _cache[fn] = result; return result

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    return int(a) if a < len(df) and df.index[int(a)] == ts else -1

def sim(df, ep, direction, entry, sl, trail, max_bars):
    """Simulate trailing stop using whatever bar frequency df is."""
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    tr = sl_d * trail; cs = sl; bst = entry; be = False
    rows = df.iloc[ep+1: ep+1+max_bars]
    for _, b in rows.iterrows():
        if direction == 1:
            if b['low'] <= cs: return (cs - entry) / sl_d
            bst = max(bst, b['high'])
            if not be and bst >= entry + sl_d: be = True; cs = entry
            if be:
                ns = bst - tr
                if ns > cs: cs = ns
        else:
            if b['high'] >= cs: return (entry - cs) / sl_d
            bst = min(bst, b['low'])
            if not be and bst <= entry - sl_d: be = True; cs = entry
            if be:
                ns = bst + tr
                if ns < cs: cs = ns
    lp = df.iloc[min(ep+max_bars, len(df)-1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def run_lc(key, tag, min_move, risk, df_h1, df_m1, date_range):
    cost = BASE_COST.get(key, 0.07) * 1.5
    h1_trades, m1_trades = [], []

    for date in sorted(set(df_h1.index.normalize().date)):
        if date not in date_range: continue
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue

        ob = df_h1[df_h1.index == day + pd.Timedelta(hours=7)]
        cb = df_h1[df_h1.index == day + pd.Timedelta(hours=15)]
        if len(ob) == 0 or len(cb) == 0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue

        sess = df_h1[(df_h1.index >= day + pd.Timedelta(hours=7)) &
                     (df_h1.index <= day + pd.Timedelta(hours=16))]
        if len(sess) == 0: continue
        dh = sess['high'].max(); dl = sess['low'].min()
        buf = (dh - dl) * 0.03

        p_h1 = ipos(df_h1, day + pd.Timedelta(hours=16))
        if p_h1 < 0: continue
        entry = df_h1.iloc[p_h1]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue

        entry_ts = day + pd.Timedelta(hours=16)

        # H1 sim
        r_h1 = sim(df_h1, p_h1, d, entry, sl, TRAIL, max_bars=80)
        h1_trades.append({'tag':tag, 'r': r_h1 - cost})

        # M1 sim — same entry, same SL, same direction, just finer bars
        if df_m1 is not None:
            p_m1 = df_m1.index.searchsorted(entry_ts)
            if p_m1 < len(df_m1):
                r_m1 = sim(df_m1, p_m1, d, entry, sl, TRAIL, max_bars=4800)
                m1_trades.append({'tag':tag, 'r': r_m1 - cost})

    return h1_trades, m1_trades

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, df_h1, df_m1, date_range, skip_dow=frozenset()):
    cost = BASE_COST.get(key, 0.07) * 1.5
    h1_trades, m1_trades = [], []

    for date in sorted(set(df_h1.index.normalize().date)):
        if date not in date_range: continue
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue

        rb = df_h1[df_h1.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue

        edf = df_h1[(df_h1.index >= day + pd.Timedelta(hours=es)) &
                    (df_h1.index <  day + pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]
            if b['high'] > rhi: d, entry, sl = 1,  rhi, rlo
            elif b['low'] < rlo: d, entry, sl = -1, rlo, rhi
            else: continue

            p_h1 = ipos(df_h1, edf.index[j])
            if p_h1 < 0: continue
            entry_ts = edf.index[j]

            r_h1 = sim(df_h1, p_h1, d, entry, sl, TRAIL, max_bars=80)
            h1_trades.append({'tag':tag, 'r': r_h1 - cost})

            if df_m1 is not None:
                p_m1 = df_m1.index.searchsorted(entry_ts)
                if p_m1 < len(df_m1):
                    r_m1 = sim(df_m1, p_m1, d, entry, sl, TRAIL, max_bars=4800)
                    m1_trades.append({'tag':tag, 'r': r_m1 - cost})
            break

    return h1_trades, m1_trades

def stats(trades, label):
    if not trades: return None
    r = np.array([t['r'] for t in trades])
    wins = r[r > 0]; losses = r[r <= 0]
    wr = len(wins)/len(r)
    pf = wins.sum()/abs(losses.sum()) if len(losses) and losses.sum()!=0 else float('inf')
    return {'label':label,'n':len(r),'wr':wr,'pf':pf,
            'avg_w':wins.mean() if len(wins) else 0,
            'avg_l':losses.mean() if len(losses) else 0}

# ── Load data ──────────────────────────────────────────────────────────────────
print("Loading data...\n")
h1 = {k: load(v) for k,v in CSVSYMS_H1.items()}
m1 = {k: load(v) for k,v in CSVSYMS_M1.items()}

# Find overlapping date range (M1 data period)
m1_dates = set()
for k, df in m1.items():
    if df is not None:
        m1_dates |= set(df.index.normalize().date)

if not m1_dates:
    print("No M1 data found. Upload M1 CSV files to this folder and retry.")
    exit(1)

date_range = m1_dates
d_min = min(date_range); d_max = max(date_range)
print(f"M1 data covers: {d_min} to {d_max}  ({len(date_range)} calendar days)\n")

# ── Run strategies ─────────────────────────────────────────────────────────────
print("Running H1 vs M1 comparison...\n")

all_h1, all_m1 = [], []

def run_pair(fn, *args):
    h, m = fn(*args)
    all_h1.extend(h); all_m1.extend(m)
    return h, m

strategies = [
    ('DAX_ORB', lambda: run_orb('DAX','DAX_ORB',8,10,12,20,200,0.0075,h1['DAX'],m1['DAX'],date_range)),
    ('NAS_ORB', lambda: run_orb('NAS100','NAS_ORB',14,16,18,30,1000,0.0075,h1['NAS100'],m1['NAS100'],date_range,frozenset({0,2,4}))),
    ('SP5_ORB', lambda: run_orb('SP500','SP5_ORB',14,16,19,3,150,0.004,h1['SP500'],m1['SP500'],date_range,frozenset({0}))),
    ('LC_EUR',  lambda: run_lc('EURUSD','LC_EUR',0.001,0.004,h1['EURUSD'],m1['EURUSD'],date_range)),
    ('LC_GBP',  lambda: run_lc('GBPUSD','LC_GBP',0.0025,0.004,h1['GBPUSD'],m1['GBPUSD'],date_range)),
    ('LC_DAX',  lambda: run_lc('DAX','LC_DAX',50.0,0.0075,h1['DAX'],m1['DAX'],date_range)),
    ('LC_UK',   lambda: run_lc('UK100','LC_UK',30.0,0.0075,h1['UK100'],m1['UK100'],date_range)),
    ('LC_GOLD', lambda: run_lc('GOLD','LC_GOLD',4.0,0.004,h1['GOLD'],m1['GOLD'],date_range)),
]

results = []
for name, fn in strategies:
    h, m = fn()
    all_h1.extend(h); all_m1.extend(m)
    sh = stats(h, 'H1')
    sm = stats(m, 'M1')
    results.append((name, sh, sm))
    if sh:
        print(f"  {name:>10}  H1: {sh['n']:>3} trades  WR {sh['wr']*100:>4.1f}%  PF {sh['pf']:>4.2f}  "
              f"AvgW {sh['avg_w']:>5.2f}R  AvgL {sh['avg_l']:>6.2f}R")
    if sm:
        print(f"  {'':>10}  M1: {sm['n']:>3} trades  WR {sm['wr']*100:>4.1f}%  PF {sm['pf']:>4.2f}  "
              f"AvgW {sm['avg_w']:>5.2f}R  AvgL {sm['avg_l']:>6.2f}R")
    print()

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n{'═'*70}")
print(f"  SYSTEM SUMMARY  —  H1 vs M1  (Trail_R={TRAIL})\n")
print(f"  {'':12}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'Avg Win':>8}  {'Avg Loss':>9}")
print(f"  {'─'*12}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*9}")

for label, trades in [('H1 sim', all_h1), ('M1 sim', all_m1)]:
    if not trades: continue
    s = stats(trades, label)
    print(f"  {label:12}  {s['n']:>7}  {s['wr']*100:>6.1f}%  {s['pf']:>6.2f}  "
          f"{s['avg_w']:>7.2f}R  {s['avg_l']:>8.2f}R")

print(f"\n  {'─'*68}")
sh_sys = stats(all_h1, 'H1')
sm_sys = stats(all_m1, 'M1')
if sh_sys and sm_sys:
    wr_diff   = (sm_sys['wr']   - sh_sys['wr'])   * 100
    avgw_diff =  sm_sys['avg_w'] - sh_sys['avg_w']
    pf_diff   =  sm_sys['pf']   - sh_sys['pf']
    print(f"\n  WR difference (M1 vs H1)      : {wr_diff:+.1f}pp")
    print(f"  Avg win difference (M1 vs H1) : {avgw_diff:+.2f}R")
    print(f"  PF difference (M1 vs H1)      : {pf_diff:+.2f}")
    print()
    if abs(wr_diff) < 3 and abs(avgw_diff) < 0.3:
        print("  VERDICT: H1 and M1 results are CONSISTENT.")
        print("           Trail_R=0.05 backtest is reliable.")
    elif avgw_diff < -0.4:
        print("  VERDICT: M1 avg win is significantly LOWER than H1.")
        print("           Trail_R=0.05 is being overstated by H1 simulation.")
        print("           Consider widening the trail.")
    else:
        print("  VERDICT: Some difference — review per-strategy numbers above.")

print(f"{'═'*70}")
