"""
backtest_yearly.py  —  Year-by-Year Breakdown
==============================================
Runs the main 8-strategy portfolio and splits results by calendar year.

Key question: is PF 1.96 consistent across all 8 years,
or is it 2 great years masking 6 average ones?

Run: python backtest_yearly.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

ACCOUNT    = 70_000
COST_SCALE = 1.5
TRAIL      = 0.10

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
    _cache[key] = df.dropna() if len(df) > 200 else None
    return _cache[key]

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    return int(a) if a < len(df) and df.index[int(a)] == ts else -1

def sim(df, ep, direction, entry, sl, max_bars=80):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    tr = sl_d * TRAIL; cs = sl; bst = entry; be = False
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

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, cost, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb  = df[df.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue
        edf = df[(df.index >= day+pd.Timedelta(hours=es)) &
                 (df.index <  day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                r = sim(df, p, 1, rhi, rlo)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
            if b['low'] < rlo:
                r = sim(df, p, -1, rlo, rhi)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
    return trades

def run_lc(key, tag, min_move, risk, cost):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        ob  = df[df.index == day+pd.Timedelta(hours=7)]
        cb  = df[df.index == day+pd.Timedelta(hours=15)]
        if len(ob) == 0 or len(cb) == 0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue
        sess = df[(df.index >= day+pd.Timedelta(hours=7)) &
                  (df.index <= day+pd.Timedelta(hours=16))]
        if len(sess) == 0: continue
        dh = sess['high'].max(); dl = sess['low'].min(); buf = (dh-dl)*0.03
        p  = ipos(df, day+pd.Timedelta(hours=16))
        if p < 0: continue
        entry = df.iloc[p]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        r = sim(df, p, d, entry, sl)
        trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r})
    return trades

def run_all():
    return (run_orb('DAX',   'DAX_ORB', 8,  9, 12, 30,  300, 0.0075, 0.07) +
            run_orb('NAS100','NAS_ORB',13, 14, 16, 50, 1500, 0.0075, 0.06, {0,2,4}) +
            run_orb('SP500', 'SP5_ORB',13, 14, 16,  5,  300, 0.004,  0.06, {0}) +
            run_lc('EURUSD','LC_EUR',0.0020,0.004,0.08) +
            run_lc('GBPUSD','LC_GBP',0.0025,0.004,0.08) +
            run_lc('DAX',   'LC_DAX',30.0, 0.0075,0.07) +
            run_lc('UK100', 'LC_UK', 30.0, 0.0075,0.07) +
            run_lc('GOLD',  'LC_GOLD',8.0, 0.004, 0.08))

def year_stats(trades):
    if len(trades) < 5: return None
    arr  = np.array([t['pnl'] for t in trades])
    wins = arr[arr > 5]; loss = arr[arr < -5]
    dates = sorted(set(t['date'] for t in trades))
    span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    eq    = ACCOUNT + np.cumsum(arr)
    pk    = np.maximum.accumulate(eq)
    dd    = (pk - eq).max()
    return {
        'n':     len(arr),
        'wr':    round(len(wins)/len(arr)*100, 1),
        'pf':    round(wins.sum()/abs(loss.sum()), 2) if len(loss) and loss.sum()!=0 else 0.0,
        'total': round(arr.sum(), 0),
        'mo':    round(arr.sum()/span*21, 0),
        'dd':    round(dd, 0),
    }

NOTES = {
    '2018': 'VIX spike Feb, vol year',
    '2019': 'Steady bull, US-China trade war',
    '2020': 'COVID crash Mar, huge vol',
    '2021': 'Recovery rally, meme stocks',
    '2022': 'Rate hikes, bear market',
    '2023': 'AI rally, low vol',
    '2024': 'Election year, rate cuts',
    '2025': 'Tariff shock Apr',
    '2026': 'Partial year (YTD)',
}

if __name__ == '__main__':
    W = 78
    print("\n" + "="*W)
    print("  YEAR-BY-YEAR BREAKDOWN  —  Main 8-strategy portfolio")
    print("  Is PF 1.96 consistent, or carried by a few outlier years?")
    print("="*W)
    for k in CSVSYMS: load_h1(k)
    print("\n  Running all strategies across 8 years...")
    all_trades = run_all()
    print(f"  Total trades: {len(all_trades)}\n")

    # Group by year
    from collections import defaultdict
    by_year = defaultdict(list)
    for t in all_trades:
        by_year[t['date'][:4]].append(t)

    # Per-strategy breakdown by year
    strat_trades = defaultdict(list)
    for t in all_trades:
        strat_trades[(t['date'][:4], t['tag'])].append(t)

    years = sorted(by_year.keys())

    print(f"  {'Year':<6} {'Tr':>4} {'WR%':>6} {'PF':>6} {'Total £':>9} {'£/mo':>8} "
          f"{'MaxDD':>8}  {'Market context'}")
    print("  " + "─"*(W-2))

    profitable = losing = 0
    for yr in years:
        trades = by_year[yr]
        s = year_stats(trades)
        if not s: continue
        sign = '+' if s['total'] >= 0 else ''
        if s['total'] >= 0:
            profitable += 1
            ok = '✅'
        else:
            losing += 1
            ok = '❌'
        pf_flag = '' if s['pf'] >= 1.5 else (' ⚠' if s['pf'] >= 1.0 else ' 🔴')
        note = NOTES.get(yr, '')
        print(f"  {yr}   {s['n']:>4} {s['wr']:>5.1f}% {s['pf']:>6.2f} "
              f"£{sign}{s['total']:>7,.0f} £{s['mo']:>6,.0f} "
              f"£{s['dd']:>7,.0f}  {note}  {ok}{pf_flag}")

    # Totals
    all_arr = np.array([t['pnl'] for t in all_trades])
    all_dates = sorted(set(t['date'] for t in all_trades))
    span = max((pd.Timestamp(all_dates[-1]) - pd.Timestamp(all_dates[0])).days, 1)
    all_eq = ACCOUNT + np.cumsum(all_arr)
    all_dd = (np.maximum.accumulate(all_eq) - all_eq).max()
    wins_all = all_arr[all_arr>5]; loss_all = all_arr[all_arr<-5]
    print("  " + "─"*(W-2))
    print(f"  {'ALL':<6} {len(all_arr):>4} {len(wins_all)/len(all_arr)*100:>5.1f}% "
          f"{wins_all.sum()/abs(loss_all.sum()):>6.2f} "
          f"£{all_arr.sum():>8,.0f} £{all_arr.sum()/span*21:>6,.0f} "
          f"£{all_dd:>7,.0f}")

    print(f"\n  Profitable years: {profitable}/{profitable+losing}")
    print(f"  Losing years:     {losing}/{profitable+losing}")

    # Per-strategy per-year heatmap
    print(f"\n{'='*W}")
    print("  STRATEGY BREAKDOWN BY YEAR  (£ total each year)")
    print("="*W)
    strategies = ['DAX_ORB','NAS_ORB','SP5_ORB','LC_EUR','LC_GBP','LC_DAX','LC_UK','LC_GOLD']
    header = f"  {'Year':<6}" + "".join(f"{s:>10}" for s in strategies)
    print(header)
    print("  " + "─"*(W-2))
    for yr in years:
        row = f"  {yr:<6}"
        for strat in strategies:
            t = strat_trades[(yr, strat)]
            if not t:
                row += f"{'—':>10}"
            else:
                total = sum(x['pnl'] for x in t)
                sign = '+' if total >= 0 else ''
                row += f"{sign+'£'+f'{abs(total):.0f}':>10}" if total >= 0 else f"{'-£'+f'{abs(total):.0f}':>10}"
        print(row)

    # Consistency analysis
    print(f"\n{'='*W}")
    print("  CONSISTENCY ANALYSIS")
    print("="*W)
    year_totals = [sum(t['pnl'] for t in by_year[yr]) for yr in years if by_year[yr]]
    if len(year_totals) >= 3:
        best  = max(year_totals); worst = min(year_totals)
        avg   = np.mean(year_totals); std  = np.std(year_totals)
        print(f"\n  Best year:   £{best:,.0f}")
        print(f"  Worst year:  £{worst:,.0f}")
        print(f"  Average/yr:  £{avg:,.0f}")
        print(f"  Std dev/yr:  £{std:,.0f}  (lower = more consistent)")
        cv = std / avg * 100 if avg > 0 else 999
        verdict = ('Very consistent ✅' if cv < 50 else
                   'Moderate variance ⚠ ' if cv < 100 else
                   'High variance ❌')
        print(f"  Coeff of var: {cv:.0f}%  →  {verdict}")

        # Check for decay
        first_half = year_totals[:len(year_totals)//2]
        second_half = year_totals[len(year_totals)//2:]
        print(f"\n  First half avg:  £{np.mean(first_half):,.0f}/yr")
        print(f"  Second half avg: £{np.mean(second_half):,.0f}/yr")
        if np.mean(second_half) >= np.mean(first_half) * 0.7:
            print(f"  → No significant edge decay ✅")
        else:
            print(f"  → Edge may be weakening ⚠  — monitor closely")
    print()
