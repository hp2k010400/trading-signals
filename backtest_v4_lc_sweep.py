"""
backtest_v4_lc_sweep.py  -  Parameter sweep for each LC and ORB strategy
=========================================================================
Uses the SAME simulation engine as backtest_v4_stress.py (BASELINE).
Sweeps:
  LC strategies  : min_move (minimum morning session move to trigger entry)
  ORB strategies : rmin (minimum reference bar range)

Run: python backtest_v4_lc_sweep.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ACCOUNT  = 70_000

CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

BASE_COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08
}

_cache = {}
def load_h1(key):
    if key in _cache: return _cache[key]
    fn = CSVSYMS.get(key)
    if not fn or not os.path.exists(fn): _cache[key] = None; return None
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    result = df.dropna() if len(df) > 200 else None
    _cache[key] = result; return result

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    return int(a) if a < len(df) and df.index[int(a)] == ts else -1

def sim(df, ep, direction, entry, sl, trail, max_bars=80):
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
    lp = df.iloc[min(ep + max_bars, len(df)-1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def backtest_lc(key, min_move, risk, trail=0.05):
    df = load_h1(key)
    if df is None: return []
    cost = BASE_COST.get(key, 0.07) * 1.5
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        ob = df[df.index == day + pd.Timedelta(hours=7)]
        cb = df[df.index == day + pd.Timedelta(hours=15)]
        if len(ob) == 0 or len(cb) == 0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue
        sess = df[(df.index >= day + pd.Timedelta(hours=7)) &
                  (df.index <= day + pd.Timedelta(hours=16))]
        if len(sess) == 0: continue
        dh = sess['high'].max(); dl = sess['low'].min()
        buf = (dh - dl) * 0.03
        p = ipos(df, day + pd.Timedelta(hours=16))
        if p < 0: continue
        entry = df.iloc[p]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        r = sim(df, p, d, entry, sl, trail)
        trades.append((r - cost) * risk * ACCOUNT)
    return trades

def backtest_orb(key, rmin, rmax, ref_h, es, ee, risk, skip_dow=frozenset(), trail=0.05):
    df = load_h1(key)
    if df is None: return []
    cost = BASE_COST.get(key, 0.07) * 1.5
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb = df[df.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue
        edf = df[(df.index >= day + pd.Timedelta(hours=es)) &
                 (df.index <  day + pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                r = sim(df, p, 1, rhi, rlo, trail)
                trades.append((r - cost) * risk * ACCOUNT); break
            if b['low'] < rlo:
                r = sim(df, p, -1, rlo, rhi, trail)
                trades.append((r - cost) * risk * ACCOUNT); break
    return trades

def sweep_stats(pnls_list):
    out = []
    for pnls in pnls_list:
        if not pnls:
            out.append({'n':0,'wr':0,'pf':0,'net':0}); continue
        a = np.array(pnls)
        wins = a[a > 0]; losses = a[a <= 0]
        wr = len(wins) / len(a)
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
        out.append({'n':len(a),'wr':wr,'pf':pf,'net':a.sum()})
    return out

def print_sweep(name, current_val, param_vals, results):
    print(f"\n{'─'*68}")
    print(f"  {name}  (current = {current_val})\n")
    print(f"  {'Value':>10}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'Net P&L':>10}  {'':>4}")
    print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*10}")
    best_pf = max((r['pf'] for r in results if r['n'] >= 20), default=0)
    for val, r in zip(param_vals, results):
        if r['n'] < 5:
            print(f"  {val:>10.4f}  {r['n']:>7}  {'—':>7}  {'—':>6}  {'—':>10}  (too few trades)")
            continue
        marker = " ◄ CURRENT" if val == current_val else \
                 " ◄ BEST PF" if abs(r['pf'] - best_pf) < 0.001 else ""
        print(f"  {val:>10.4f}  {r['n']:>7}  {r['wr']*100:>6.1f}%  {r['pf']:>6.2f}  "
              f"£{r['net']:>9,.0f}{marker}")

print("Loading data...")
data_keys = list(CSVSYMS.keys())
for k in data_keys: load_h1(k)  # pre-warm cache
print("Running sweeps...\n")

# ══ LC STRATEGIES ══════════════════════════════════════════════════════════════
print("═"*68)
print("LC STRATEGY — MIN_MOVE SWEEP")
print("═"*68)

lc_configs = [
    ('LC_EUR',  'EURUSD', 0.0010, 0.0040,
     [0.0005,0.0008,0.0010,0.0015,0.0020,0.0030,0.0040,0.0050,0.0060,0.0080,0.0100]),
    ('LC_GBP',  'GBPUSD', 0.0025, 0.0040,
     [0.0010,0.0015,0.0020,0.0025,0.0030,0.0040,0.0050,0.0060,0.0080,0.0100,0.0150]),
    ('LC_DAX',  'DAX',    50.0,   0.0075,
     [10,20,30,40,50,60,75,100,125,150,200]),
    ('LC_UK',   'UK100',  30.0,   0.0075,
     [10,15,20,25,30,40,50,60,80,100]),
    ('LC_GOLD', 'GOLD',   4.0,    0.0040,
     [1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,10.0,12.0]),
]

for name, key, current, risk, vals in lc_configs:
    results = sweep_stats([backtest_lc(key, v, risk) for v in vals])
    print_sweep(name, current, vals, results)

# ══ ORB STRATEGIES ═════════════════════════════════════════════════════════════
print(f"\n\n{'═'*68}")
print("ORB STRATEGY — RMIN SWEEP  (minimum ref-bar range)")
print("═"*68)

orb_configs = [
    ('DAX_ORB', 'DAX',    20,  [5,10,15,20,25,30,40,50,75,100],
     dict(rmax=200,  ref_h=8,  es=10, ee=12, risk=0.0075, skip_dow=frozenset())),
    ('NAS_ORB', 'NAS100', 30,  [10,20,30,40,50,75,100,150,200],
     dict(rmax=1000, ref_h=14, es=16, ee=18, risk=0.0075, skip_dow=frozenset({0,2,4}))),
    ('SP5_ORB', 'SP500',  3,   [1,2,3,4,5,7,10,15,20],
     dict(rmax=150,  ref_h=14, es=16, ee=19, risk=0.0040, skip_dow=frozenset({0}))),
]

for name, key, current, vals, kw in orb_configs:
    results = sweep_stats([
        backtest_orb(key, v, kw['rmax'], kw['ref_h'], kw['es'], kw['ee'],
                     kw['risk'], kw['skip_dow']) for v in vals
    ])
    print_sweep(name, current, vals, results)

print(f"\n{'═'*68}")
print("  Done.")
print(f"{'═'*68}")
