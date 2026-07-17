"""
backtest_v4_per_strategy.py  -  Per-strategy performance breakdown
==================================================================
Runs each of the 8 V4 strategies in complete isolation over the full
8.5-year dataset. Shows exactly which strategies are carrying the system
and which are dragging it down.

Metrics per strategy:
  Trades, Win Rate, Profit Factor, Avg Win R, Avg Loss R, RRR, Net P&L

Run: python backtest_v4_per_strategy.py
"""
import numpy as np
import pandas as pd
import os, sys

ACCOUNT   = 70_000
COST_PCT  = 0.07    # baseline spread/slip cost as fraction of SL

CSVSYMS = {
    'DAX':    'GER40_cash_H1.csv',
    'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv',
    'EURUSD': 'EURUSD_H1.csv',
    'GBPUSD': 'GBPUSD_H1.csv',
    'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

LC_MIN = {
    'EURUSD': 0.0010, 'GBPUSD': 0.0025,
    'DAX': 50.0, 'UK100': 30.0, 'GOLD': 4.0,
}

STRATEGIES = {
    'DAX_ORB': dict(key='DAX',    risk=0.0075, type='orb',
                    ref_h=8, win_s=10, win_e=12, rmin=20,  rmax=200,  trail=0.05, skip_dow=set()),
    'NAS_ORB': dict(key='NAS100', risk=0.0075, type='orb',
                    ref_h=14,win_s=16, win_e=18, rmin=30,  rmax=1000, trail=0.05, skip_dow={0,2,3,4}),
    'SP5_ORB': dict(key='SP500',  risk=0.0040, type='orb',
                    ref_h=14,win_s=16, win_e=19, rmin=3,   rmax=150,  trail=0.05, skip_dow={0}),
    'LC_EUR':  dict(key='EURUSD', risk=0.0040, type='lc',  min_move=LC_MIN['EURUSD'], trail=0.05),
    'LC_GBP':  dict(key='GBPUSD', risk=0.0040, type='lc',  min_move=LC_MIN['GBPUSD'], trail=0.05),
    'LC_DAX':  dict(key='DAX',    risk=0.0075, type='lc',  min_move=LC_MIN['DAX'],    trail=0.05),
    'LC_UK':   dict(key='UK100',  risk=0.0075, type='lc',  min_move=LC_MIN['UK100'],  trail=0.05),
    'LC_GOLD': dict(key='GOLD',   risk=0.0040, type='lc',  min_move=LC_MIN['GOLD'],   trail=0.05),
}

def load_h1(key):
    fn = CSVSYMS[key]
    if not os.path.exists(fn):
        print(f"  Missing: {fn}")
        return None
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.sort_values('time').drop_duplicates('time').reset_index(drop=True)
    return df

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

def run_orb(cfg, df):
    trades = []
    for date in get_dates(df):
        if date.weekday() in cfg['skip_dow']: continue
        ref = get_bar(df, pd.Timestamp(date.year, date.month, date.day, cfg['ref_h']))
        if ref is None: continue
        rng = ref['high'] - ref['low']
        if not (cfg['rmin'] <= rng <= cfg['rmax']): continue
        for h in range(cfg['win_s'], cfg['win_e']):
            ts = pd.Timestamp(date.year, date.month, date.day, h)
            b = get_bar(df, ts)
            if b is None: continue
            if b['close'] > ref['high']:   d, entry, sl = 1,  b['close'], ref['low']
            elif b['close'] < ref['low']:  d, entry, sl = -1, b['close'], ref['high']
            else: continue
            sl_d = abs(entry - sl)
            if sl_d <= 0: continue
            ep = int(df['time'].searchsorted(ts))
            r = sim_trade(df, ep, d, entry, sl, cfg['trail'])
            r_net = r - COST_PCT
            trades.append({'date': date, 'r': r_net, 'win': r_net > 0,
                           'pnl': r_net * cfg['risk'] * ACCOUNT})
            break
    return trades

def run_lc(cfg, df):
    trades = []
    for date in get_dates(df):
        if date.weekday() == 4: continue
        b07 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 7))
        b15 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 15))
        if b07 is None or b15 is None: continue
        move = b15['close'] - b07['open']
        if abs(move) < cfg['min_move']: continue
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
        r = sim_trade(df, ep, d, entry, sl, cfg['trail'])
        r_net = r - COST_PCT
        trades.append({'date': date, 'r': r_net, 'win': r_net > 0,
                       'pnl': r_net * cfg['risk'] * ACCOUNT})
    return trades

def stats(trades, name):
    if not trades:
        return {'name': name, 'n': 0}
    r    = np.array([t['r']   for t in trades])
    wins = r[r > 0]; losses = r[r <= 0]
    wr   = len(wins) / len(r)
    pf   = wins.sum() / abs(losses.sum()) if len(losses) else float('inf')
    pnl  = sum(t['pnl'] for t in trades)
    return {
        'name':   name,
        'n':      len(r),
        'wr':     wr,
        'pf':     pf,
        'avg_w':  wins.mean()   if len(wins)   else 0,
        'avg_l':  losses.mean() if len(losses) else 0,
        'rrr':    wins.mean() / abs(losses.mean()) if len(losses) and len(wins) else 0,
        'net':    pnl,
        'trades': trades,
    }

# ── Run all strategies ─────────────────────────────────────────────────────────
print("Loading data and running per-strategy backtest...\n")
data = {}
for key in CSVSYMS:
    data[key] = load_h1(key)

all_stats = []
for name, cfg in STRATEGIES.items():
    df = data.get(cfg['key'])
    if df is None:
        print(f"  {name}: skipped (no data)")
        continue
    trades = run_orb(cfg, df) if cfg['type'] == 'orb' else run_lc(cfg, df)
    s = stats(trades, name)
    all_stats.append(s)
    print(f"  {name}: {s['n']} trades  WR={s['wr']*100:.1f}%  PF={s['pf']:.2f}  Net=£{s['net']:,.0f}")

# ── Print summary table ────────────────────────────────────────────────────────
print(f"\n{'═'*80}")
print(f"PER-STRATEGY BREAKDOWN  (8.5-year backtest, baseline scenario)\n")
print(f"  {'Strategy':>10}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'AvgWinR':>8}  "
      f"{'AvgLosR':>8}  {'RRR':>6}  {'Net P&L':>10}  {'Status'}")
print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*10}  {'─'*10}")

total_net = 0
for s in all_stats:
    if s['n'] == 0:
        print(f"  {s['name']:>10}  NO DATA")
        continue
    status = '✓ GOOD' if s['pf'] >= 1.5 and s['wr'] >= 0.45 else \
             '~ OK'   if s['pf'] >= 1.2 else '✗ WEAK'
    print(f"  {s['name']:>10}  {s['n']:>7}  {s['wr']*100:>6.1f}%  {s['pf']:>6.2f}  "
          f"{s['avg_w']:>8.2f}R  {s['avg_l']:>8.2f}R  {s['rrr']:>6.2f}  "
          f"£{s['net']:>9,.0f}  {status}")
    total_net += s['net']

print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*10}")
print(f"  {'TOTAL':>10}  {'':>7}  {'':>7}  {'':>6}  {'':>8}  {'':>8}  {'':>6}  £{total_net:>9,.0f}")
print(f"{'═'*80}")

# ── Year-by-year for weakest strategy ─────────────────────────────────────────
weakest = min([s for s in all_stats if s['n'] > 0], key=lambda s: s['pf'])
print(f"\nYEAR-BY-YEAR: {weakest['name']} (weakest strategy)\n")
by_year = {}
for t in weakest['trades']:
    y = t['date'].year
    by_year.setdefault(y, []).append(t)
print(f"  {'Year':>6}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'Net P&L':>10}")
print(f"  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*10}")
for y in sorted(by_year):
    t_r = np.array([t['r'] for t in by_year[y]])
    wins = t_r[t_r > 0]; losses = t_r[t_r <= 0]
    wr = len(wins) / len(t_r)
    pf = wins.sum() / abs(losses.sum()) if len(losses) else float('inf')
    net = sum(t['pnl'] for t in by_year[y])
    print(f"  {y:>6}  {len(t_r):>7}  {wr*100:>6.1f}%  {pf:>6.2f}  £{net:>9,.0f}")

# ── Also show best strategy year-by-year ──────────────────────────────────────
best = max([s for s in all_stats if s['n'] > 0], key=lambda s: s['pf'])
print(f"\nYEAR-BY-YEAR: {best['name']} (best strategy)\n")
by_year = {}
for t in best['trades']:
    y = t['date'].year
    by_year.setdefault(y, []).append(t)
print(f"  {'Year':>6}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'Net P&L':>10}")
print(f"  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*10}")
for y in sorted(by_year):
    t_r = np.array([t['r'] for t in by_year[y]])
    wins = t_r[t_r > 0]; losses = t_r[t_r <= 0]
    wr = len(wins) / len(t_r)
    pf = wins.sum() / abs(losses.sum()) if len(losses) else float('inf')
    net = sum(t['pnl'] for t in by_year[y])
    print(f"  {y:>6}  {len(t_r):>7}  {wr*100:>6.1f}%  {pf:>6.2f}  £{net:>9,.0f}")
