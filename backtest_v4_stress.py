"""
backtest_v4_stress.py  -  V4 Live Trading Stress Test
======================================================
Runs the same 8 strategies under three cost scenarios:

  BASELINE   Current model (COST_SCALE=1.5, fixed per-strategy costs)
  REALISTIC  Variable spread + slippage + 3% gap risk on losing trades
  STRESS     2x spread + 2x slippage + 6% gap risk (extreme conditions)

Spread widens automatically when bar range > 1.5x ATR (volatile/news bars).

Run: python backtest_v4_stress.py
"""
import pandas as pd
import numpy as np
import os, warnings, random
from collections import defaultdict
warnings.filterwarnings('ignore')
random.seed(42)

ACCOUNT     = 70_000
MC_RUNS     = 3_000
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10

CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

# Normal spread in price units (tightest typical broker spread)
BASE_SPREAD = {
    'EURUSD': 0.00012,  # 1.2 pips
    'GBPUSD': 0.00018,  # 1.8 pips
    'DAX':    1.2,      # 1.2 pts
    'NAS100': 1.5,      # 1.5 pts
    'SP500':  0.25,     # 0.25 pts
    'UK100':  0.8,      # 0.8 pts
    'GOLD':   0.20,     # $0.20
}

# One-way slippage per entry (price moves before order fills)
BASE_SLIP = {
    'EURUSD': 0.00008,  # 0.8 pip
    'GBPUSD': 0.00012,  # 1.2 pips
    'DAX':    1.5,      # 1.5 pts
    'NAS100': 1.8,      # 1.8 pts
    'SP500':  0.20,     # 0.2 pts
    'UK100':  1.0,      # 1 pt
    'GOLD':   0.15,     # $0.15
}

# Gap risk: % of full-stop losses that gap through (exit worse than intended)
GAP_PROB = {'baseline': 0.00, 'realistic': 0.03, 'stress': 0.06}
GAP_MULT = {'baseline': 1.00, 'realistic': 1.50, 'stress': 2.00}

_cache = {}
def load_h1(key):
    if key in _cache: return _cache[key]
    fname = CSVSYMS.get(key)
    if not fname or not os.path.exists(fname): _cache[key] = None; return None
    df = pd.read_csv(fname)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    result = df.dropna() if len(df) > 200 else None
    _cache[key] = result; return result

def vol_mult(df, pos, scenario):
    """Spread multiplier: widens when current bar is volatile vs 20-bar ATR."""
    if scenario == 'baseline': return 1.0
    win = df.iloc[max(0, pos-20):pos]
    if len(win) < 5: return 1.0
    atr = (win['high'] - win['low']).mean()
    if atr <= 0: return 1.0
    br  = df.iloc[pos]['high'] - df.iloc[pos]['low']
    ratio = br / atr
    if ratio > 2.5: mult = 3.5   # extreme spike — news level
    elif ratio > 1.5: mult = 1.8 # elevated vol
    else: mult = 1.0
    return mult * (2.0 if scenario == 'stress' else 1.0)

def cost_r(key, sl_d, vm, scenario):
    """Total cost as fraction of SL distance (R units)."""
    if scenario == 'baseline':
        # Match original fixed cost model
        base = {'DAX':0.07,'NAS100':0.06,'SP500':0.06,
                'EURUSD':0.08,'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08}
        return base.get(key, 0.07) * 1.5
    s_mult = 2.0 if scenario == 'stress' else 1.0
    spread_pts = BASE_SPREAD[key] * vm * s_mult
    slip_pts   = BASE_SLIP[key]   * vm * s_mult
    return (spread_pts + slip_pts) / sl_d if sl_d > 0 else 0.10

def apply_gap(r, scenario):
    """Randomly worsen full SL losses to simulate gap-through exits."""
    if r > -0.90: return r
    if random.random() < GAP_PROB[scenario]:
        return r * GAP_MULT[scenario]
    return r

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

def _pnl(r, risk, c): return (r - c) * risk * ACCOUNT

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, trail, scenario, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None: return []
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
            b   = edf.iloc[j]
            p   = ipos(df, edf.index[j])
            if p < 0: continue
            vm  = vol_mult(df, p, scenario)
            slip = (BASE_SLIP.get(key,0) * vm * (2 if scenario=='stress' else 1)
                    if scenario != 'baseline' else 0)
            if b['high'] > rhi:
                entry = rhi + slip
                sl_d  = abs(entry - rlo)
                c     = cost_r(key, sl_d, vm, scenario)
                r     = sim(df, p, 1, entry, rlo, trail)
                r     = apply_gap(r, scenario)
                trades.append({'pnl':_pnl(r,risk,c),'date':str(date),'tag':tag}); break
            if b['low'] < rlo:
                entry = rlo - slip
                sl_d  = abs(rhi - entry)
                c     = cost_r(key, sl_d, vm, scenario)
                r     = sim(df, p, -1, entry, rhi, trail)
                r     = apply_gap(r, scenario)
                trades.append({'pnl':_pnl(r,risk,c),'date':str(date),'tag':tag}); break
    return trades

def run_lc(key, tag, min_move, risk, trail, scenario):
    df = load_h1(key)
    if df is None: return []
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
        dh  = sess['high'].max(); dl = sess['low'].min()
        buf = (dh - dl) * 0.03
        p   = ipos(df, day + pd.Timedelta(hours=16))
        if p < 0: continue
        vm    = vol_mult(df, p, scenario)
        slip  = (BASE_SLIP.get(key,0) * vm * (2 if scenario=='stress' else 1)
                 if scenario != 'baseline' else 0)
        entry = df.iloc[p]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        entry -= slip * d   # slippage worsens entry in trade direction
        sl_d   = abs(entry - sl)
        if sl_d <= 0: continue
        c = cost_r(key, sl_d, vm, scenario)
        r = sim(df, p, d, entry, sl, trail)
        r = apply_gap(r, scenario)
        trades.append({'pnl':_pnl(r,risk,c),'date':str(date),'tag':tag})
    return trades

def run_all(scenario):
    return (
        run_orb('DAX',   'DAX_ORB', 8,  10,12,  20, 200, 0.0075,0.05, scenario) +
        run_orb('NAS100','NAS_ORB',14,  16,18,  30,1000, 0.0075,0.05, scenario, frozenset({0,2,4})) +
        run_orb('SP500', 'SP5_ORB',14,  16,19,   3, 150, 0.004, 0.05, scenario, frozenset({0})) +
        run_lc('EURUSD', 'LC_EUR',  0.001,  0.004, 0.05, scenario) +
        run_lc('GBPUSD', 'LC_GBP',  0.0025, 0.004, 0.05, scenario) +
        run_lc('DAX',    'LC_DAX',  50.0,   0.0075,0.05, scenario) +
        run_lc('UK100',  'LC_UK',   30.0,   0.0075,0.05, scenario) +
        run_lc('GOLD',   'LC_GOLD', 4.0,    0.004, 0.05, scenario)
    )

def stats(trades):
    if len(trades) < 5: return None
    arr  = np.array([t['pnl'] for t in trades])
    wins = arr[arr > 5]; loss = arr[arr < -5]
    eq   = ACCOUNT + np.cumsum(arr)
    pk   = np.maximum.accumulate(eq)
    dd   = (pk - eq).max()
    pf   = round(wins.sum()/abs(loss.sum()),2) if len(loss) and loss.sum()!=0 else 0.0
    dates = sorted(set(t['date'] for t in trades))
    span  = max((pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days, 1)
    return {'n':len(arr),'pf':pf,'wr':round(len(wins)/len(arr)*100,1),
            'total':round(arr.sum(),0),'dd':round(dd,0),'mo':round(arr.sum()/span*21,0)}

def monte_carlo(trades):
    daily_pnl = defaultdict(float)
    for t in trades: daily_pnl[t['date']] += t['pnl']
    day_pnls = list(daily_pnl.values())
    target   = ACCOUNT * FTMO_TARGET
    dlimit   = ACCOUNT * FTMO_DAILY
    tlimit   = ACCOUNT * FTMO_TOTAL
    passes   = 0
    tdds     = []
    for _ in range(MC_RUNS):
        seq = day_pnls.copy(); random.shuffle(seq)
        eq  = ACCOUNT; peak = ACCOUNT; passed = failed = False; tdd = 0
        for dp in seq:
            ds = eq; eq += dp; peak = max(peak, eq); tdd = max(tdd, peak - eq)
            if (ds - eq) > dlimit:       failed = True; break
            if (ACCOUNT - eq) > tlimit:  failed = True; break
            if (eq - ACCOUNT) >= target: passed = True; break
        tdds.append(tdd)
        if passed: passes += 1
    return passes / MC_RUNS * 100, np.median(tdds)

if __name__ == '__main__':
    W = 80
    SCENARIOS = ['baseline', 'realistic', 'stress']

    print('\n' + '='*W)
    print('  V4 STRESS TEST  —  FTMO £70k  —  Slippage + Spread + Gap Risk')
    print('='*W)
    print('  BASELINE   Fixed costs (current model)')
    print('  REALISTIC  Variable spread (ATR-scaled) + slippage + 3% gap risk')
    print('  STRESS     2x spread + 2x slippage + 6% gap risk on SL losses')

    results = {}
    for sc in SCENARIOS:
        print(f'\n  [{sc.upper()}] running...', end=' ', flush=True)
        trades = run_all(sc)
        results[sc] = trades
        s = stats(trades)
        print(f'done — {len(trades)} trades')

    print('\n' + '='*W)
    print('  SCENARIO COMPARISON')
    print('='*W)
    print(f'  {"Scenario":<12} {"Trades":>7} {"WR%":>6} {"PF":>6} {"Total £":>10} {"£/month":>8} {"MaxDD":>8} {"MC Pass":>8}')
    print('  ' + '-'*70)

    for sc in SCENARIOS:
        trades = results[sc]
        s  = stats(trades)
        mc, mdd = monte_carlo(trades)
        print(f'  {sc.upper():<12} {s["n"]:>7} {s["wr"]:>5.1f}% {s["pf"]:>6.2f} '
              f'{s["total"]:>+10,.0f} {s["mo"]:>+8,.0f} {s["dd"]:>8,.0f} {mc:>7.1f}%')

    print()
    sr = stats(results['realistic'])
    ss = stats(results['stress'])
    print(f'  Realistic live estimate:  £{sr["mo"]:,.0f}/month')
    print(f'  Worst-case stress:        £{ss["mo"]:,.0f}/month')

    # Year by year for REALISTIC
    print('\n' + '='*W)
    print('  YEAR-BY-YEAR  (REALISTIC scenario)')
    print('='*W)
    print(f'  {"Year":4}  {"Trades":>6}  {"WR%":>5}  {"PF":>6}  {"Total £":>10}  {"£/month":>8}  {"MaxDD":>8}')
    print('  ' + '-'*60)

    NOTES = {
        '2018':'VIX spike Feb', '2019':'Bull/trade war',
        '2020':'COVID crash',   '2021':'Recovery + memes',
        '2022':'Rate hikes',    '2023':'AI rally',
        '2024':'Election+cuts', '2025':'Tariff shock',
        '2026':'YTD',
    }
    by_year = defaultdict(list)
    for t in results['realistic']: by_year[t['date'][:4]].append(t)
    for yr in sorted(by_year):
        s = stats(by_year[yr])
        if not s: continue
        print(f'  {yr}  {s["n"]:>6}  {s["wr"]:>4.1f}%  {s["pf"]:>6.2f}  '
              f'{s["total"]:>+10,.0f}  {s["mo"]:>+8,.0f}  {s["dd"]:>8,.0f}  {NOTES.get(yr,"")}')

    s_all = stats(results['realistic'])
    print('  ' + '-'*60)
    print(f'  ALL   {s_all["n"]:>6}  {s_all["wr"]:>4.1f}%  {s_all["pf"]:>6.2f}  '
          f'{s_all["total"]:>+10,.0f}  {s_all["mo"]:>+8,.0f}  {s_all["dd"]:>8,.0f}')

    print(f'\n  These are the numbers to plan around. REALISTIC is your expected')
    print(f'  live performance. STRESS is a genuine bad-conditions scenario.\n')
