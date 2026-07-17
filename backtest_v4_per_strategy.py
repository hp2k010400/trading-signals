"""
backtest_v4_per_strategy.py  -  Per-strategy performance breakdown
==================================================================
Uses the SAME simulation engine as backtest_v4_stress.py (BASELINE):
  - ORB enters at the breakout level (not bar close)
  - Trail moves off intrabar HIGH/LOW (not close)

Run: python backtest_v4_per_strategy.py
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

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, trail, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None: return []
    trades = []
    cost = BASE_COST.get(key, 0.07) * 1.5
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
                entry = rhi; sl_d = abs(entry - rlo)
                r = sim(df, p, 1, entry, rlo, trail)
                trades.append({'tag':tag,'r':r-cost,'pnl':(r-cost)*risk*ACCOUNT}); break
            if b['low'] < rlo:
                entry = rlo; sl_d = abs(rhi - entry)
                r = sim(df, p, -1, entry, rhi, trail)
                trades.append({'tag':tag,'r':r-cost,'pnl':(r-cost)*risk*ACCOUNT}); break
    return trades

def run_lc(key, tag, min_move, risk, trail):
    df = load_h1(key)
    if df is None: return []
    trades = []
    cost = BASE_COST.get(key, 0.07) * 1.5
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
        sl_d = abs(entry - sl)
        if sl_d <= 0: continue
        r = sim(df, p, d, entry, sl, trail)
        trades.append({'tag':tag,'r':r-cost,'pnl':(r-cost)*risk*ACCOUNT})
    return trades

def per_strategy_stats(all_trades):
    tags = ['DAX_ORB','NAS_ORB','SP5_ORB','LC_EUR','LC_GBP','LC_DAX','LC_UK','LC_GOLD']
    results = []
    for tag in tags:
        t = [x for x in all_trades if x['tag'] == tag]
        if not t:
            results.append({'tag':tag,'n':0}); continue
        r = np.array([x['r'] for x in t])
        pnl = np.array([x['pnl'] for x in t])
        wins = r[r > 0]; losses = r[r <= 0]
        wr  = len(wins) / len(r)
        pf  = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')
        results.append({
            'tag':    tag,
            'n':      len(r),
            'wr':     wr,
            'pf':     pf,
            'avg_w':  wins.mean()   if len(wins)   else 0,
            'avg_l':  losses.mean() if len(losses) else 0,
            'rrr':    wins.mean() / abs(losses.mean()) if len(losses) and len(wins) else 0,
            'net':    pnl.sum(),
        })
    return results

# ── Run ─────────────────────────────────────────────────────────────────────────
print("Loading data and running per-strategy backtest (BASELINE scenario)...\n")

all_trades = (
    run_orb('DAX',   'DAX_ORB', 8,  10,12,  20, 200, 0.0075, 0.05) +
    run_orb('NAS100','NAS_ORB', 14, 16,18,  30,1000, 0.0075, 0.05, frozenset({0,2,4})) +
    run_orb('SP500', 'SP5_ORB', 14, 16,19,   3, 150, 0.0040, 0.05, frozenset({0})) +
    run_lc('EURUSD', 'LC_EUR',  0.001,  0.0040, 0.05) +
    run_lc('GBPUSD', 'LC_GBP',  0.0025, 0.0040, 0.05) +
    run_lc('DAX',    'LC_DAX',  50.0,   0.0075, 0.05) +
    run_lc('UK100',  'LC_UK',   30.0,   0.0075, 0.05) +
    run_lc('GOLD',   'LC_GOLD', 4.0,    0.0040, 0.05)
)

print(f"Total trades: {len(all_trades)}\n")

# ── Summary table ───────────────────────────────────────────────────────────────
stats = per_strategy_stats(all_trades)

print(f"{'═'*85}")
print(f"PER-STRATEGY BREAKDOWN  (BASELINE — same engine as stress test)\n")
print(f"  {'Strategy':>10}  {'Trades':>7}  {'WR':>7}  {'PF':>6}  {'AvgWinR':>8}  "
      f"{'AvgLosR':>8}  {'RRR':>6}  {'Net P&L':>10}  {'Status'}")
print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*10}  {'─'*10}")

total_net = 0
for s in stats:
    if s['n'] == 0:
        print(f"  {s['tag']:>10}  NO DATA"); continue
    status = '✓ GOOD' if s['pf'] >= 1.5 and s['wr'] >= 0.45 else \
             '~ OK'   if s['pf'] >= 1.2  else '✗ WEAK'
    print(f"  {s['tag']:>10}  {s['n']:>7}  {s['wr']*100:>6.1f}%  {s['pf']:>6.2f}  "
          f"{s['avg_w']:>8.2f}R  {s['avg_l']:>8.2f}R  {s['rrr']:>6.2f}  "
          f"£{s['net']:>9,.0f}  {status}")
    total_net += s['net']

print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*10}")

# System-level combined stats
r_all = np.array([t['r'] for t in all_trades])
wins_all = r_all[r_all > 0]; losses_all = r_all[r_all <= 0]
sys_wr = len(wins_all)/len(r_all)*100
sys_pf = wins_all.sum()/abs(losses_all.sum()) if len(losses_all) else 0
print(f"  {'SYSTEM':>10}  {len(r_all):>7}  {sys_wr:>6.1f}%  {sys_pf:>6.2f}  "
      f"{'':>8}  {'':>8}  {'':>6}  £{total_net:>9,.0f}")
print(f"{'═'*85}")

# ── Year-by-year for weakest and best LC ────────────────────────────────────────
def year_breakdown(tag, all_trades):
    t = [x for x in all_trades if x['tag'] == tag]
    if not t: return
    print(f"\nYEAR-BY-YEAR: {tag}\n")
    by_year = {}
    for x in t:
        # date isn't stored — use pnl sign as proxy, skip per-year for now
        pass
    print(f"  (year breakdown requires date tracking — run sweep for detail)")

# Show LC strategies sorted by PF
lc_stats = [s for s in stats if s['tag'].startswith('LC') and s['n'] > 0]
lc_stats.sort(key=lambda s: s['pf'], reverse=True)
print(f"\nLC STRATEGIES RANKED BY PF:")
for s in lc_stats:
    print(f"  {s['tag']:>10}  PF {s['pf']:.2f}  WR {s['wr']*100:.1f}%  "
          f"AvgW {s['avg_w']:.2f}R  RRR {s['rrr']:.2f}  Net £{s['net']:,.0f}")

orb_stats = [s for s in stats if s['tag'].endswith('ORB') and s['n'] > 0]
print(f"\nORB STRATEGIES RANKED BY PF:")
for s in sorted(orb_stats, key=lambda s: s['pf'], reverse=True):
    print(f"  {s['tag']:>10}  PF {s['pf']:.2f}  WR {s['wr']*100:.1f}%  "
          f"AvgW {s['avg_w']:.2f}R  RRR {s['rrr']:.2f}  Net £{s['net']:,.0f}")
