"""
backtest_advanced.py  —  Monte Carlo, Walk-Forward & Stress Test Suite
=======================================================================
Full validation of the 10kbotV3 8-strategy portfolio.

Run: pip install pandas numpy && python backtest_advanced.py
"""

import pandas as pd
import numpy as np
import os
import warnings
from collections import defaultdict
warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
ACCOUNT        = 70_000
COST_SCALE     = 1.5
TRAIL          = 0.10
MC_SIMS        = 5_000
FTMO_TARGET    = 7_000    # Phase 1: +10% = £7,000
FTMO_DAILY_LIM = 3_500    # Phase 1: max daily loss £3,500
FTMO_TOTAL_LIM = 7_000    # Phase 1: max total drawdown from £70k

# Edit this to reflect today's actual net profit on the challenge:
CURRENT_PROFIT = 1_183    # £71,183 balance after Monday's DAX loss

# ── Data Loading ─────────────────────────────────────────────────────────────
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
    return (run_orb('DAX',    'DAX_ORB', 8,  9, 12, 30,  300, 0.0075, 0.07) +
            run_orb('NAS100', 'NAS_ORB',13, 14, 16, 50, 1500, 0.0075, 0.06, {0,2,4}) +
            run_orb('SP500',  'SP5_ORB',13, 14, 16,  5,  300, 0.004,  0.06, {0}) +
            run_lc('EURUSD', 'LC_EUR',  0.0020, 0.004, 0.08) +
            run_lc('GBPUSD', 'LC_GBP',  0.0025, 0.004, 0.08) +
            run_lc('DAX',    'LC_DAX',  30.0,   0.0075,0.07) +
            run_lc('UK100',  'LC_UK',   30.0,   0.0075,0.07) +
            run_lc('GOLD',   'LC_GOLD', 8.0,    0.004, 0.08))

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_daily_pnls(trades):
    by_date = defaultdict(float)
    for t in trades:
        by_date[t['date']] += t['pnl']
    return [(d, by_date[d]) for d in sorted(by_date.keys())]

def pf_wr_mo(arr, months):
    wins = arr[arr > 5]; loss = arr[arr < -5]
    if len(loss) == 0 or loss.sum() == 0: pf = 99.0
    else: pf = wins.sum() / abs(loss.sum())
    wr = len(wins) / len(arr) * 100
    mo = arr.sum() / months if months > 0 else 0
    return round(pf,2), round(wr,1), round(mo,0)

W = 72

# ── Section 1: Monte Carlo ────────────────────────────────────────────────────
def run_monte_carlo(daily_pnls, n=MC_SIMS, start_equity=ACCOUNT, label="Base Case"):
    print(f"\n{'='*W}")
    print(f"  MONTE CARLO — {label}")
    print(f"  {n:,} iterations | Start: £{start_equity:,.0f} | Target: +£{FTMO_TARGET:,}")
    print(f"  Daily limit: -£{FTMO_DAILY_LIM:,} | Total limit: -£{FTMO_TOTAL_LIM:,}")
    print(f"{'='*W}")

    pnl_arr = np.array([p for _, p in daily_pnls])
    rng = np.random.default_rng(42)

    outcomes, days_list, dd_list = [], [], []

    for _ in range(n):
        shuffled = rng.permutation(pnl_arr)
        equity = start_equity
        peak   = equity
        max_dd = 0
        outcome = 'timeout'
        day_n   = 0

        for i, dpnl in enumerate(shuffled):
            day_n = i + 1
            if dpnl < -FTMO_DAILY_LIM:
                outcome = 'daily_breach'; break
            equity += dpnl
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if equity < ACCOUNT - FTMO_TOTAL_LIM:
                outcome = 'total_breach'; break
            if equity >= ACCOUNT + FTMO_TARGET:
                outcome = 'pass'; break

        outcomes.append(outcome)
        days_list.append(day_n)
        dd_list.append(max_dd)

    outcomes = np.array(outcomes)
    days_arr = np.array(days_list)
    dd_arr   = np.array(dd_list)

    pass_m  = outcomes == 'pass'
    daily_m = outcomes == 'daily_breach'
    total_m = outcomes == 'total_breach'
    time_m  = outcomes == 'timeout'

    print(f"\n  OUTCOME PROBABILITIES ({n:,} simulations)")
    print(f"  {'✅ Pass target:':<35} {pass_m.sum()/n*100:>6.1f}%  ({pass_m.sum():,})")
    print(f"  {'❌ Daily loss breach:':<35} {daily_m.sum()/n*100:>6.1f}%  ({daily_m.sum():,})")
    print(f"  {'❌ Total loss breach:':<35} {total_m.sum()/n*100:>6.1f}%  ({total_m.sum():,})")
    print(f"  {'⏱  Timed out (ran out of data):':<35} {time_m.sum()/n*100:>6.1f}%  ({time_m.sum():,})")

    if pass_m.sum() > 0:
        pd_ = days_arr[pass_m]
        print(f"\n  TRADING DAYS TO PASS (passing simulations only)")
        print(f"  {'Fastest (10th pct):':<30} {np.percentile(pd_,10):.0f} days  (~{np.percentile(pd_,10)/21*4.3:.1f} weeks)")
        print(f"  {'Median:':<30} {np.median(pd_):.0f} days  (~{np.median(pd_)/21*4.3:.1f} weeks)")
        print(f"  {'Slow (90th pct):':<30} {np.percentile(pd_,90):.0f} days  (~{np.percentile(pd_,90)/21*4.3:.1f} weeks)")

    print(f"\n  MAX DRAWDOWN DISTRIBUTION")
    print(f"  {'Median:':<30} £{np.median(dd_arr):,.0f}")
    print(f"  {'90th pct:':<30} £{np.percentile(dd_arr,90):,.0f}")
    print(f"  {'Worst seen:':<30} £{dd_arr.max():,.0f}")

    return pass_m.sum() / n

# ── Section 2: Current State MC (bootstrap) ───────────────────────────────────
def run_current_state_mc(daily_pnls, current_profit=CURRENT_PROFIT, n=MC_SIMS):
    current_equity = ACCOUNT + current_profit
    print(f"\n{'='*W}")
    print(f"  MONTE CARLO — CURRENT STATE (bootstrap from historical distribution)")
    print(f"  Already at: £{current_equity:,.0f}  (+£{current_profit:,})")
    print(f"  Still need: +£{FTMO_TARGET - current_profit:,} to pass")
    print(f"{'='*W}")

    pnl_arr = np.array([p for _, p in daily_pnls])
    rng = np.random.default_rng(77)

    outcomes, days_list = [], []

    for _ in range(n):
        # Bootstrap: sample with replacement (we don't know which future days come)
        sampled = rng.choice(pnl_arr, size=len(pnl_arr), replace=True)
        equity  = current_equity
        outcome = 'timeout'
        day_n   = 0

        for i, dpnl in enumerate(sampled):
            day_n = i + 1
            if dpnl < -FTMO_DAILY_LIM:
                outcome = 'daily_breach'; break
            equity += dpnl
            if equity < ACCOUNT - FTMO_TOTAL_LIM:
                outcome = 'total_breach'; break
            if equity >= ACCOUNT + FTMO_TARGET:
                outcome = 'pass'; break

        outcomes.append(outcome)
        days_list.append(day_n)

    outcomes = np.array(outcomes)
    days_arr = np.array(days_list)
    pass_m   = outcomes == 'pass'

    print(f"\n  {'✅ Pass probability:':<35} {pass_m.sum()/n*100:.1f}%")
    print(f"  {'❌ Daily breach probability:':<35} {(outcomes=='daily_breach').sum()/n*100:.1f}%")
    print(f"  {'❌ Total breach probability:':<35} {(outcomes=='total_breach').sum()/n*100:.1f}%")

    if pass_m.sum() > 0:
        pd_ = days_arr[pass_m]
        print(f"\n  ADDITIONAL TRADING DAYS NEEDED FROM HERE")
        print(f"  {'Fastest (10th pct):':<30} {np.percentile(pd_,10):.0f} days  (~{np.percentile(pd_,10)/21*4.3:.1f} weeks)")
        print(f"  {'Median:':<30} {np.median(pd_):.0f} days  (~{np.median(pd_)/21*4.3:.1f} weeks)")
        print(f"  {'Slow (90th pct):':<30} {np.percentile(pd_,90):.0f} days  (~{np.percentile(pd_,90)/21*4.3:.1f} weeks)")

# ── Section 3: Walk-Forward ───────────────────────────────────────────────────
def run_walk_forward(all_trades):
    print(f"\n{'='*W}")
    print(f"  WALK-FORWARD ANALYSIS")
    print(f"  In-sample: 2018–2021  |  Out-of-sample: 2022–2026")
    print(f"{'='*W}")

    def stats_block(trades, label):
        if not trades:
            print(f"\n  {label}: no data"); return None
        arr   = np.array([t['pnl'] for t in trades])
        wins  = arr[arr > 5]; loss = arr[arr < -5]
        dates = sorted(set(t['date'] for t in trades))
        months = len(set(d[:7] for d in dates))
        span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
        eq    = ACCOUNT + np.cumsum(arr)
        pk    = np.maximum.accumulate(eq)
        dd    = (pk - eq).max()
        pf    = round(wins.sum()/abs(loss.sum()),2) if len(loss) and loss.sum()!=0 else 99.0
        wr    = round(len(wins)/len(arr)*100,1)
        mo    = round(arr.sum()/months,0)
        print(f"\n  {label}")
        print(f"  {'Trades:':<22} {len(arr)}")
        print(f"  {'Win rate:':<22} {wr}%")
        print(f"  {'Profit factor:':<22} {pf}")
        print(f"  {'Monthly avg P&L:':<22} £{mo:,.0f}")
        print(f"  {'Max drawdown:':<22} £{dd:,.0f}")
        return {'pf':pf,'wr':wr,'mo':mo,'dd':dd}

    is_t  = [t for t in all_trades if t['date'][:4] <= '2021']
    oos_t = [t for t in all_trades if t['date'][:4] >= '2022']

    s1 = stats_block(is_t,  "IN-SAMPLE (2018-2021) — training data")
    s2 = stats_block(oos_t, "OUT-OF-SAMPLE (2022-2026) — never seen")

    if s1 and s2:
        print(f"\n  DEGRADATION CHECK  (>40% drop = concern)")
        def chk(name, v1, v2, fmt=''):
            chg = (v2-v1)/v1*100 if v1 != 0 else 0
            flag = '✅' if abs(chg) < 20 else ('⚠ ' if abs(chg) < 40 else '❌')
            print(f"  {name:<22} {v1}{fmt} → {v2}{fmt}  ({chg:+.1f}%)  {flag}")
        chk('Profit factor:',   s1['pf'],  s2['pf'])
        chk('Win rate:',        s1['wr'],  s2['wr'],  '%')
        chk('Monthly avg:',    f"£{s1['mo']:,.0f}", f"£{s2['mo']:,.0f}")

        if s2['pf'] >= 1.5:
            print(f"\n  → Edge holds strongly out-of-sample ✅")
        elif s2['pf'] >= 1.0:
            print(f"\n  → Some degradation but still profitable out-of-sample ⚠")
        else:
            print(f"\n  → Significant degradation — review strategy ❌")

    # Rolling walk-forward (1-year OOS windows)
    print(f"\n  ROLLING WALK-FORWARD  (train on 3 yrs, test on next 1 yr)")
    print(f"  {'Window':<18} {'OOS PF':>8} {'OOS WR%':>9} {'OOS £/mo':>10}  {'Verdict'}")
    print(f"  {'─'*58}")

    years = sorted(set(t['date'][:4] for t in all_trades))
    for i in range(3, len(years)):
        oos_yr  = years[i]
        is_yrs  = years[max(0,i-3):i]
        is_t2   = [t for t in all_trades if t['date'][:4] in is_yrs]
        oos_t2  = [t for t in all_trades if t['date'][:4] == oos_yr]
        if len(oos_t2) < 10: continue
        oos_arr = np.array([t['pnl'] for t in oos_t2])
        months  = len(set(t['date'][:7] for t in oos_t2))
        w = oos_arr[oos_arr>5]; l = oos_arr[oos_arr<-5]
        pf = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 99.0
        wr = round(len(w)/len(oos_arr)*100,1)
        mo = round(oos_arr.sum()/months,0)
        flag = '✅' if pf >= 1.5 else ('⚠ ' if pf >= 1.0 else '❌')
        train = f"{is_yrs[0]}-{is_yrs[-1]}"
        print(f"  Train {train} → Test {oos_yr}   {pf:>6.2f}   {wr:>6.1f}%  £{mo:>7,.0f}  {flag}")

# ── Section 4: Stress Tests ───────────────────────────────────────────────────
def run_stress_tests(all_trades):
    print(f"\n{'='*W}")
    print(f"  STRESS TEST SUITE  (what breaks the system?)")
    print(f"{'='*W}")

    arr    = np.array([t['pnl'] for t in all_trades])
    months = len(set(t['date'][:7] for t in all_trades))
    rng    = np.random.default_rng(42)

    # Build best-year label
    by_year = defaultdict(list)
    for i, t in enumerate(all_trades): by_year[t['date'][:4]].append(i)
    yr_totals = {yr: sum(all_trades[i]['pnl'] for i in idx) for yr, idx in by_year.items()}
    best_yr   = max(yr_totals, key=yr_totals.get)

    scenarios = []

    # Base
    scenarios.append(('Base case (actual backtest)', arr.copy()))

    # Win rate -10%
    a = arr.copy()
    win_idx = np.where(a > 5)[0]
    flip    = rng.choice(win_idx, size=int(len(win_idx)*0.10), replace=False)
    a[flip] = -abs(a[flip]) * 0.8
    scenarios.append(('Win rate -10%', a))

    # Avg win -20%
    a = arr.copy(); a[a > 5] *= 0.80
    scenarios.append(('Average win reduced 20%', a))

    # Avg loss +20%
    a = arr.copy(); a[a < -5] *= 1.20
    scenarios.append(('Average loss increased 20%', a))

    # Combined moderate stress
    a = arr.copy(); a[a > 5] *= 0.85; a[a < -5] *= 1.15
    scenarios.append(('Moderate stress (wins -15%, losses +15%)', a))

    # Severe stress
    a = arr.copy(); a[a > 5] *= 0.70; a[a < -5] *= 1.30
    scenarios.append(('Severe stress (wins -30%, losses +30%)', a))

    # Remove best year
    bad = set(by_year[best_yr])
    a   = np.array([t['pnl'] for i,t in enumerate(all_trades) if i not in bad])
    scenarios.append((f'Remove best year ({best_yr})', a))

    print(f"\n  {'Scenario':<44} {'PF':>6} {'WR%':>6} {'£/mo':>8}  Verdict")
    print(f"  {'─'*70}")

    for label, a in scenarios:
        wins = a[a > 5]; loss = a[a < -5]
        pf   = round(wins.sum()/abs(loss.sum()),2) if len(loss) and loss.sum()!=0 else 99.0
        wr   = round(len(wins)/len(a)*100,1)
        mo   = round(a.sum()/months,0)
        v    = ('✅ Strong' if pf >= 1.5 else
                '⚠  Marginal' if pf >= 1.2 else
                '⚠  Barely profitable' if pf >= 1.0 else
                '❌ Unprofitable')
        print(f"  {label:<44} {pf:>6.2f} {wr:>5.1f}% £{mo:>6,.0f}  {v}")

    # Find break-even point
    print(f"\n  BREAK-EVEN SENSITIVITY")
    print(f"  How much do wins need to shrink before system goes negative?")
    for pct in range(5, 55, 5):
        a = arr.copy(); a[a > 5] *= (1 - pct/100)
        wins = a[a > 5]; loss = a[a < -5]
        pf = wins.sum()/abs(loss.sum()) if len(loss) and loss.sum()!=0 else 99.0
        mo = a.sum()/months
        if pf < 1.0:
            print(f"  System goes negative at wins reduced by {pct}%  (PF drops to {pf:.2f})")
            break
        elif pct >= 50:
            print(f"  System stays positive even with wins reduced 50% ✅")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print("\n" + "="*W)
    print("  10kbotV3 — FULL VALIDATION SUITE")
    print("  Monte Carlo | Walk-Forward | Stress Tests | Current State")
    print("="*W)

    print("\n  Loading data and running all strategies...")
    for k in CSVSYMS: load_h1(k)
    all_trades  = run_all()
    daily_pnls  = get_daily_pnls(all_trades)
    total_months = len(set(t['date'][:7] for t in all_trades))

    print(f"  Total trades:       {len(all_trades)}")
    print(f"  Total trading days: {len(daily_pnls)}")
    print(f"  Total months:       {total_months}")

    # Overall stats
    arr  = np.array([t['pnl'] for t in all_trades])
    wins = arr[arr>5]; loss = arr[arr<-5]
    pf   = wins.sum()/abs(loss.sum())
    wr   = len(wins)/len(arr)*100
    mo   = arr.sum()/total_months
    eq   = ACCOUNT + np.cumsum(arr)
    pk   = np.maximum.accumulate(eq)
    dd   = (pk-eq).max()
    print(f"\n  OVERALL: WR={wr:.1f}%  PF={pf:.2f}  £/mo={mo:,.0f}  MaxDD=£{dd:,.0f}")

    # Run all sections
    run_monte_carlo(daily_pnls, label="Full Historical Data")
    run_current_state_mc(daily_pnls, current_profit=CURRENT_PROFIT)
    run_walk_forward(all_trades)
    run_stress_tests(all_trades)

    print(f"\n{'='*W}")
    print("  DONE")
    print(f"{'='*W}\n")
