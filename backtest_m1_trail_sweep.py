"""
backtest_m1_trail_sweep.py  -  Find optimal Trail_R using M1 data
=================================================================
Sweeps Trail_R from tight (0.05) to wide (no trail) using the M1
CSV files, which give an accurate picture of real trailing stop behavior.

The H1 backtest overstates avg win because it can't see intrabar wiggles
that knock out a tight trail. M1 is the ground truth.

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

def collect_signals_lc(key, min_move, df_h1, df_m1, date_range):
    """Return (h1_pos, m1_pos, direction, entry, sl, cost) for each valid LC day."""
    cost = BASE_COST.get(key, 0.07) * 1.5
    signals = []
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
        p_m1 = df_m1.index.searchsorted(entry_ts) if df_m1 is not None else -1
        if p_m1 >= len(df_m1 if df_m1 is not None else []): p_m1 = -1
        signals.append((p_h1, p_m1, d, entry, sl, cost))
    return signals

def collect_signals_orb(key, ref_h, es, ee, rmin, rmax, df_h1, df_m1, date_range, skip_dow=frozenset()):
    cost = BASE_COST.get(key, 0.07) * 1.5
    signals = []
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
            p_m1 = df_m1.index.searchsorted(entry_ts) if df_m1 is not None else -1
            if p_m1 >= len(df_m1 if df_m1 is not None else []): p_m1 = -1
            signals.append((p_h1, p_m1, d, entry, sl, cost))
            break
    return signals

def score(signals, df_h1, df_m1, trail):
    h1_r, m1_r = [], []
    for p_h1, p_m1, d, entry, sl, cost in signals:
        r = sim(df_h1, p_h1, d, entry, sl, trail, max_bars=80) - cost
        h1_r.append(r)
        if df_m1 is not None and p_m1 >= 0:
            r = sim(df_m1, p_m1, d, entry, sl, trail, max_bars=4800) - cost
            m1_r.append(r)
    return np.array(h1_r), np.array(m1_r)

def pf(r): return r[r>0].sum()/abs(r[r<=0].sum()) if len(r[r<=0]) and r[r<=0].sum()!=0 else float('inf')
def wr(r): return len(r[r>0])/len(r) if len(r) else 0
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

# ── Collect signals once (same for all trail values) ──────────────────────────
print("Collecting trade signals...")
all_signals = (
    collect_signals_orb('DAX','DAX_ORB',8,10,12,20,200,h1['DAX'],m1['DAX'],m1_dates) +
    collect_signals_orb('NAS100','NAS_ORB',14,16,18,30,1000,h1['NAS100'],m1['NAS100'],m1_dates,frozenset({0,2,4})) +
    collect_signals_orb('SP500','SP5_ORB',14,16,19,3,150,h1['SP500'],m1['SP500'],m1_dates,frozenset({0})) +
    collect_signals_lc('EURUSD',0.001,h1['EURUSD'],m1['EURUSD'],m1_dates) +
    collect_signals_lc('GBPUSD',0.0025,h1['GBPUSD'],m1['GBPUSD'],m1_dates) +
    collect_signals_lc('DAX',50.0,h1['DAX'],m1['DAX'],m1_dates) +
    collect_signals_lc('UK100',30.0,h1['UK100'],m1['UK100'],m1_dates) +
    collect_signals_lc('GOLD',4.0,h1['GOLD'],m1['GOLD'],m1_dates)
)

# Filter to signals that have both H1 and M1 positions
valid = [(p_h1, p_m1, d, entry, sl, cost) for p_h1, p_m1, d, entry, sl, cost in all_signals
         if p_h1 >= 0 and p_m1 >= 0]
print(f"Valid signals: {len(valid)}\n")

# ── Trail sweep ────────────────────────────────────────────────────────────────
TRAIL_VALUES = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.0, 1.5, 2.0, 5.0]

print(f"{'═'*78}")
print(f"  TRAIL_R SWEEP  —  M1 simulation (ground truth)\n")
print(f"  {'Trail_R':>8}  {'H1 PF':>7}  {'H1 WR':>7}  {'H1 AvgW':>8}  {'M1 PF':>7}  {'M1 WR':>7}  {'M1 AvgW':>8}  {'Gap':>6}")
print(f"  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*6}")

best_m1_pf = 0
best_trail = None

results = []
for tr in TRAIL_VALUES:
    h1_r, m1_r = score(valid, h1['DAX'], m1['DAX'], tr)  # placeholder — need all

    # Re-score with actual per-instrument dfs
    all_h1_r, all_m1_r = [], []
    for p_h1, p_m1, d, entry, sl, cost in valid:
        # We need the correct df for each signal — use a simplified approach
        # Score all signals against their stored positions
        pass

    # Actually just re-run score() on the full valid list with placeholder
    # The df argument doesn't matter since we pass p_h1/p_m1 directly
    # Let's run it properly by rebuilding per-instrument signal lists
    break  # placeholder

# Proper per-instrument sweep
strat_signals = {
    'DAX_ORB': collect_signals_orb('DAX','DAX_ORB',8,10,12,20,200,h1['DAX'],m1['DAX'],m1_dates),
    'NAS_ORB': collect_signals_orb('NAS100','NAS_ORB',14,16,18,30,1000,h1['NAS100'],m1['NAS100'],m1_dates,frozenset({0,2,4})),
    'SP5_ORB': collect_signals_orb('SP500','SP5_ORB',14,16,19,3,150,h1['SP500'],m1['SP500'],m1_dates,frozenset({0})),
    'LC_EUR':  collect_signals_lc('EURUSD',0.001,h1['EURUSD'],m1['EURUSD'],m1_dates),
    'LC_GBP':  collect_signals_lc('GBPUSD',0.0025,h1['GBPUSD'],m1['GBPUSD'],m1_dates),
    'LC_DAX':  collect_signals_lc('DAX',50.0,h1['DAX'],m1['DAX'],m1_dates),
    'LC_UK':   collect_signals_lc('UK100',30.0,h1['UK100'],m1['UK100'],m1_dates),
    'LC_GOLD': collect_signals_lc('GOLD',4.0,h1['GOLD'],m1['GOLD'],m1_dates),
}
strat_h1df = {
    'DAX_ORB': h1['DAX'], 'NAS_ORB': h1['NAS100'], 'SP5_ORB': h1['SP500'],
    'LC_EUR': h1['EURUSD'], 'LC_GBP': h1['GBPUSD'], 'LC_DAX': h1['DAX'],
    'LC_UK': h1['UK100'], 'LC_GOLD': h1['GOLD'],
}
strat_m1df = {
    'DAX_ORB': m1['DAX'], 'NAS_ORB': m1['NAS100'], 'SP5_ORB': m1['SP500'],
    'LC_EUR': m1['EURUSD'], 'LC_GBP': m1['GBPUSD'], 'LC_DAX': m1['DAX'],
    'LC_UK': m1['UK100'], 'LC_GOLD': m1['GOLD'],
}

print(f"  {'Trail_R':>8}  {'H1 PF':>7}  {'H1 WR':>7}  {'H1 AvgW':>8}  {'M1 PF':>7}  {'M1 WR':>7}  {'M1 AvgW':>8}  {'Gap':>6}")
print(f"  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*7}  {'─'*7}  {'─'*8}  {'─'*6}")

for tr in TRAIL_VALUES:
    all_h1_r, all_m1_r = [], []
    for sname, sigs in strat_signals.items():
        dfh = strat_h1df[sname]; dfm = strat_m1df[sname]
        for p_h1, p_m1, d, entry, sl, cost in sigs:
            if p_h1 >= 0 and dfh is not None:
                all_h1_r.append(sim(dfh, p_h1, d, entry, sl, tr, 80) - cost)
            if p_m1 >= 0 and dfm is not None:
                all_m1_r.append(sim(dfm, p_m1, d, entry, sl, tr, 4800) - cost)

    h = np.array(all_h1_r); m = np.array(all_m1_r)
    h_pf = pf(h); m_pf = pf(m)
    gap = m_pf - h_pf
    marker = " ◄ CURRENT" if tr == 0.05 else " ◄ BEST M1" if (m_pf > best_m1_pf and len(m) > 50) else ""
    if m_pf > best_m1_pf and len(m) > 50:
        best_m1_pf = m_pf; best_trail = tr
    print(f"  {tr:>8.2f}  {h_pf:>7.2f}  {wr(h)*100:>6.1f}%  {aw(h):>7.2f}R  "
          f"{m_pf:>7.2f}  {wr(m)*100:>6.1f}%  {aw(m):>7.2f}R  {gap:>+6.2f}{marker}")

print(f"\n{'═'*78}")
print(f"  Best Trail_R on M1: {best_trail}  (PF {best_m1_pf:.2f})")
print(f"  Current Trail_R   : 0.05  (PF shown above)")
print(f"\n  To update the EA: change Trail_R input from 0.05 to {best_trail}")
print(f"  Impact: all 8 strategies affected equally.")
print(f"{'═'*78}")
