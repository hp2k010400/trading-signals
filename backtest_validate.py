"""
backtest_validate.py — Full validation of new portfolio
Validates LC strategies + optimised ORB portfolio before going live.

New portfolio:
  DAX_ORB  — as-is                (PF 1.88)
  SP5_ORB  — as-is                (PF 1.52)
  NAS_ORB  — Tue/Thu only         (bad PF on Wed/Fri)
  LC_EUR   — London Close fade    (PF 2.46)
  LC_GBP   — London Close fade    (PF 1.94)
  LC_DAX   — London Close fade    (PF 1.90)

Outputs:
  A. Per-strategy stats (full 8 years)
  B. Walk-forward IS vs OOS for each strategy
  C. Rolling walk-forward (6 splits)
  D. Quarterly breakdown — consistency check
  E. Monthly P&L chart
  F. Monthly distribution
  G. FTMO Monte Carlo (10,000 sims, no time limit)
  H. New instrument candidates (export these from MT5 next)

Run: python backtest_validate.py
"""

import pandas as pd
import numpy as np
import warnings
import os
from dataclasses import dataclass
from collections import defaultdict

warnings.filterwarnings('ignore')

ACCOUNT    = 70_000
TRAIL_ORB  = 0.10
COST_SCALE = 1.5
WF_SPLIT   = pd.Timestamp('2025-01-01', tz='UTC')

RISKS = {
    'DAX_ORB':  0.0075, 'NAS_ORB':  0.0075, 'SP5_ORB':  0.004,
    'LC_EUR':   0.004,  'LC_GBP':   0.004,  'LC_DAX':   0.0075,
    'UK_ORB':   0.0075, 'LC_UK':    0.0075,
    'GOLD_ORB': 0.004,  'LC_GOLD':  0.004,
    'JPY_ORB':  0.004,  'ASIA_JPY': 0.004,
}
COST_R_BASE = {
    'DAX_ORB':  0.07,  'NAS_ORB':  0.06,  'SP5_ORB':  0.06,
    'LC_EUR':   0.08,  'LC_GBP':   0.08,  'LC_DAX':   0.07,
    'UK_ORB':   0.07,  'LC_UK':    0.07,
    'GOLD_ORB': 0.08,  'LC_GOLD':  0.08,
    'JPY_ORB':  0.08,  'ASIA_JPY': 0.08,
}
CSVSYMS = {
    'EURUSD':  'EURUSD_H1.csv',    'GBPUSD':  'GBPUSD_H1.csv',
    'DAX':     'GER40_cash_H1.csv','NAS100':  'US100_cash_H1.csv',
    'SP500':   'US500_cash_H1.csv',
    'UK100':   'UK100_cash_H1.csv',
    'GOLD':    'XAUUSD_H1.csv',
    'USDJPY':  'USDJPY_H1.csv',
}

_cache = {}

@dataclass
class Trade:
    date: str
    pnl_raw: float
    tag: str
    dow: int

# ── Data ──────────────────────────────────────────────────────────────────────
def load_h1(key):
    if key in _cache: return _cache[key]
    fname = CSVSYMS.get(key)
    if not fname or not os.path.exists(fname):
        _cache[key] = None; return None
    df = pd.read_csv(fname)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time')[['open','high','low','close']].dropna()
    _cache[key] = df if len(df) > 200 else None
    return _cache[key]

# ── Core sim ──────────────────────────────────────────────────────────────────
def sim(df, ep, direction, entry, sl, max_bars=48):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0
    trail = sl_d * TRAIL_ORB; cur_sl = sl; best = entry; be = False
    last_px = entry
    for _, b in df.iloc[ep+1 : ep+1+max_bars].iterrows():
        last_px = b['close']
        if direction == 1:
            if b['low'] <= cur_sl: return (cur_sl - entry) / sl_d
            best = max(best, b['high'])
            if not be and best >= entry + sl_d: be = True; cur_sl = entry
            if be:
                ns = best - trail
                if ns > cur_sl: cur_sl = ns
        else:
            if b['high'] >= cur_sl: return (entry - cur_sl) / sl_d
            best = min(best, b['low'])
            if not be and best <= entry - sl_d: be = True; cur_sl = entry
            if be:
                ns = best + trail
                if ns < cur_sl: cur_sl = ns
    return ((last_px - entry) if direction == 1 else (entry - last_px)) / sl_d

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    if a >= len(df): return -1
    return int(a) if df.index[int(a)] == ts else -1

def make_trade(df, ep, direction, entry, sl, tag, ds, dow):
    r = sim(df, ep, direction, entry, sl)
    return Trade(date=ds, pnl_raw=r * RISKS[tag] * ACCOUNT, tag=tag, dow=dow)

def net(t):
    return t.pnl_raw - COST_R_BASE[t.tag] * COST_SCALE * RISKS[t.tag] * ACCOUNT

# ── Stats ─────────────────────────────────────────────────────────────────────
def stats(trades, date_from=None, date_to=None):
    if date_from: trades = [t for t in trades if t.date >= str(date_from.date())]
    if date_to:   trades = [t for t in trades if t.date <  str(date_to.date())]
    if not trades or len(trades) < 20: return None
    arr  = np.array([net(t) for t in trades])
    wins = arr[arr > 5]; loss = arr[arr < -5]
    dates = sorted(set(t.date for t in trades))
    span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    return {
        'n':   len(arr),
        'wr':  round(len(wins) / len(arr) * 100, 1),
        'pf':  round(wins.sum() / abs(loss.sum()), 2) if len(loss) else 0.0,
        'mo':  round(arr.sum() / span * 21, 0),
        'tpm': round(len(arr) / span * 21, 1),
        'arr': arr,
        'dates': dates,
    }

def sharpe(trades, date_from=None, date_to=None):
    if date_from: trades = [t for t in trades if t.date >= str(date_from.date())]
    if date_to:   trades = [t for t in trades if t.date <  str(date_to.date())]
    by_day = defaultdict(float)
    for t in trades: by_day[t.date] += net(t)
    daily = np.array(list(by_day.values()))
    if len(daily) < 10 or daily.std() == 0: return 0.0
    return round((daily.mean() / daily.std()) * (252 ** 0.5), 2)

def max_drawdown(trades):
    arr    = np.array([net(t) for t in sorted(trades, key=lambda x: x.date)])
    equity = ACCOUNT + np.cumsum(arr)
    peak   = np.maximum.accumulate(equity)
    dd     = peak - equity
    if dd.max() == 0: return 0.0, 0.0
    return round(dd.max(), 0), round(dd.max() / peak[np.argmax(dd)] * 100, 2)

# ── Strategy runners ──────────────────────────────────────────────────────────
def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=frozenset()):
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
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                trades.append(make_trade(df, p, 1,  rhi, rlo, tag, ds, day.dayofweek)); break
            if b['low']  < rlo:
                trades.append(make_trade(df, p, -1, rlo, rhi, tag, ds, day.dayofweek)); break
    return trades

def run_london_close(key, tag, min_move):
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
        day_df   = df[(df.index >= day + pd.Timedelta(hours=7)) &
                      (df.index <= day + pd.Timedelta(hours=16))]
        if len(day_df) == 0: continue
        day_high = day_df['high'].max()
        day_low  = day_df['low'].min()
        buf      = (day_high - day_low) * 0.03
        entry_df = df[df.index == day + pd.Timedelta(hours=16)]
        if len(entry_df) == 0: continue
        p     = ipos(df, day + pd.Timedelta(hours=16))
        entry = entry_df.iloc[0]['open']
        ds    = str(date)
        if move > min_move:
            sl = day_high + buf
            if sl <= entry: continue
            trades.append(make_trade(df, p, -1, entry, sl, tag, ds, day.dayofweek))
        else:
            sl = day_low - buf
            if sl >= entry: continue
            trades.append(make_trade(df, p, 1, entry, sl, tag, ds, day.dayofweek))
    return trades

# ── FTMO Monte Carlo ──────────────────────────────────────────────────────────
def ftmo_monte_carlo(trades, n_sim=10_000, target=7_000,
                     daily_limit=3_500, total_limit=7_000):
    by_day = defaultdict(float)
    for t in trades: by_day[t.date] += net(t)
    daily_pnls = np.array(list(by_day.values()))
    rng = np.random.default_rng(42)
    pass_c = bust_c = run_c = 0
    for _ in range(n_sim):
        equity = ACCOUNT; peak = ACCOUNT; passed = busted = False
        for dp in rng.choice(daily_pnls, size=500, replace=True):
            if dp < -daily_limit:          busted = True; break
            equity += dp; peak = max(peak, equity)
            if peak - equity > total_limit: busted = True; break
            if equity - ACCOUNT >= target:  passed = True; break
        if   busted: bust_c += 1
        elif passed: pass_c += 1
        else:        run_c  += 1
    return pass_c/n_sim*100, bust_c/n_sim*100, run_c/n_sim*100

# ── Bar chart ─────────────────────────────────────────────────────────────────
def bar_chart(monthly, width=40):
    vals = list(monthly.values())
    if not vals: return
    mx = max(abs(v) for v in vals)
    print()
    for m, v in sorted(monthly.items()):
        bar = ('█' * int(abs(v)/mx*width)) if v >= 0 else ('░' * int(abs(v)/mx*width))
        print(f"  {m}  {'+'if v>=0 else'-'}£{abs(v):>7,.0f}  {bar}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 70

    print("\n" + "=" * W)
    print("  NEW PORTFOLIO VALIDATION  —  8-year MT5 H1 data")
    print("  DAX_ORB · SP5_ORB · NAS_ORB(Tue/Thu) · LC_EUR · LC_GBP · LC_DAX")
    print("=" * W)

    print("\n  Loading data and running strategies...")
    for k in CSVSYMS: load_h1(k)

    # Build portfolio
    strats = {
        'DAX_ORB': run_orb('DAX',    'DAX_ORB', 8,  9, 12,  30,  300),
        'SP5_ORB': run_orb('SP500',  'SP5_ORB', 13, 14, 16,   5,  300, {0}),
        'NAS_ORB': run_orb('NAS100', 'NAS_ORB', 13, 14, 16,  50, 1500, {0, 2, 4}),  # Tue/Thu only
        'LC_EUR':  run_london_close('EURUSD', 'LC_EUR', min_move=0.0020),
        'LC_GBP':  run_london_close('GBPUSD', 'LC_GBP', min_move=0.0025),
        'LC_DAX':  run_london_close('DAX',    'LC_DAX', min_move=30.0),
    }
    all_trades = [t for v in strats.values() for t in v]
    print(f"  Done. Total trades: {len(all_trades):,}\n")

    # ── A. Per-strategy full history ──────────────────────────────────────────
    print("=" * W)
    print("  A. PER-STRATEGY STATS  (full 8 years, 1.5x costs)")
    print("=" * W)
    print(f"\n  {'Strategy':<12} {'Tr':>5} {'T/mo':>5} {'WR%':>6} {'PF':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'£/mo':>8}")
    print("  " + "─" * (W - 2))

    total_mo = 0
    for tag, trades in strats.items():
        s = stats(trades)
        if not s: continue
        arr  = s['arr']
        wins = arr[arr > 5]; loss = arr[arr < -5]
        ok   = '✅' if s['pf'] >= 1.5 else ('⚠ ' if s['pf'] >= 1.2 else '❌')
        aw   = round(wins.mean()) if len(wins) else 0
        al   = round(abs(loss.mean())) if len(loss) else 0
        print(f"  {tag:<12} {s['n']:>5} {s['tpm']:>5.1f} {s['wr']:>5.1f}% "
              f"{s['pf']:>6.2f} £{aw:>6,} £{al:>6,} £{s['mo']:>7,}  {ok}")
        total_mo += s['mo']
    print(f"\n  Portfolio total: £{total_mo:,.0f}/month")

    # ── B. Walk-forward IS vs OOS ─────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  B. WALK-FORWARD  IS (pre-Jan 2025) vs OOS (Jan 2025+)  [1.5x]")
    print("=" * W)
    print(f"\n  {'Strategy':<12} {'IS PF':>7} {'OOS PF':>8} {'Ratio':>7} {'IS £/mo':>9} "
          f"{'OOS £/mo':>9} {'Hold?'}")
    print("  " + "─" * (W - 2))

    all_is = []; all_oos = []
    for tag, trades in strats.items():
        si = stats(trades, date_to=WF_SPLIT)
        so = stats(trades, date_from=WF_SPLIT)
        if not si or not so: continue
        ratio = so['pf'] / si['pf'] * 100
        ok    = '✅' if so['pf'] >= 1.3 else ('⚠ ' if so['pf'] >= 1.1 else '❌')
        print(f"  {tag:<12} {si['pf']:>7.2f} {so['pf']:>8.2f} {ratio:>6.0f}% "
              f"£{si['mo']:>8,} £{so['mo']:>8,}  {ok}")
        all_is  += [t for t in trades if t.date <  str(WF_SPLIT.date())]
        all_oos += [t for t in trades if t.date >= str(WF_SPLIT.date())]

    si = stats(all_is); so = stats(all_oos)
    if si and so:
        ratio = so['pf'] / si['pf'] * 100
        print(f"\n  {'PORTFOLIO':<12} {si['pf']:>7.2f} {so['pf']:>8.2f} {ratio:>6.0f}% "
              f"£{si['mo']:>8,} £{so['mo']:>8,}")
        v = ('✅ HOLDS WELL' if ratio >= 80 else '⚠  MODERATE' if ratio >= 60 else '❌ DEGRADED')
        print(f"\n  OOS/IS ratio: {ratio:.0f}%  →  {v}")
        sh_i = sharpe(all_is); sh_oo = sharpe(all_oos)
        print(f"  Sharpe IS: {sh_i}  |  Sharpe OOS: {sh_oo}")

    # ── C. Rolling walk-forward ───────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  C. ROLLING WALK-FORWARD  (6 splits, 1.5x costs)")
    print("  OOS PF >1.3 across ALL splits = structural edge.")
    print("=" * W)
    print(f"\n  {'Split':<12} {'IS Tr':>7} {'IS PF':>7} {'OOS Tr':>8} {'OOS PF':>8} "
          f"{'Ratio':>7} {'Hold?'}")
    print("  " + "─" * (W - 2))

    splits = ['2022-01-01','2023-01-01','2023-07-01',
              '2024-01-01','2024-07-01','2025-01-01']
    all_pass = True
    for sd in splits:
        sp = pd.Timestamp(sd, tz='UTC')
        si = stats(all_trades, date_to=sp)
        so = stats(all_trades, date_from=sp)
        if not si or not so or si['n'] < 100 or so['n'] < 50:
            print(f"  {sd:<12}  insufficient data"); continue
        ratio = so['pf'] / si['pf'] * 100
        ok    = '✅' if so['pf'] >= 1.3 else ('⚠ ' if so['pf'] >= 1.1 else '❌')
        if so['pf'] < 1.3: all_pass = False
        print(f"  {sd:<12} {si['n']:>7,} {si['pf']:>7.2f} {so['n']:>8,} "
              f"{so['pf']:>8.2f} {ratio:>6.0f}%  {ok}")

    print(f"\n  → {'✅ Edge holds across all splits' if all_pass else '⚠  Some splits show weakness'}")

    # ── D. Quarterly breakdown ────────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  D. QUARTERLY BREAKDOWN  (1.5x costs)")
    print("=" * W)
    print(f"\n  {'Quarter':<14} {'Tr':>5} {'WR%':>6} {'PF':>6} {'£/mo':>8} {'P&L':>9}")
    print("  " + "─" * (W - 2))

    quarters = [
        ('Q1 2022', pd.Timestamp('2022-01-01',tz='UTC'), pd.Timestamp('2022-04-01',tz='UTC')),
        ('Q2 2022', pd.Timestamp('2022-04-01',tz='UTC'), pd.Timestamp('2022-07-01',tz='UTC')),
        ('Q3 2022', pd.Timestamp('2022-07-01',tz='UTC'), pd.Timestamp('2022-10-01',tz='UTC')),
        ('Q4 2022', pd.Timestamp('2022-10-01',tz='UTC'), pd.Timestamp('2023-01-01',tz='UTC')),
        ('Q1 2023', pd.Timestamp('2023-01-01',tz='UTC'), pd.Timestamp('2023-04-01',tz='UTC')),
        ('Q2 2023', pd.Timestamp('2023-04-01',tz='UTC'), pd.Timestamp('2023-07-01',tz='UTC')),
        ('Q3 2023', pd.Timestamp('2023-07-01',tz='UTC'), pd.Timestamp('2023-10-01',tz='UTC')),
        ('Q4 2023', pd.Timestamp('2023-10-01',tz='UTC'), pd.Timestamp('2024-01-01',tz='UTC')),
        ('Q1 2024', pd.Timestamp('2024-01-01',tz='UTC'), pd.Timestamp('2024-04-01',tz='UTC')),
        ('Q2 2024', pd.Timestamp('2024-04-01',tz='UTC'), pd.Timestamp('2024-07-01',tz='UTC')),
        ('Q3 2024', pd.Timestamp('2024-07-01',tz='UTC'), pd.Timestamp('2024-10-01',tz='UTC')),
        ('Q4 2024', pd.Timestamp('2024-10-01',tz='UTC'), pd.Timestamp('2025-01-01',tz='UTC')),
        ('Q1 2025', pd.Timestamp('2025-01-01',tz='UTC'), pd.Timestamp('2025-04-01',tz='UTC')),
        ('Q2 2025', pd.Timestamp('2025-04-01',tz='UTC'), pd.Timestamp('2025-07-01',tz='UTC')),
        ('Q3 2025', pd.Timestamp('2025-07-01',tz='UTC'), pd.Timestamp('2025-10-01',tz='UTC')),
        ('Q4 2025', pd.Timestamp('2025-10-01',tz='UTC'), pd.Timestamp('2026-01-01',tz='UTC')),
        ('Q1/2 2026',pd.Timestamp('2026-01-01',tz='UTC'), None),
    ]
    for qn, qf, qt in quarters:
        s = stats(all_trades, date_from=qf, date_to=qt)
        if not s or s['n'] < 10: continue
        ok = '✅' if s['pf'] >= 1.4 else ('⚠ ' if s['pf'] >= 1.0 else '❌')
        print(f"  {qn:<14} {s['n']:>5} {s['wr']:>5.1f}% {s['pf']:>6.2f} "
              f"£{s['mo']:>7,} £{int(s['arr'].sum()):>8,}  {ok}")

    # ── E. Monthly chart ──────────────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  E. MONTHLY P&L  (1.5x costs, new portfolio)")
    print("=" * W)

    monthly = defaultdict(float)
    for t in all_trades: monthly[t.date[:7]] += net(t)
    bar_chart(monthly)
    pos = sum(1 for v in monthly.values() if v > 0)
    neg = sum(1 for v in monthly.values() if v <= 0)
    print(f"\n  Positive: {pos}  |  Negative: {neg}  |  Hit rate: {pos/(pos+neg)*100:.0f}%")

    # ── F. Monthly distribution ───────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  F. MONTHLY DISTRIBUTION")
    print("=" * W)
    mo_arr = np.array(sorted(monthly.values()))
    print(f"""
  {len(mo_arr)} months of data:
    Median:           £{np.median(mo_arr):>8,.0f}
    Average:          £{np.mean(mo_arr):>8,.0f}
    Best month:       £{np.max(mo_arr):>8,.0f}
    Worst month:      £{np.min(mo_arr):>8,.0f}
    Std deviation:    £{np.std(mo_arr):>8,.0f}
    Months above £0:  {sum(1 for v in mo_arr if v > 0)/len(mo_arr)*100:.0f}%
    Months above £3k: {sum(1 for v in mo_arr if v > 3000)/len(mo_arr)*100:.0f}%
    Months above £8k: {sum(1 for v in mo_arr if v > 8000)/len(mo_arr)*100:.0f}%
    Months above £15k:{sum(1 for v in mo_arr if v > 15000)/len(mo_arr)*100:.0f}%
""")

    # ── G. FTMO Monte Carlo ───────────────────────────────────────────────────
    print("=" * W)
    print("  G. FTMO PHASE 1 — NO TIME LIMIT  (10,000 sims, 1.5x costs)")
    print("=" * W)

    sa  = stats(all_trades)
    dd, dd_pct = max_drawdown(all_trades)
    pass_f, bust_f, run_f = ftmo_monte_carlo(all_trades)

    pass_o, bust_o, run_o = ftmo_monte_carlo(all_oos)
    so = stats(all_oos)

    print(f"""
  Full 8-year data ({sa['n']:,} trades, PF {sa['pf']}, MaxDD £{dd:,} / {dd_pct:.1f}%):
  ┌──────────────────────────────────────────────────┐
  │  Pass (hit +£7k profit):       {pass_f:>6.1f}%           │
  │  Bust (hit loss limit):         {bust_f:>6.1f}%           │
  │  Still running at 500-day cap:  {run_f:>6.1f}%           │
  │  Eventual pass rate:           {pass_f/(pass_f+bust_f)*100:>6.1f}%           │
  └──────────────────────────────────────────────────┘

  OOS only ({so['n']:,} trades, PF {so['pf']}) — most honest:
  ┌──────────────────────────────────────────────────┐
  │  Pass (hit +£7k profit):       {pass_o:>6.1f}%           │
  │  Bust (hit loss limit):         {bust_o:>6.1f}%           │
  │  Still running at 500-day cap:  {run_o:>6.1f}%           │
  │  Eventual pass rate:           {pass_o/(pass_o+bust_o)*100:>6.1f}%           │
  └──────────────────────────────────────────────────┘
  Expected attempts needed: {1/(pass_o/(pass_o+bust_o)):.2f}

  VERDICT:
    >90% eventual pass rate  →  Pay £489. Expected to pass first attempt.
    70-90%                   →  Pay, might need one retry.
    <70%                     →  More live validation first.
""")

    # ── H. New instrument tests ───────────────────────────────────────────────
    print("=" * W)
    print("  H. NEW INSTRUMENTS  (UK100, Gold, USDJPY)")
    print("=" * W)

    new_strats = {}

    # UK100 — London session ORB (same logic as DAX) + LC
    if os.path.exists('UK100_cash_H1.csv'):
        new_strats['UK_ORB']  = run_orb('UK100', 'UK_ORB',  8, 9, 12, 30, 300)
        new_strats['LC_UK']   = run_london_close('UK100', 'LC_UK', min_move=30.0)
    else:
        print("\n  UK100_cash_H1.csv not found — export from MT5 and re-run")

    # Gold — London ORB (08:00 ref, 09:00-12:00 entry) + LC
    if os.path.exists('XAUUSD_H1.csv'):
        new_strats['GOLD_ORB'] = run_orb('GOLD', 'GOLD_ORB', 8, 9, 12, 5, 80)
        new_strats['LC_GOLD']  = run_london_close('GOLD', 'LC_GOLD', min_move=8.0)
    else:
        print("  XAUUSD_H1.csv not found — export from MT5 and re-run")

    # USDJPY — Asia ORB (00:00-03:00 range, 03:00-07:00 entry) + London ORB
    if os.path.exists('USDJPY_H1.csv'):
        new_strats['JPY_ORB']  = run_orb('USDJPY', 'JPY_ORB', 8, 9, 12, 20, 150)
        new_strats['ASIA_JPY'] = run_asia_orb_jpy()
    else:
        print("  USDJPY_H1.csv not found — export from MT5 and re-run")

    if new_strats:
        print(f"\n  {'Strategy':<14} {'Tr':>5} {'T/mo':>5} {'WR%':>6} {'PF':>6} "
              f"{'£/mo':>8}  Verdict")
        print("  " + "─" * (W - 2))

        new_include = []
        for tag, trades in new_strats.items():
            s = stats(trades)
            if not s:
                print(f"  {tag:<14}  insufficient data"); continue
            arr  = s['arr']
            wins = arr[arr > 5]; loss = arr[arr < -5]
            if s['pf'] >= 1.5:
                verdict = '✅ INCLUDE'
                new_include.append((tag, trades))
            elif s['pf'] >= 1.3:
                verdict = '⚠  MAYBE'
            else:
                verdict = '❌ SKIP'
            print(f"  {tag:<14} {s['n']:>5} {s['tpm']:>5.1f} {s['wr']:>5.1f}% "
                  f"{s['pf']:>6.2f} £{s['mo']:>7,}  {verdict}")

        if new_include:
            combined = all_trades + [t for _, v in new_include for t in v]
            sc = stats(combined)
            dd2, _ = max_drawdown(combined)
            oos2   = [t for t in combined if t.date >= str(WF_SPLIT.date())]
            pass2, bust2, _ = ftmo_monte_carlo(oos2)
            print(f"\n  ── Full portfolio with new instruments ──")
            print(f"  Trades/mo: {sc['tpm']:.1f}  |  WR: {sc['wr']:.1f}%  |  "
                  f"PF: {sc['pf']:.2f}  |  £/mo: £{sc['mo']:,.0f}  |  MaxDD: £{dd2:,.0f}")
            print(f"  FTMO OOS pass rate: {pass2:.1f}%  |  "
                  f"Expected attempts: {1/(pass2/(pass2+bust2)):.2f}")


def run_asia_orb_jpy():
    """Asia ORB for USDJPY — 00:00-03:00 UTC range, 03:00-07:00 entry."""
    df = load_h1('USDJPY')
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 0: continue
        rdf = df[(df.index >= day) & (df.index < day + pd.Timedelta(hours=3))]
        if len(rdf) < 2: continue
        a_hi = rdf['high'].max(); a_lo = rdf['low'].min()
        rng  = a_hi - a_lo
        if not (0.10 <= rng <= 0.80): continue  # 10-80 pips for JPY
        buf  = rng * 0.10
        edf  = df[(df.index >= day + pd.Timedelta(hours=3)) &
                  (df.index <  day + pd.Timedelta(hours=7))]
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > a_hi:
                trades.append(make_trade(df, p, 1,  a_hi, a_lo-buf, 'ASIA_JPY', ds, day.dayofweek)); break
            if b['low']  < a_lo:
                trades.append(make_trade(df, p, -1, a_lo, a_hi+buf, 'ASIA_JPY', ds, day.dayofweek)); break
    return trades
