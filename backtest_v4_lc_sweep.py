"""
backtest_v4_lc_sweep.py  -  Parameter sweep for each LC and ORB strategy
=========================================================================
Sweeps the key parameter for each strategy to find the optimal input:
  LC strategies  : min_move (minimum morning session move to trigger entry)
  ORB strategies : rmin (minimum reference bar range)

For each parameter value shows: trades, WR, PF, net P&L.
Highlights current V4 value and optimal value.

Run: python backtest_v4_lc_sweep.py
"""
import numpy as np
import pandas as pd
import os

ACCOUNT  = 70_000
COST_PCT = 0.07

CSVSYMS = {
    'DAX':    'GER40_cash_H1.csv',
    'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv',
    'EURUSD': 'EURUSD_H1.csv',
    'GBPUSD': 'GBPUSD_H1.csv',
    'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

def load_h1(key):
    fn = CSVSYMS[key]
    if not os.path.exists(fn): return None
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'])
    return df.sort_values('time').drop_duplicates('time').reset_index(drop=True)

def get_bar(df, ts):
    idx = df['time'].searchsorted(ts)
    if idx < len(df) and df.iloc[idx]['time'] == ts:
        return df.iloc[idx]
    return None

def get_dates(df):
    return pd.to_datetime(df['time'].dt.normalize().unique())

def sim_trade(df, ep, direction, entry, sl, trail=0.05, max_bars=80):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    tr = sl_d * trail; cs = sl; be = False
    for i in range(ep+1, min(ep+max_bars, len(df))):
        b = df.iloc[i]
        mv = (b['close'] - entry) * direction
        if not be and mv >= sl_d: cs = entry; be = True
        if be and mv >= sl_d + tr:
            new_cs = entry + (mv - tr) * direction
            cs = max(cs, new_cs) if direction == 1 else min(cs, new_cs)
        if direction == 1 and b['low']  < cs: return (cs - entry) / sl_d
        if direction == -1 and b['high'] > cs: return (entry - cs) / sl_d
    lp = df.iloc[min(ep+max_bars, len(df)-1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def backtest_lc(df, min_move, risk, trail=0.05):
    trades = []
    for date in get_dates(df):
        if date.weekday() == 4: continue
        b07 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 7))
        b15 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 15))
        if b07 is None or b15 is None: continue
        move = b15['close'] - b07['open']
        if abs(move) < min_move: continue
        sess = [get_bar(df, pd.Timestamp(date.year, date.month, date.day, h))
                for h in range(7, 16)]
        sess = [b for b in sess if b is not None]
        if len(sess) < 2: continue
        d_hi = max(b['high'] for b in sess)
        d_lo = min(b['low']  for b in sess)
        buf  = (d_hi - d_lo) * 0.03
        d    = -1 if move > 0 else 1
        entry = b15['close']
        sl    = d_hi + buf if d == -1 else d_lo - buf
        sl_d  = abs(entry - sl)
        if sl_d <= 0: continue
        ep = int(df['time'].searchsorted(pd.Timestamp(date.year, date.month, date.day, 15)))
        r = sim_trade(df, ep, d, entry, sl, trail)
        r_net = r - COST_PCT
        trades.append(r_net * risk * ACCOUNT)
    return trades

def backtest_orb(df, rmin, rmax, ref_h, win_s, win_e, risk, skip_dow=set(), trail=0.05):
    trades = []
    for date in get_dates(df):
        if date.weekday() in skip_dow: continue
        ref = get_bar(df, pd.Timestamp(date.year, date.month, date.day, ref_h))
        if ref is None: continue
        rng = ref['high'] - ref['low']
        if not (rmin <= rng <= rmax): continue
        for h in range(win_s, win_e):
            ts = pd.Timestamp(date.year, date.month, date.day, h)
            b = get_bar(df, ts)
            if b is None: continue
            if b['close'] > ref['high']:   d, entry, sl = 1,  b['close'], ref['low']
            elif b['close'] < ref['low']:  d, entry, sl = -1, b['close'], ref['high']
            else: continue
            sl_d = abs(entry - sl)
            if sl_d <= 0: continue
            ep = int(df['time'].searchsorted(ts))
            r = sim_trade(df, ep, d, entry, sl, trail)
            r_net = r - COST_PCT
            trades.append(r_net * risk * ACCOUNT)
            break
    return trades

def print_sweep(name, current_val, param_vals, results):
    print(f"\n{'─'*65}")
    print(f"  {name}  (current = {current_val})\n")
    print(f"  {'Value':>10}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'Net P&L':>10}  {'':>4}")
    print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*10}")
    best_pf = max((r['pf'] for r in results if r['n'] >= 20), default=0)
    for val, r in zip(param_vals, results):
        if r['n'] < 5:
            print(f"  {val:>10.4f}  {r['n']:>7}  {'—':>7}  {'—':>6}  {'—':>10}  (too few trades)")
            continue
        marker = " ◄ CURRENT" if val == current_val else \
                 " ◄ BEST PF" if r['pf'] == best_pf else ""
        print(f"  {val:>10.4f}  {r['n']:>7}  {r['wr']*100:>6.1f}%  {r['pf']:>6.2f}  "
              f"£{r['net']:>9,.0f}{marker}")

def sweep_results(pnls_list):
    out = []
    for pnls in pnls_list:
        if not pnls:
            out.append({'n': 0, 'wr': 0, 'pf': 0, 'net': 0})
            continue
        a = np.array(pnls)
        wins = a[a > 0]; losses = a[a <= 0]
        wr = len(wins) / len(a)
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
        out.append({'n': len(a), 'wr': wr, 'pf': pf, 'net': a.sum()})
    return out

print("Loading data...")
data = {k: load_h1(k) for k in CSVSYMS}
print("Running sweeps...\n")

# ══ LC STRATEGIES ══════════════════════════════════════════════════════════════
print("═"*65)
print("LC STRATEGY — MIN_MOVE SWEEP")
print("═"*65)

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
    df = data.get(key)
    if df is None: continue
    results = sweep_results([backtest_lc(df, v, risk) for v in vals])
    print_sweep(name, current, vals, results)

# ══ ORB STRATEGIES ═════════════════════════════════════════════════════════════
print(f"\n\n{'═'*65}")
print("ORB STRATEGY — RMIN SWEEP  (minimum ref-bar range)")
print("═"*65)

orb_configs = [
    ('DAX_ORB', 'DAX',    20,  [5,10,15,20,25,30,40,50,75,100],
     dict(rmax=200,  ref_h=8,  win_s=10, win_e=12, risk=0.0075, skip_dow=set())),
    ('NAS_ORB', 'NAS100', 30,  [10,20,30,40,50,75,100,150,200],
     dict(rmax=1000, ref_h=14, win_s=16, win_e=18, risk=0.0075, skip_dow={0,2,3,4})),
    ('SP5_ORB', 'SP500',  3,   [1,2,3,4,5,7,10,15,20],
     dict(rmax=150,  ref_h=14, win_s=16, win_e=19, risk=0.0040, skip_dow={0})),
]

for name, key, current, vals, kwargs in orb_configs:
    df = data.get(key)
    if df is None: continue
    results = sweep_results([
        backtest_orb(df, v, kwargs['rmax'], kwargs['ref_h'],
                     kwargs['win_s'], kwargs['win_e'], kwargs['risk'],
                     kwargs['skip_dow']) for v in vals
    ])
    print_sweep(name, current, vals, results)

print(f"\n{'═'*65}")
print("  Done. Look for parameters where PF peaks — those are the optimal values.")
print(f"{'═'*65}")
