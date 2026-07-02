"""
backtest_montecarlo.py  —  Monte Carlo + Rolling 12-Month PF
=============================================================
Two analyses in one script:

1. MONTE CARLO (2,000 simulations)
   Shuffles trade order randomly to model luck vs skill.
   Answers:
   - What's the probability of passing the FTMO challenge?
   - What's the probability of busting the funded account?
   - What's the realistic worst-case drawdown?
   - How long should it take to pass Phase 1?

2. ROLLING 12-MONTH PF
   Slides a 12-month window across all 8 years month by month.
   Shows whether the edge is stable, growing, or decaying over time.
   This directly answers the "is the strategy losing its edge?" concern.

Run: python backtest_montecarlo.py
"""
import pandas as pd
import numpy as np
import os
import warnings
from collections import defaultdict
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

def run_lc(key, tag, min_move, risk, cost):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        ob  = df[df.index == day+pd.Timedelta(hours=7)]
        cb  = df[df.index == day+pd.Timedelta(hours=15)]
        if len(ob)==0 or len(cb)==0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue
        sess = df[(df.index >= day+pd.Timedelta(hours=7)) &
                  (df.index <= day+pd.Timedelta(hours=16))]
        if len(sess)==0: continue
        dh = sess['high'].max(); dl = sess['low'].min(); buf = (dh-dl)*0.03
        p  = ipos(df, day+pd.Timedelta(hours=16))
        if p < 0: continue
        entry = df.iloc[p]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d==-1 and sl<=entry: continue
        if d==1  and sl>=entry: continue
        r = sim(df, p, d, entry, sl)
        trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r})
    return trades

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, cost, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb  = df[df.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb)==0: continue
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
                r = sim(df, p,-1, rlo, rhi)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
    return trades

def run_all():
    return (run_orb('DAX',   'DAX_ORB', 8, 9,12, 30, 300,  0.0075,0.07) +
            run_orb('NAS100','NAS_ORB',13,14,16, 50,1500,  0.0075,0.06, {0,2,4}) +
            run_orb('SP500', 'SP5_ORB',13,14,16,  5, 300,  0.004, 0.06, {0}) +
            run_lc('EURUSD','LC_EUR',0.0020,0.004,0.08) +
            run_lc('GBPUSD','LC_GBP',0.0025,0.004,0.08) +
            run_lc('DAX',   'LC_DAX',30.0, 0.0075,0.07) +
            run_lc('UK100', 'LC_UK', 30.0, 0.0075,0.07) +
            run_lc('GOLD',  'LC_GOLD',8.0, 0.004, 0.08))

# ── Monte Carlo ───────────────────────────────────────────────────────────────
def monte_carlo(trades, n_sims=2000, seed=42):
    np.random.seed(seed)
    arr = np.array([t['pnl'] for t in trades])

    # FTMO levels
    TARGET  = ACCOUNT * 1.10   # £77,000 — challenge pass
    BUST    = ACCOUNT * 0.90   # £63,000 — funded account bust
    DAILY_CB = ACCOUNT * 0.035  # £2,450 — our circuit breaker

    max_dds   = np.zeros(n_sims)
    finals    = np.zeros(n_sims)
    busted    = np.zeros(n_sims, dtype=bool)
    passed    = np.zeros(n_sims, dtype=bool)
    pass_n    = []

    # Group trades by date to preserve within-day correlations when shuffling
    by_day = defaultdict(list)
    for t in sorted(trades, key=lambda x: x['date']):
        by_day[t['date']].append(t['pnl'])
    days = list(by_day.keys())
    day_pnls = [np.array(by_day[d]) for d in days]

    for i in range(n_sims):
        idx = np.random.permutation(len(day_pnls))
        eq = ACCOUNT; peak = ACCOUNT; max_dd = 0.0; n_trades = 0
        sim_passed = sim_busted = False

        for di in idx:
            day_arr = day_pnls[di]
            day_total = day_arr.sum()
            # Apply daily circuit breaker: cap single-day loss
            if day_total < -DAILY_CB:
                day_total = -DAILY_CB
            eq += day_total
            n_trades += len(day_arr)

            if eq > peak: peak = eq
            dd = peak - eq
            if dd > max_dd: max_dd = dd

            if not sim_passed and eq >= TARGET:
                sim_passed = True
                passed[i]  = True
                pass_n.append(n_trades)
            if not sim_busted and eq <= BUST:
                sim_busted = True
                busted[i]  = True

        max_dds[i] = max_dd
        finals[i]  = eq

    trades_per_month = len(arr) / max(
        (pd.Timestamp(max(t['date'] for t in trades)) -
         pd.Timestamp(min(t['date'] for t in trades))).days, 1) * 21

    return {
        'max_dds': max_dds, 'finals': finals,
        'p_pass': passed.mean(), 'p_bust': busted.mean(),
        'pass_n': np.array(pass_n) if pass_n else np.array([len(arr)]),
        'tpm': trades_per_month, 'n_sims': n_sims,
    }

# ── Rolling PF ────────────────────────────────────────────────────────────────
def rolling_pf(trades, months=12):
    srt = sorted(trades, key=lambda t: t['date'])
    if not srt: return []
    t0  = pd.Timestamp(srt[0]['date'],  tz='UTC')
    t1  = pd.Timestamp(srt[-1]['date'], tz='UTC')
    out = []
    cur = t0 + pd.DateOffset(months=months)
    while cur <= t1 + pd.DateOffset(days=1):
        w0  = cur - pd.DateOffset(months=months)
        win = [t for t in srt
               if w0 <= pd.Timestamp(t['date'], tz='UTC') < cur]
        if len(win) >= 20:
            arr  = np.array([t['pnl'] for t in win])
            wins = arr[arr > 5]; loss = arr[arr < -5]
            pf   = round(wins.sum()/abs(loss.sum()), 2) if len(loss) and loss.sum()!=0 else 0.0
            mo   = round(arr.sum()/months, 0)
            out.append({'month': cur.strftime('%Y-%m'), 'pf': pf, 'mo': mo, 'n': len(win)})
        cur += pd.DateOffset(months=1)
    return out

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 72
    print("\n" + "="*W)
    print("  MONTE CARLO + ROLLING 12-MONTH PF")
    print("  2,000 simulations | 8-year dataset | £70,000 starting balance")
    print("="*W)

    for k in CSVSYMS: load_h1(k)
    print("\n  Loading trades...")
    all_trades = run_all()
    print(f"  {len(all_trades)} trades | {len(set(t['date'] for t in all_trades))} trading days\n")

    # ── Monte Carlo ───────────────────────────────────────────────────────────
    print("="*W)
    print("  MONTE CARLO  —  shuffles trade ORDER, keeps daily groupings")
    print("  Daily circuit breaker (3.5% = £2,450) applied each simulation")
    print("="*W)

    print("\n  Running 2,000 simulations...", end='', flush=True)
    mc = monte_carlo(all_trades, n_sims=2000)
    print(" done.\n")

    dds = mc['max_dds']; finals = mc['finals']

    print("  DRAWDOWN DISTRIBUTION (across all simulations):")
    print(f"  Best case   (5th pct):   £{np.percentile(dds,  5):>8,.0f}")
    print(f"  Typical     (50th pct):  £{np.percentile(dds, 50):>8,.0f}")
    print(f"  Bad case    (95th pct):  £{np.percentile(dds, 95):>8,.0f}")
    print(f"  Worst case  (99th pct):  £{np.percentile(dds, 99):>8,.0f}")
    print(f"  ─────────────────────────────────────────")
    print(f"  FTMO max loss limit:     £{7_000:>8,}  (never go below £63,000)")
    p7  = (dds > 7_000).mean()*100
    p10 = (dds > 10_000).mean()*100
    verdict7  = '✅ low risk' if p7  < 5  else ('⚠  moderate' if p7  < 15 else '❌ HIGH')
    verdict10 = '✅ low risk' if p10 < 5  else ('⚠  moderate' if p10 < 15 else '❌ HIGH')
    print(f"\n  P(ever hit £7k DD):      {p7:>5.1f}%  {verdict7}")
    print(f"  P(ever hit £10k DD):     {p10:>5.1f}%  {verdict10}")

    print(f"\n  FTMO CHALLENGE — Phase 1: +10% target before -10% bust")
    p_pass = mc['p_pass']*100; p_bust = mc['p_bust']*100
    vp = '✅' if p_pass > 70 else ('⚠ ' if p_pass > 50 else '❌')
    vb = '✅' if p_bust < 5  else ('⚠ ' if p_bust < 15 else '❌')
    print(f"  P(pass challenge):       {p_pass:>5.1f}%  {vp}")
    print(f"  P(bust funded account):  {p_bust:>5.1f}%  {vb}")

    if len(mc['pass_n']) > 0:
        med_n = np.median(mc['pass_n'])
        med_m = med_n / mc['tpm']
        p25_m = np.percentile(mc['pass_n'], 25) / mc['tpm']
        p75_m = np.percentile(mc['pass_n'], 75) / mc['tpm']
        print(f"\n  TIME TO PASS CHALLENGE (among simulations that passed):")
        print(f"  Median:  {med_n:.0f} trades  ≈  {med_m:.1f} months")
        print(f"  Fast 25%: under {p25_m:.1f} months")
        print(f"  Slow 25%: over  {p75_m:.1f} months")
        print(f"  (Trades/month: {mc['tpm']:.0f})")

    print(f"\n  FINAL BALANCE DISTRIBUTION (after {len(all_trades)} trades in random order):")
    for pct in [5, 25, 50, 75, 95]:
        f = np.percentile(finals, pct)
        print(f"  {pct:>3}th pct:  £{f:>10,.0f}  ({(f/ACCOUNT-1)*100:>+6.1f}%)")

    # ── Rolling PF ────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  ROLLING 12-MONTH PF  —  one row per month, 12-month lookback")
    print("  Shows edge stability. A DECLINING trend = edge decaying.")
    print("  Stable within ±0.3 of average = normal variance, not decay.")
    print(f"{'='*W}\n")

    rolling = rolling_pf(all_trades, months=12)

    if rolling:
        pf_vals = [r['pf'] for r in rolling]
        avg_pf  = np.mean(pf_vals)

        print(f"  {'Month':<9} {'PF':>6}  {'vs avg':>7}  {'£/mo':>9}  {'N':>5}  Chart")
        print("  " + "─"*60)
        for r in rolling:
            delta = r['pf'] - avg_pf
            bar   = '█' * max(0, int(r['pf'] * 6)) + ('░' * max(0, 12 - int(r['pf'] * 6)))
            ok    = '✅' if r['pf'] >= 1.6 else ('⚠ ' if r['pf'] >= 1.2 else '❌')
            print(f"  {r['month']:<9} {r['pf']:>6.2f}  {delta:>+7.2f}  "
                  f"£{r['mo']:>8,.0f}  {r['n']:>5}  {bar} {ok}")

        print(f"\n  PF range:       {min(pf_vals):.2f} — {max(pf_vals):.2f}")
        print(f"  Average PF:     {avg_pf:.2f}")
        print(f"  Std deviation:  {np.std(pf_vals):.2f}")

        # Trend: linear regression slope
        x = np.arange(len(pf_vals))
        slope, intercept = np.polyfit(x, pf_vals, 1)
        annual_drift = slope * 12
        print(f"\n  Trend (linear slope): {slope:+.4f} per month  "
              f"({annual_drift:+.2f} PF per year)")
        if abs(annual_drift) < 0.10:
            print(f"  → Edge is STABLE ✅  (drift <0.10 PF/year is noise)")
        elif annual_drift < -0.10:
            print(f"  → Edge is DECLINING ⚠   ({annual_drift:.2f} PF/year) — monitor closely")
        else:
            print(f"  → Edge is GROWING ✅  ({annual_drift:+.2f} PF/year)")

        # Period comparison
        n = len(pf_vals)
        early = np.mean(pf_vals[:n//3])
        mid   = np.mean(pf_vals[n//3: 2*n//3])
        late  = np.mean(pf_vals[2*n//3:])
        print(f"\n  Period breakdown:")
        print(f"  Early third avg PF:   {early:.2f}")
        print(f"  Middle third avg PF:  {mid:.2f}")
        print(f"  Recent third avg PF:  {late:.2f}")
        if late >= early * 0.85:
            print(f"  → No meaningful decay between early and recent periods ✅")
        else:
            print(f"  → Recent PF is {(late/early-1)*100:.0f}% lower than early period ⚠")

    print()
