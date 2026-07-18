"""
backtest_m1_trail_sweep.py  -  Find optimal Trail_R using M1 data
=================================================================
Sweeps Trail_R from tight (0.05) to wide using M1 CSVs.
Signals (entry/SL/direction) are detected on H1, then simulated on M1.
Same engine as backtest_m1_vs_h1.py.

Run: python backtest_m1_trail_sweep.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

CSVSYMS_H1 = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}
CSVSYMS_M1 = {
    'EURUSD': 'EURUSD_M1.csv',     'GBPUSD': 'GBPUSD_M1.csv',
    'DAX':    'GER40.cash_M1.csv', 'NAS100': 'US100.cash_M1.csv',
    'SP500':  'US500.cash_M1.csv', 'UK100':  'UK100.cash_M1.csv',
    'GOLD':   'XAUUSD_M1.csv',
}
BASE_COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08
}
TRAIL_VALUES = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.0, 1.5, 2.0, 5.0]

_cache = {}
def load(fn):
    if fn in _cache: return _cache[fn]
    if not os.path.exists(fn): _cache[fn] = None; return None
    df = pd.read_csv(fn)
    if 'time' not in df.columns:
        df = pd.read_csv(fn, skiprows=1)
    if 'time' not in df.columns: _cache[fn] = None; return None
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
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    tr = sl_d * trail; cs = sl; bst = entry; be = False
    for _, b in df.iloc[ep+1: ep+1+max_bars].iterrows():
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

def signals_lc(df_h1, df_m1, min_move, cost, date_range):
    if df_h1 is None: return []
    out = []
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
        d = -1 if move > 0 else 1
        sl = (dh + buf) if d == -1 else (dl - buf)
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        entry_ts = day + pd.Timedelta(hours=16)
        p_m1 = -1
        if df_m1 is not None:
            p_m1 = int(df_m1.index.searchsorted(entry_ts))
            if p_m1 >= len(df_m1): p_m1 = -1
        out.append((df_h1, df_m1, p_h1, p_m1, d, entry, sl, cost))
    return out

def signals_orb(df_h1, df_m1, ref_h, es, ee, rmin, rmax, cost, date_range, skip_dow=frozenset()):
    if df_h1 is None: return []
    out = []
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
            if b['high'] > rhi: d, entry, sl = 1, rhi, rlo
            elif b['low'] < rlo: d, entry, sl = -1, rlo, rhi
            else: continue
            p_h1 = ipos(df_h1, edf.index[j])
            if p_h1 < 0: continue
            entry_ts = edf.index[j]
            p_m1 = -1
            if df_m1 is not None:
                p_m1 = int(df_m1.index.searchsorted(entry_ts))
                if p_m1 >= len(df_m1): p_m1 = -1
            out.append((df_h1, df_m1, p_h1, p_m1, d, entry, sl, cost))
            break
    return out

def score_signals(signals, trail):
    h1_r, m1_r = [], []
    for df_h1, df_m1, p_h1, p_m1, d, entry, sl, cost in signals:
        if p_h1 >= 0 and df_h1 is not None:
            h1_r.append(sim(df_h1, p_h1, d, entry, sl, trail, 80) - cost)
        if p_m1 >= 0 and df_m1 is not None:
            m1_r.append(sim(df_m1, p_m1, d, entry, sl, trail, 4800) - cost)
    return np.array(h1_r), np.array(m1_r)

def pf(r): return r[r>0].sum()/abs(r[r<=0].sum()) if len(r[r<=0]) and r[r<=0].sum()!=0 else float('inf')
def wr(r): return len(r[r>0])/len(r)*100 if len(r) else 0
def aw(r): return r[r>0].mean() if len(r[r>0]) else 0

# ── Load ───────────────────────────────────────────────────────────────────────
print("Loading data...")
h1 = {k: load(v) for k,v in CSVSYMS_H1.items()}
m1 = {k: load(v) for k,v in CSVSYMS_M1.items()}

m1_dates = set()
for df in m1.values():
    if df is not None: m1_dates |= set(df.index.normalize().date)
if not m1_dates: print("No M1 data found."); exit(1)
print(f"M1 period: {min(m1_dates)} to {max(m1_dates)}\n")

# ── Collect signals once — same entry/SL used for all trail values ─────────────
print("Collecting signals...")
c = BASE_COST
all_signals = (
    signals_orb(h1['DAX'],   m1['DAX'],   8, 10,12, 20, 200, c['DAX']*1.5,    m1_dates) +
    signals_orb(h1['NAS100'],m1['NAS100'],14,16,18, 30,1000, c['NAS100']*1.5, m1_dates, frozenset({0,2,4})) +
    signals_orb(h1['SP500'], m1['SP500'], 14,16,19,  3, 150, c['SP500']*1.5,  m1_dates, frozenset({0})) +
    signals_lc( h1['EURUSD'],m1['EURUSD'],0.001,     c['EURUSD']*1.5, m1_dates) +
    signals_lc( h1['GBPUSD'],m1['GBPUSD'],0.0025,    c['GBPUSD']*1.5, m1_dates) +
    signals_lc( h1['DAX'],   m1['DAX'],   50.0,      c['DAX']*1.5,    m1_dates) +
    signals_lc( h1['UK100'], m1['UK100'], 30.0,      c['UK100']*1.5,  m1_dates) +
    signals_lc( h1['GOLD'],  m1['GOLD'],  4.0,       c['GOLD']*1.5,   m1_dates)
)
print(f"Total signals: {len(all_signals)}\n")

# ── Sweep ──────────────────────────────────────────────────────────────────────
print(f"{'═'*76}")
print(f"  TRAIL_R SWEEP — M1 simulation (ground truth)\n")
print(f"  {'Trail':>7}  {'H1 PF':>7}  {'H1 WR':>6}  {'H1 AvgW':>7}  ||  {'M1 PF':>7}  {'M1 WR':>6}  {'M1 AvgW':>7}")
print(f"  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*7}  {'──':>4}  {'─'*7}  {'─'*6}  {'─'*7}")

best_m1_pf = 0; best_trail = 0.05

for tr in TRAIL_VALUES:
    h, m = score_signals(all_signals, tr)
    h_pf = pf(h); m_pf = pf(m)
    marker = " ◄ CURRENT" if tr == 0.05 else ""
    if m_pf > best_m1_pf and len(m) >= 50:
        best_m1_pf = m_pf; best_trail = tr
    print(f"  {tr:>7.2f}  {h_pf:>7.2f}  {wr(h):>5.1f}%  {aw(h):>6.2f}R  ||  "
          f"{m_pf:>7.2f}  {wr(m):>5.1f}%  {aw(m):>6.2f}R{marker}")

print(f"\n{'═'*76}")
print(f"  BEST Trail_R on M1 : {best_trail}  (PF {best_m1_pf:.2f})")
print(f"  Current Trail_R    : 0.05")
print(f"\n  To fix the EA: change Trail_R from 0.05 to {best_trail}")
print(f"  Update the input on your VPS MT5 and restart the EA.")
print(f"{'═'*76}")
