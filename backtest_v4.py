"""
backtest_v4.py  -  V4 System Full Backtest
==========================================
V4 locked parameters from grid-search + walk-forward optimisation.
Run: python backtest_v4.py
"""
import pandas as pd
import numpy as np
import os, warnings, random
from collections import defaultdict
warnings.filterwarnings('ignore')

ACCOUNT = 70_000
COST_SCALE = 1.5
MC_RUNS = 5_000
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10

CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',
    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv',
    'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv',
    'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

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

def _pnl(r, risk, cost): return (r - cost * COST_SCALE) * risk * ACCOUNT

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, trail, cost, skip_dow=frozenset()):
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
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                r = sim(df, p, 1, rhi, rlo, trail)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
            if b['low'] < rlo:
                r = sim(df, p,-1, rlo, rhi, trail)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
    return trades

def run_lc(key, tag, min_move, risk, trail, cost):
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
        dh = sess['high'].max(); dl = sess['low'].min(); buf = (dh - dl) * 0.03
        p  = ipos(df, day + pd.Timedelta(hours=16))
        if p < 0: continue
        entry = df.iloc[p]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        r = sim(df, p, d, entry, sl, trail)
        trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r})
    return trades

def run_all():
    return (
        run_orb('DAX',   'DAX_ORB', 8,  10,12,  20, 200, 0.0075,0.05,0.07) +
        run_orb('NAS100','NAS_ORB',14,  16,18,  30,1000, 0.0075,0.05,0.06, frozenset({0,2,4})) +
        run_orb('SP500', 'SP5_ORB',14,  16,19,   3, 150, 0.004, 0.05,0.06, frozenset({0})) +
        run_lc('EURUSD', 'LC_EUR',  0.001,  0.004, 0.05,0.08) +
        run_lc('GBPUSD', 'LC_GBP',  0.0025, 0.004, 0.05,0.08) +
        run_lc('DAX',    'LC_DAX',  50.0,   0.0075,0.05,0.07) +
        run_lc('UK100',  'LC_UK',   30.0,   0.0075,0.05,0.07) +
        run_lc('GOLD',   'LC_GOLD', 4.0,    0.004, 0.05,0.08)
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
    return {
        'n':len(arr), 'pf':pf, 'wr':round(len(wins)/len(arr)*100,1),
        'total':round(arr.sum(),0), 'dd':round(dd,0),
        'mo':round(arr.sum()/span*21,0),
    }

def filter_dates(trades, start, end):
    return [t for t in trades if start <= t['date'] < end]

NOTES = {
    '2018':'VIX spike Feb',       '2019':'Steady bull, trade war',
    '2020':'COVID crash',         '2021':'Meme stocks, recovery',
    '2022':'Rate hikes, bear',    '2023':'AI rally, low vol',
    '2024':'Election + rate cuts','2025':'Tariff shock Apr',
    '2026':'Partial YTD',
}

FOLDS = [
    ('2018-01-01','2021-01-01','2021-01-01','2022-01-01'),
    ('2019-01-01','2022-01-01','2022-01-01','2023-01-01'),
    ('2020-01-01','2023-01-01','2023-01-01','2024-01-01'),
    ('2021-01-01','2024-01-01','2024-01-01','2025-01-01'),
    ('2022-01-01','2025-01-01','2025-01-01','2026-01-01'),
]

def print_yearly(all_trades):
    W = 80
    print('\n' + '='*W)
    print('  1. YEAR-BY-YEAR BREAKDOWN')
    print('='*W)
    print('  Year    Tr    WR%      PF    Total      /mo    MaxDD  Context')
    print('  ' + '-'*76)
    by_year = defaultdict(list)
    for t in all_trades: by_year[t['date'][:4]].append(t)
    prof = loss_yr = 0
    for yr in sorted(by_year):
        s = stats(by_year[yr])
        if not s: continue
        ok  = 'OK' if s['total'] >= 0 else 'LOSS'
        pff = '' if s['pf'] >= 1.5 else (' LOW' if s['pf'] >= 1.0 else ' WEAK')
        sign = '+' if s['total'] >= 0 else ''
        if s['total'] >= 0: prof += 1
        else: loss_yr += 1
        print('  {}  {:>4}  {:>5.1f}%  {:>6.2f}  {:>+8,.0f}  {:>6,.0f}  {:>6,.0f}  {}  {}{}'.format(
            yr, s['n'], s['wr'], s['pf'], s['total'], s['mo'], s['dd'],
            NOTES.get(yr,''), ok, pff))
    s = stats(all_trades)
    print('  ' + '-'*76)
    print('  ALL   {:>4}  {:>5.1f}%  {:>6.2f}  {:>+8,.0f}  {:>6,.0f}  {:>6,.0f}'.format(
        s['n'], s['wr'], s['pf'], s['total'], s['mo'], s['dd']))
    print('\n  Profitable years: {}/{}  |  Losing years: {}/{}'.format(
        prof, prof+loss_yr, loss_yr, prof+loss_yr))

    strat_yr = defaultdict(list)
    for t in all_trades: strat_yr[(t['date'][:4], t['tag'])].append(t)
    strats = ['DAX_ORB','NAS_ORB','SP5_ORB','LC_EUR','LC_GBP','LC_DAX','LC_UK','LC_GOLD']
    print('\n  Strategy P&L by year (GBP):')
    print('  ' + 'Year  ' + ''.join('{:>10}'.format(s) for s in strats))
    print('  ' + '-'*86)
    for yr in sorted(by_year):
        row = '  ' + yr + '  '
        for stg in strats:
            t = strat_yr[(yr, stg)]
            if not t: row += '{:>10}'.format('--')
            else:
                tot = sum(x['pnl'] for x in t)
                row += '{:>+10,.0f}'.format(tot)
        print(row)

def print_walkforward(all_trades):
    W = 80
    print('\n' + '='*W)
    print('  2. WALK-FORWARD VALIDATION  (3-year IS / 1-year OOS, 5 folds)')
    print('  V4 params are fixed -- shows OOS consistency across market regimes')
    print('='*W)
    print('  Fold  Train            OOS    IS PF   OOS PF   OOS Tr     OOS GBP')
    print('  ' + '-'*66)
    oos_pfs = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(FOLDS):
        is_t  = filter_dates(all_trades, is_s, is_e)
        oos_t = filter_dates(all_trades, oos_s, oos_e)
        si = stats(is_t); so = stats(oos_t)
        if not si or not so: continue
        oos_pfs.append(so['pf'])
        flag = 'PASS' if so['pf'] >= 1.3 else ('WARN' if so['pf'] >= 1.0 else 'FAIL')
        print('  F{}    {}--{}        {}   {:>7.2f}  {:>7.2f}   {:>6}   {:>+9,.0f}  {}'.format(
            i+1, is_s[:4], is_e[:4], oos_s[:4],
            si['pf'], so['pf'], so['n'], so['total'], flag))
    if oos_pfs:
        print('  ' + '-'*66)
        print('  OOS PF range: {:.2f} -- {:.2f}  |  Mean: {:.2f}'.format(
            min(oos_pfs), max(oos_pfs), np.mean(oos_pfs)))
        if min(oos_pfs) >= 1.3:
            print('  -> All OOS folds >= 1.3  -- consistent edge confirmed')
        elif min(oos_pfs) >= 1.0:
            print('  -> All OOS profitable -- some variance, monitor')
        else:
            print('  -> Weak OOS fold -- investigate before deploying')

def run_monte_carlo(all_trades):
    daily_pnl = defaultdict(float)
    for t in all_trades: daily_pnl[t['date']] += t['pnl']
    day_pnls    = list(daily_pnl.values())
    target      = ACCOUNT * FTMO_TARGET
    daily_limit = ACCOUNT * FTMO_DAILY
    total_limit = ACCOUNT * FTMO_TOTAL
    passes = fails_daily = fails_total = still_open = 0
    peak_dds = []
    for _ in range(MC_RUNS):
        seq = day_pnls.copy(); random.shuffle(seq)
        eq = ACCOUNT; peak = ACCOUNT
        passed = False; failed = False; peak_dd = 0.0
        for dp in seq:
            day_start = eq; eq += dp
            peak = max(peak, eq)
            peak_dd = max(peak_dd, peak - eq)
            if (day_start - eq) > daily_limit:
                fails_daily += 1; failed = True; break
            if (ACCOUNT - eq) > total_limit:
                fails_total += 1; failed = True; break
            if (eq - ACCOUNT) >= target:
                passed = True; break
        peak_dds.append(peak_dd)
        if passed:       passes += 1
        elif not failed: still_open += 1

    pass_rate = passes / MC_RUNS * 100
    W = 80
    print('\n' + '='*W)
    print('  3. MONTE CARLO -- FTMO PHASE 1  ({:,} simulations, shuffle daily P&L)'.format(MC_RUNS))
    print('  Target +{:,.0f}  |  Daily limit -{:,.0f}  |  Total limit -{:,.0f}'.format(
        target, daily_limit, total_limit))
    print('='*W)
    print('\n  Passed (target hit):        {:>5,}  ({:.1f}%)'.format(passes, pass_rate))
    print('  Failed -- daily breach:     {:>5,}  ({:.1f}%)'.format(fails_daily, fails_daily/MC_RUNS*100))
    print('  Failed -- total DD:         {:>5,}  ({:.1f}%)'.format(fails_total, fails_total/MC_RUNS*100))
    print('  Still trading at end:       {:>5,}  ({:.1f}%)'.format(still_open, still_open/MC_RUNS*100))
    print('\n  Median peak drawdown:       {:>8,.0f}'.format(np.median(peak_dds)))
    print('  95th pctile peak DD:        {:>8,.0f}'.format(np.percentile(peak_dds, 95)))
    if pass_rate >= 90:   verdict = 'Strong edge -- deploy with confidence'
    elif pass_rate >= 75: verdict = 'Good edge -- proceed'
    elif pass_rate >= 60: verdict = 'Moderate edge -- review params'
    else:                 verdict = 'Weak edge -- do not deploy'
    print('\n  -- PASS RATE: {:.1f}%  ->  {} --\n'.format(pass_rate, verdict))

if __name__ == '__main__':
    W = 80
    print('\n' + '='*W)
    print('  V4 SYSTEM -- FULL 8-YEAR BACKTEST  (70,000 GBP FTMO)')
    print('  trail=0.05 universal + per-strategy optimised entries')
    print('='*W)
    for k in CSVSYMS: load_h1(k)
    print('\n  Running 8 strategies...')
    all_trades = run_all()
    print('  Total trades: {:,}'.format(len(all_trades)))
    print_yearly(all_trades)
    print_walkforward(all_trades)
    run_monte_carlo(all_trades)
