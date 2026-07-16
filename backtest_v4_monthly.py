"""
backtest_v4_monthly.py  -  V4 System Full Monthly Breakdown
============================================================
Comprehensive output including:
  1. Monthly P&L table (every month 2018-2026)
  2. Trades per month / per day averages
  3. Best / worst month analysis
  4. Strategy contribution breakdown
  5. Year-by-year summary
  6. Walk-forward validation
  7. Monte Carlo FTMO pass rate

Run: python backtest_v4_monthly.py
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

def month_key(date_str):
    return date_str[:7]  # 'YYYY-MM'

def filter_dates(trades, start, end):
    return [t for t in trades if start <= t['date'] < end]

FOLDS = [
    ('2018-01-01','2021-01-01','2021-01-01','2022-01-01'),
    ('2019-01-01','2022-01-01','2022-01-01','2023-01-01'),
    ('2020-01-01','2023-01-01','2023-01-01','2024-01-01'),
    ('2021-01-01','2024-01-01','2024-01-01','2025-01-01'),
    ('2022-01-01','2025-01-01','2025-01-01','2026-01-01'),
]

# ── Section 1: Monthly breakdown ───────────────────────────────────────────────
def print_monthly(all_trades):
    W = 88
    by_month = defaultdict(list)
    for t in all_trades:
        by_month[month_key(t['date'])].append(t)

    by_day = defaultdict(list)
    for t in all_trades:
        by_day[t['date']].append(t)

    months = sorted(by_month.keys())

    print('\n' + '='*W)
    print('  1. MONTHLY BREAKDOWN  (V4 system, 70,000 GBP account)')
    print('='*W)
    print('  Month     Tr   WR%     PF    GBP P&L   Running Eq   MaxDD')
    print('  ' + '-'*72)

    running_eq = ACCOUNT
    profitable = losing = 0
    month_totals = []
    month_trades = []

    for mo in months:
        trades = by_month[mo]
        arr  = np.array([t['pnl'] for t in trades])
        wins = arr[arr > 5]; loss = arr[arr < -5]
        total = arr.sum()
        running_eq += total
        wr   = len(wins)/len(arr)*100 if len(arr) > 0 else 0
        pf   = round(wins.sum()/abs(loss.sum()),2) if len(loss) and loss.sum()!=0 else 0.0
        eq_arr = np.cumsum(arr)
        dd   = (np.maximum.accumulate(eq_arr) - eq_arr).max() if len(arr) > 0 else 0

        month_totals.append(total)
        month_trades.append(len(arr))

        ok = '+' if total >= 0 else '-'
        flag = '' if pf >= 1.5 else (' LOW' if pf >= 1.0 else ' WEAK')
        print('  {}  {:>3}  {:>5.1f}%  {:>5.2f}  {:>+9,.0f}   {:>9,.0f}   {:>7,.0f}  {}{}'.format(
            mo, len(arr), wr, pf, total, running_eq, dd, ok, flag))

        if total >= 0: profitable += 1
        else: losing += 1

    print('  ' + '-'*72)

    # Summary stats
    arr_all = np.array([t['pnl'] for t in all_trades])
    wins_all = arr_all[arr_all > 5]; loss_all = arr_all[arr_all < -5]
    pf_all = round(wins_all.sum()/abs(loss_all.sum()),2)
    print('\n  Total months: {}  |  Profitable: {}  |  Losing: {}'.format(
        len(months), profitable, losing))
    print('  Profitable month rate: {:.1f}%'.format(profitable/len(months)*100))
    print('\n  Best month:   {:>+,.0f}'.format(max(month_totals)))
    print('  Worst month:  {:>+,.0f}'.format(min(month_totals)))
    print('  Average/month:{:>+,.0f}'.format(np.mean(month_totals)))
    print('  Median/month: {:>+,.0f}'.format(np.median(month_totals)))
    print('  Std dev/month:{:>,.0f}'.format(np.std(month_totals)))

    # Trades per month / per day
    total_trading_days = len(by_day)
    print('\n  Avg trades/month: {:.0f}'.format(np.mean(month_trades)))
    print('  Avg trades/day:   {:.2f}  (across {} trading days)'.format(
        len(all_trades) / total_trading_days, total_trading_days))
    print('  Max trades/month: {}  |  Min trades/month: {}'.format(
        max(month_trades), min(month_trades)))

    # Day of week breakdown
    print('\n  Trades by day of week:')
    dow_names = {0:'Mon', 1:'Tue', 2:'Wed', 3:'Thu', 4:'Fri'}
    dow_counts = defaultdict(int); dow_pnl = defaultdict(float)
    for t in all_trades:
        d = pd.Timestamp(t['date']).dayofweek
        dow_counts[d] += 1; dow_pnl[d] += t['pnl']
    print('  ' + '  '.join('{}: {:>4} trades  {:>+8,.0f}'.format(
        dow_names.get(d,'?'), dow_counts[d], dow_pnl[d])
        for d in sorted(dow_counts)))

# ── Section 2: Strategy contribution ──────────────────────────────────────────
def print_strategy_summary(all_trades):
    W = 88
    print('\n' + '='*W)
    print('  2. STRATEGY CONTRIBUTION SUMMARY')
    print('='*W)
    print('  Strategy    Trades  WR%     PF    Total GBP   /month   Avg/trade')
    print('  ' + '-'*70)

    strats = ['DAX_ORB','NAS_ORB','SP5_ORB','LC_EUR','LC_GBP','LC_DAX','LC_UK','LC_GOLD']
    by_strat = defaultdict(list)
    for t in all_trades: by_strat[t['tag']].append(t)

    dates = sorted(set(t['date'] for t in all_trades))
    span_mo = (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days / 30.44

    for stg in strats:
        trades = by_strat[stg]
        if not trades:
            print('  {:<12} {:>6}  --'.format(stg, 0)); continue
        arr  = np.array([t['pnl'] for t in trades])
        wins = arr[arr > 5]; loss = arr[arr < -5]
        pf   = round(wins.sum()/abs(loss.sum()),2) if len(loss) and loss.sum()!=0 else 0.0
        wr   = len(wins)/len(arr)*100
        total = arr.sum()
        mo    = total / span_mo
        avg   = total / len(arr)
        print('  {:<12} {:>6}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  {:>+7,.0f}  {:>+8,.0f}'.format(
            stg, len(arr), wr, pf, total, mo, avg))

    print('  ' + '-'*70)
    arr_all = np.array([t['pnl'] for t in all_trades])
    wins_all = arr_all[arr_all > 5]; loss_all = arr_all[arr_all < -5]
    print('  {:<12} {:>6}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  {:>+7,.0f}  {:>+8,.0f}'.format(
        'TOTAL', len(arr_all),
        len(wins_all)/len(arr_all)*100,
        wins_all.sum()/abs(loss_all.sum()),
        arr_all.sum(), arr_all.sum()/span_mo, arr_all.sum()/len(arr_all)))

# ── Section 3: Year-by-year ────────────────────────────────────────────────────
NOTES = {
    '2018':'VIX spike', '2019':'Trade war', '2020':'COVID',
    '2021':'Meme stks', '2022':'Rate hikes','2023':'AI rally',
    '2024':'Election',  '2025':'Tariffs',   '2026':'YTD',
}
def print_yearly(all_trades):
    W = 88
    print('\n' + '='*W)
    print('  3. YEAR-BY-YEAR SUMMARY')
    print('='*W)
    print('  Year    Tr   WR%     PF    Total GBP   /month   MaxDD    Context')
    print('  ' + '-'*76)
    by_year = defaultdict(list)
    for t in all_trades: by_year[t['date'][:4]].append(t)
    for yr in sorted(by_year):
        trades = by_year[yr]
        arr  = np.array([t['pnl'] for t in trades])
        wins = arr[arr > 5]; loss = arr[arr < -5]
        pf   = round(wins.sum()/abs(loss.sum()),2) if len(loss) and loss.sum()!=0 else 0.0
        wr   = len(wins)/len(arr)*100
        dates = sorted(set(t['date'] for t in trades))
        span  = max((pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days, 1)
        mo    = arr.sum()/span*21
        eq    = ACCOUNT + np.cumsum(arr)
        dd    = (np.maximum.accumulate(eq)-eq).max()
        ok    = 'OK' if arr.sum() >= 0 else 'LOSS'
        print('  {}   {:>4}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  {:>+7,.0f}  {:>7,.0f}  {}  {}'.format(
            yr, len(arr), wr, pf, arr.sum(), mo, dd, NOTES.get(yr,''), ok))
    arr_all = np.array([t['pnl'] for t in all_trades])
    wins_all = arr_all[arr_all > 5]; loss_all = arr_all[arr_all < -5]
    dates_all = sorted(set(t['date'] for t in all_trades))
    span_all  = max((pd.Timestamp(dates_all[-1])-pd.Timestamp(dates_all[0])).days,1)
    eq_all = ACCOUNT + np.cumsum(arr_all)
    dd_all = (np.maximum.accumulate(eq_all)-eq_all).max()
    print('  ' + '-'*76)
    print('  ALL    {:>4}  {:>5.1f}%  {:>5.2f}  {:>+10,.0f}  {:>+7,.0f}  {:>7,.0f}'.format(
        len(arr_all), len(wins_all)/len(arr_all)*100,
        wins_all.sum()/abs(loss_all.sum()),
        arr_all.sum(), arr_all.sum()/span_all*21, dd_all))

# ── Section 4: Walk-forward ────────────────────────────────────────────────────
def print_walkforward(all_trades):
    W = 88
    print('\n' + '='*W)
    print('  4. WALK-FORWARD VALIDATION  (3-year IS / 1-year OOS)')
    print('='*W)
    print('  Fold  Train            OOS    IS PF   OOS PF   OOS Tr     OOS GBP')
    print('  ' + '-'*66)
    oos_pfs = []
    for i, (is_s, is_e, oos_s, oos_e) in enumerate(FOLDS):
        is_t  = filter_dates(all_trades, is_s, is_e)
        oos_t = filter_dates(all_trades, oos_s, oos_e)
        if len(is_t) < 5 or len(oos_t) < 5: continue
        def pf(trades):
            arr = np.array([t['pnl'] for t in trades])
            w = arr[arr>5]; l = arr[arr<-5]
            return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
        is_pf = pf(is_t); oos_pf = pf(oos_t)
        oos_total = sum(t['pnl'] for t in oos_t)
        oos_pfs.append(oos_pf)
        flag = 'PASS' if oos_pf >= 1.3 else ('WARN' if oos_pf >= 1.0 else 'FAIL')
        print('  F{}    {}--{}        {}   {:>7.2f}  {:>7.2f}   {:>6}   {:>+9,.0f}  {}'.format(
            i+1, is_s[:4], is_e[:4], oos_s[:4], is_pf, oos_pf, len(oos_t), oos_total, flag))
    if oos_pfs:
        print('  ' + '-'*66)
        print('  OOS PF: {:.2f} - {:.2f}  |  Mean: {:.2f}  |  All >= 1.3: {}'.format(
            min(oos_pfs), max(oos_pfs), np.mean(oos_pfs),
            'YES' if min(oos_pfs) >= 1.3 else 'NO'))

# ── Section 5: Monte Carlo ─────────────────────────────────────────────────────
def run_monte_carlo(all_trades):
    daily_pnl = defaultdict(float)
    for t in all_trades: daily_pnl[t['date']] += t['pnl']
    day_pnls    = list(daily_pnl.values())
    target      = ACCOUNT * FTMO_TARGET
    daily_limit = ACCOUNT * FTMO_DAILY
    total_limit = ACCOUNT * FTMO_TOTAL
    passes = fails_daily = fails_total = still_open = 0
    peak_dds = []; days_to_pass = []
    for _ in range(MC_RUNS):
        seq = day_pnls.copy(); random.shuffle(seq)
        eq = ACCOUNT; peak = ACCOUNT
        passed = failed = False; peak_dd = 0.0; day_count = 0
        for dp in seq:
            day_start = eq; eq += dp; day_count += 1
            peak = max(peak, eq); peak_dd = max(peak_dd, peak - eq)
            if (day_start - eq) > daily_limit:  fails_daily += 1; failed = True; break
            if (ACCOUNT - eq) > total_limit:    fails_total += 1; failed = True; break
            if (eq - ACCOUNT) >= target:        passed = True; break
        peak_dds.append(peak_dd)
        if passed:       passes += 1; days_to_pass.append(day_count)
        elif not failed: still_open += 1
    pass_rate = passes / MC_RUNS * 100
    W = 88
    print('\n' + '='*W)
    print('  5. MONTE CARLO  FTMO PHASE 1  ({:,} simulations)'.format(MC_RUNS))
    print('  Target +{:,.0f}  |  Daily limit -{:,.0f}  |  Total limit -{:,.0f}'.format(
        target, daily_limit, total_limit))
    print('='*W)
    print('\n  Passed (target hit):        {:>5,}  ({:.1f}%)'.format(passes, pass_rate))
    print('  Failed daily breach:        {:>5,}  ({:.1f}%)'.format(fails_daily, fails_daily/MC_RUNS*100))
    print('  Failed total DD:            {:>5,}  ({:.1f}%)'.format(fails_total, fails_total/MC_RUNS*100))
    print('  Still trading at end:       {:>5,}  ({:.1f}%)'.format(still_open, still_open/MC_RUNS*100))
    print('\n  Median days to pass:        {:>5.0f}  trading days'.format(
        np.median(days_to_pass) if days_to_pass else 0))
    print('  Median peak drawdown:       {:>8,.0f}'.format(np.median(peak_dds)))
    print('  95th pctile peak DD:        {:>8,.0f}'.format(np.percentile(peak_dds, 95)))
    if pass_rate >= 90:   verdict = 'Strong -- deploy with confidence'
    elif pass_rate >= 75: verdict = 'Good edge -- proceed'
    elif pass_rate >= 60: verdict = 'Moderate -- review'
    else:                 verdict = 'Weak -- do not deploy'
    print('\n  -- PASS RATE: {:.1f}%  ->  {} --\n'.format(pass_rate, verdict))

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 88
    print('\n' + '='*W)
    print('  V4 SYSTEM  FULL BACKTEST  (70,000 GBP FTMO)')
    print('  trail=0.05  |  V4 optimised parameters  |  H1 simulation')
    print('='*W)
    for k in CSVSYMS: load_h1(k)
    print('\n  Running all 8 strategies...')
    all_trades = run_all()
    print('  Total trades: {:,}\n'.format(len(all_trades)))
    print_monthly(all_trades)
    print_strategy_summary(all_trades)
    print_yearly(all_trades)
    print_walkforward(all_trades)
    run_monte_carlo(all_trades)
