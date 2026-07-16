"""
backtest_v4_cot.py  -  V4 System + COT Filter Backtest
=======================================================
Tests whether filtering LC trades using CFTC COT positioning improves results.

COT filter logic (LC strategies only):
  - Each week CFTC publishes net non-commercial (large speculator) positions
  - If specs are NET LONG → only take LC SHORT trades (fade up-moves)
    (Trend followers are long = morning rallies are "with" the crowd = risky to fade)
  - If specs are NET SHORT → only take LC LONG trades (fade down-moves)
  - In other words: only trade when reversing into the institutional bias direction

ORB strategies are unaffected (momentum strategies, not reversals).

Output:
  - Full comparison table: no filter vs COT filter for each LC strategy
  - Monthly breakdown with COT filter applied
  - Walk-forward and Monte Carlo on filtered results

Requires: COT_weekly.csv (run download_cot.py first)

Run: python backtest_v4_cot.py
"""
import pandas as pd
import numpy as np
import os, warnings, random
from collections import defaultdict
warnings.filterwarnings('ignore')

ACCOUNT    = 70_000
COST_SCALE = 1.5
MC_RUNS    = 5_000
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10

CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}
COT_INSTRUMENTS = {
    'EURUSD': 'EUR', 'GBPUSD': 'GBP', 'GOLD': 'GOLD',
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

_cot_cache = {}
def load_cot():
    if 'data' in _cot_cache: return _cot_cache['data']
    if not os.path.exists('COT_weekly.csv'):
        print('ERROR: COT_weekly.csv not found. Run download_cot.py first.')
        return None
    df = pd.read_csv('COT_weekly.csv', parse_dates=['date'])
    df = df.sort_values('date')
    _cot_cache['data'] = df
    return df

def get_cot_direction(cot_df, instrument, trade_date):
    """Return 1 (specs net long) or -1 (specs net short) as of most recent COT report."""
    sym = COT_INSTRUMENTS.get(instrument)
    if not sym or cot_df is None: return 0  # 0 = no data, don't filter
    rows = cot_df[(cot_df['instrument'] == sym) &
                  (cot_df['date'] <= pd.Timestamp(trade_date, tz=None))]
    if len(rows) == 0: return 0
    return 1 if rows.iloc[-1]['net_long'] > 0 else -1

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
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r,'dir':1})
                break
            if b['low'] < rlo:
                r = sim(df, p,-1, rlo, rhi, trail)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r,'dir':-1})
                break
    return trades

def run_lc(key, tag, min_move, risk, trail, cost, cot_df=None, use_cot=False):
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
        if move > 0: sl = dh + buf; d = -1   # fade the rally → short
        else:        sl = dl - buf; d =  1   # fade the drop  → long
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue

        # COT filter: only take trade if direction aligns with spec positioning
        if use_cot and cot_df is not None:
            cot_bias = get_cot_direction(cot_df, key, date)
            if cot_bias != 0 and d != cot_bias:
                continue  # spec bias opposes trade direction — skip

        r = sim(df, p, d, entry, sl, trail)
        trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r,'dir':d})
    return trades

def run_all(cot_df=None, use_cot=False):
    return (
        run_orb('DAX',   'DAX_ORB', 8,  10,12,  20, 200, 0.0075,0.05,0.07) +
        run_orb('NAS100','NAS_ORB',14,  16,18,  30,1000, 0.0075,0.05,0.06, frozenset({0,2,4})) +
        run_orb('SP500', 'SP5_ORB',14,  16,19,   3, 150, 0.004, 0.05,0.06, frozenset({0})) +
        run_lc('EURUSD','LC_EUR',  0.001,  0.004, 0.05,0.08, cot_df, use_cot) +
        run_lc('GBPUSD','LC_GBP',  0.0025, 0.004, 0.05,0.08, cot_df, use_cot) +
        run_lc('DAX',   'LC_DAX',  50.0,   0.0075,0.05,0.07, None,   False) +   # no CFTC data for DAX
        run_lc('UK100', 'LC_UK',   30.0,   0.0075,0.05,0.07, None,   False) +   # no CFTC data for UK100
        run_lc('GOLD',  'LC_GOLD', 4.0,    0.004, 0.05,0.08, cot_df, use_cot)
    )

def strat_stats(trades, span_mo):
    if not trades: return None
    arr = np.array([t['pnl'] for t in trades])
    w = arr[arr>5]; l = arr[arr<-5]
    pf = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    return dict(n=len(arr), wr=len(w)/len(arr)*100, pf=pf,
                total=arr.sum(), pm=arr.sum()/span_mo)

FOLDS = [
    ('2018-01-01','2021-01-01','2021-01-01','2022-01-01'),
    ('2019-01-01','2022-01-01','2022-01-01','2023-01-01'),
    ('2020-01-01','2023-01-01','2023-01-01','2024-01-01'),
    ('2021-01-01','2024-01-01','2024-01-01','2025-01-01'),
    ('2022-01-01','2025-01-01','2025-01-01','2026-01-01'),
]

def filter_dates(trades, start, end):
    return [t for t in trades if start <= t['date'] < end]

def pf(trades):
    if not trades: return 0.0
    arr = np.array([t['pnl'] for t in trades])
    w = arr[arr>5]; l = arr[arr<-5]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0

def run_mc(all_trades, label):
    daily_pnl = defaultdict(float)
    for t in all_trades: daily_pnl[t['date']] += t['pnl']
    day_pnls    = list(daily_pnl.values())
    target      = ACCOUNT * FTMO_TARGET
    daily_limit = ACCOUNT * FTMO_DAILY
    total_limit = ACCOUNT * FTMO_TOTAL
    passes = 0; days_to_pass = []
    for _ in range(MC_RUNS):
        seq = day_pnls.copy(); random.shuffle(seq)
        eq = ACCOUNT; passed = failed = False
        for dp in seq:
            day_start = eq; eq += dp
            if (day_start - eq) > daily_limit: failed = True; break
            if (ACCOUNT - eq) > total_limit:   failed = True; break
            if not passed and (eq - ACCOUNT) >= target:
                passed = True; break
        if passed: passes += 1
    return passes / MC_RUNS * 100

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 90
    print('\n' + '='*W)
    print('  V4 + COT FILTER BACKTEST  (70,000 GBP)')
    print('='*W)

    for k in CSVSYMS: load_h1(k)
    cot_df = load_cot()
    if cot_df is None: exit(1)

    print('\n  Running baseline (no filter)...')
    base = run_all(cot_df, use_cot=False)

    print('  Running with COT filter...')
    filtered = run_all(cot_df, use_cot=True)

    dates = sorted(set(t['date'] for t in base))
    span_mo = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 30.44

    # ── Strategy comparison table ─────────────────────────────────────────────
    print('\n' + '='*W)
    print('  STRATEGY COMPARISON: BASELINE vs COT FILTER')
    print('='*W)
    print('  {:<12}  {:>6}  {:>5}  {:>5}  {:>10}  |  {:>6}  {:>5}  {:>5}  {:>10}  {:>8}'.format(
        'Strategy', 'Tr', 'WR%', 'PF', 'Total GBP',
        'Tr', 'WR%', 'PF', 'Total GBP', 'Delta'))
    print('  {:<12}  {:>26}  |  {:>26}  {:>8}'.format(
        '', '--- BASELINE ---', '--- COT FILTER ---', ''))
    print('  ' + '-'*78)

    strats = ['DAX_ORB','NAS_ORB','SP5_ORB','LC_EUR','LC_GBP','LC_DAX','LC_UK','LC_GOLD']
    base_by_strat  = defaultdict(list)
    filt_by_strat  = defaultdict(list)
    for t in base:     base_by_strat[t['tag']].append(t)
    for t in filtered: filt_by_strat[t['tag']].append(t)

    for stg in strats:
        b = strat_stats(base_by_strat[stg],  span_mo)
        f = strat_stats(filt_by_strat[stg],  span_mo)
        if not b: continue
        cot_tag = '(COT)' if stg in ('LC_EUR','LC_GBP','LC_GOLD') else '(n/a) '
        delta = f['total'] - b['total'] if f else -b['total']
        f_str = '{:>6}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}'.format(
            f['n'], f['wr'], f['pf'], f['total']) if f else '    --'
        print('  {:<12}  {:>6}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  |  {}  {:>+8,.0f}  {}'.format(
            stg, b['n'], b['wr'], b['pf'], b['total'],
            f_str, delta, cot_tag))

    # totals
    def totals(trades):
        arr = np.array([t['pnl'] for t in trades])
        w = arr[arr>5]; l = arr[arr<-5]
        return len(arr), len(w)/len(arr)*100, w.sum()/abs(l.sum()), arr.sum()
    bn, bwr, bpf, btot = totals(base)
    fn, fwr, fpf, ftot = totals(filtered)
    print('  ' + '-'*78)
    print('  {:<12}  {:>6}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  |  {:>6}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  {:>+8,.0f}'.format(
        'TOTAL', bn, bwr, bpf, btot, fn, fwr, fpf, ftot, ftot - btot))

    # ── LC strategies deep dive ───────────────────────────────────────────────
    lc_strats = ['LC_EUR','LC_GBP','LC_GOLD']
    print('\n' + '='*W)
    print('  LC STRATEGY DETAIL (COT-filtered instruments only)')
    print('='*W)
    print('  {:<10}  {:>26}  |  {:>26}  {:>9}'.format(
        '', '--- BASELINE ---', '--- COT FILTER ---', ''))
    print('  {:<10}  {:>6}  {:>5}  {:>5}  {:>7}  |  {:>6}  {:>5}  {:>5}  {:>7}  {:>9}'.format(
        'Strategy', 'Tr', 'WR%', 'PF', '£/mo',
                    'Tr', 'WR%', 'PF', '£/mo', '£/mo Δ'))
    print('  ' + '-'*72)
    for stg in lc_strats:
        b = strat_stats(base_by_strat[stg], span_mo)
        f = strat_stats(filt_by_strat[stg], span_mo)
        if not b: continue
        f_str = '{:>6}  {:>5.1f}%  {:>5.2f}  {:>+7,.0f}'.format(
            f['n'], f['wr'], f['pf'], f['pm']) if f else '    --'
        delta_pm = f['pm'] - b['pm'] if f else 0
        print('  {:<10}  {:>6}  {:>5.1f}%  {:>5.2f}  {:>+7,.0f}  |  {}  {:>+9,.0f}'.format(
            stg, b['n'], b['wr'], b['pf'], b['pm'], f_str, delta_pm))
    print()
    print('  COT filter reduces trade count (skips ~50% of LC EUR/GBP/GOLD trades).')
    print('  If PF improves materially (>0.3), the filter adds genuine edge.')
    print('  If PF is similar or worse, the filter is just reducing exposure with no benefit.')

    # ── Monthly breakdown (filtered) ──────────────────────────────────────────
    print('\n' + '='*W)
    print('  MONTHLY BREAKDOWN — COT FILTERED SYSTEM')
    print('='*W)
    print('  Month     Tr   WR%     PF    GBP P&L   Running Eq')
    print('  ' + '-'*55)
    by_month = defaultdict(list)
    for t in filtered: by_month[t['date'][:7]].append(t)
    running_eq = ACCOUNT; profitable = losing = 0
    for mo in sorted(by_month):
        trades = by_month[mo]
        arr = np.array([t['pnl'] for t in trades])
        w = arr[arr>5]; l = arr[arr<-5]
        total = arr.sum(); running_eq += total
        wr  = len(w)/len(arr)*100 if len(arr) > 0 else 0
        ppf = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
        ok  = '+' if total >= 0 else '-'
        if total >= 0: profitable += 1
        else: losing += 1
        print('  {}  {:>3}  {:>5.1f}%  {:>5.2f}  {:>+9,.0f}   {:>9,.0f}  {}'.format(
            mo, len(arr), wr, ppf, total, running_eq, ok))
    print('\n  Profitable months: {}  |  Losing: {}  |  Rate: {:.1f}%'.format(
        profitable, losing, profitable/(profitable+losing)*100))

    # ── Walk-forward ──────────────────────────────────────────────────────────
    print('\n' + '='*W)
    print('  WALK-FORWARD (COT filtered) vs BASELINE')
    print('='*W)
    print('  Fold  OOS     Base PF → COT PF    OOS Trades Base → COT    OOS GBP Base → COT')
    print('  ' + '-'*72)
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(FOLDS):
        bt = filter_dates(base,     oos_s, oos_e)
        ft = filter_dates(filtered, oos_s, oos_e)
        if not bt or not ft: continue
        bpf_oos = pf(bt); fpf_oos = pf(ft)
        flag = 'BETTER' if fpf_oos > bpf_oos + 0.1 else ('WORSE' if fpf_oos < bpf_oos - 0.1 else 'SAME')
        print('  F{}    {}   {:>5.2f} → {:>5.2f}    {:>4} → {:>4}        {:>+9,.0f} → {:>+9,.0f}  {}'.format(
            i+1, oos_s[:4], bpf_oos, fpf_oos,
            len(bt), len(ft),
            sum(t['pnl'] for t in bt), sum(t['pnl'] for t in ft),
            flag))

    # ── Monte Carlo comparison ─────────────────────────────────────────────────
    print('\n' + '='*W)
    print('  MONTE CARLO FTMO PHASE 1  ({:,} runs)'.format(MC_RUNS))
    print('='*W)
    base_pass = run_mc(base, 'baseline')
    filt_pass = run_mc(filtered, 'cot_filter')
    print('  Baseline pass rate:    {:.1f}%'.format(base_pass))
    print('  COT filter pass rate:  {:.1f}%'.format(filt_pass))
    verdict = 'IMPROVEMENT' if filt_pass > base_pass + 2 else \
              ('WORSE' if filt_pass < base_pass - 2 else 'NO MATERIAL DIFFERENCE')
    print('\n  COT filter effect on FTMO pass rate: {}'.format(verdict))
    print()
    print('  CONCLUSION:')
    print('  If COT PF > baseline PF across most folds → add COT filter to V4 EA')
    print('  If COT PF similar or worse → discard COT filter, save the complexity')
