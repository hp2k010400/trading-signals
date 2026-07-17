"""
backtest_v4_trade_log.py  -  Per-trade R-multiple distribution from backtest
=============================================================================
Runs the full V4 backtest (BASELINE scenario) and extracts every trade's
R-multiple. Shows the actual distribution of wins and losses to explain
what the expected RRR looks like — and puts the live 0.98 RRR in context.

Requires H1 CSV files in the working directory (same as backtest_v4_stress.py).

Run: python backtest_v4_trade_log.py
"""
import numpy as np
import os, sys

# ── Reuse backtest_v4_stress infrastructure ────────────────────────────────────
# Add current dir to path and import helpers
sys.path.insert(0, os.path.dirname(__file__))

ACCOUNT  = 70_000
COST_PCT = 0.07     # baseline cost as fraction of SL

CSVSYMS = {
    'DAX':    'GER40_cash_H1.csv',
    'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv',
    'EURUSD': 'EURUSD_H1.csv',
    'GBPUSD': 'GBPUSD_H1.csv',
    'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

RISK = {
    'DAX_ORB': 0.0075, 'NAS_ORB': 0.0075, 'SP5_ORB': 0.0040,
    'LC_EUR':  0.0040, 'LC_GBP':  0.0040, 'LC_DAX':  0.0075,
    'LC_UK':   0.0075, 'LC_GOLD': 0.0040,
}

LC_MIN = {'EURUSD': 0.0010, 'GBPUSD': 0.0025, 'DAX': 50.0,
          'UK100': 30.0, 'GOLD': 4.0}

try:
    import pandas as pd
except ImportError:
    print("pandas not installed. Run: pip install pandas numpy")
    sys.exit(1)

def load_h1(key):
    fn = CSVSYMS[key]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'])
    return df.sort_values('time').drop_duplicates('time').reset_index(drop=True)

def get_bar(df, ts):
    idx = df['time'].searchsorted(ts)
    if idx < len(df) and df.iloc[idx]['time'] == ts:
        return df.iloc[idx]
    return None

def sim_trade(df, ep, direction, entry, sl, trail=0.05, max_bars=80):
    sl_d = abs(entry - sl)
    if sl_d <= 0:
        return -1.0
    tr = sl_d * trail
    cs = sl
    bst = entry
    be = False
    for i in range(ep + 1, min(ep + max_bars, len(df))):
        b = df.iloc[i]
        mv = (b['close'] - entry) * direction
        if not be and mv >= sl_d:
            cs = entry
            be = True
        if be and mv >= sl_d + tr:
            new_cs = entry + (mv - tr) * direction
            if direction == 1:
                cs = max(cs, new_cs)
            else:
                cs = min(cs, new_cs)
            bst = b['close']
        if direction == 1 and b['low'] < cs:
            return (cs - entry) / sl_d
        if direction == -1 and b['high'] > cs:
            return (entry - cs) / sl_d
    lp = df.iloc[min(ep + max_bars, len(df) - 1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def get_dates(df):
    return pd.to_datetime(df['time'].dt.normalize().unique())

def run_orb(key, tag, ref_h, win_s, win_e, rmin, rmax, risk_pct, trail, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None:
        return []
    trades = []
    for date in get_dates(df):
        if date.weekday() in skip_dow:
            continue
        ref = get_bar(df, pd.Timestamp(date.year, date.month, date.day, ref_h))
        if ref is None:
            continue
        rng = ref['high'] - ref['low']
        if not (rmin <= rng <= rmax):
            continue
        for h in range(win_s, win_e):
            ts = pd.Timestamp(date.year, date.month, date.day, h)
            b = get_bar(df, ts)
            if b is None:
                continue
            if b['close'] > ref['high']:
                d, entry, sl = 1, b['close'], ref['low']
            elif b['close'] < ref['low']:
                d, entry, sl = -1, b['close'], ref['high']
            else:
                continue
            sl_d = abs(entry - sl)
            if sl_d <= 0:
                continue
            ep = int(df['time'].searchsorted(ts))
            r = sim_trade(df, ep, d, entry, sl, trail)
            r_net = r - COST_PCT
            pnl = r_net * risk_pct * ACCOUNT
            trades.append({'tag': tag, 'date': str(date.date()), 'r': r_net,
                           'win': r_net > 0, 'pnl': pnl})
            break
    return trades

def run_lc(key, tag, risk_pct, min_move, trail):
    df = load_h1(key)
    if df is None:
        return []
    trades = []
    for date in get_dates(df):
        if date.weekday() == 4:
            continue
        b07 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 7))
        b15 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 15))
        if b07 is None or b15 is None:
            continue
        move = b15['close'] - b07['open']
        if abs(move) < min_move:
            continue
        sess = [get_bar(df, pd.Timestamp(date.year, date.month, date.day, h))
                for h in range(7, 16)]
        sess = [b for b in sess if b is not None]
        if len(sess) < 2:
            continue
        d_hi = max(b['high'] for b in sess)
        d_lo = min(b['low']  for b in sess)
        buf  = (d_hi - d_lo) * 0.03
        d    = -1 if move > 0 else 1
        entry = b15['close']
        sl    = d_hi + buf if d == -1 else d_lo - buf
        sl_d  = abs(entry - sl)
        if sl_d <= 0:
            continue
        ep = int(df['time'].searchsorted(pd.Timestamp(date.year, date.month, date.day, 15)))
        r = sim_trade(df, ep, d, entry, sl, trail)
        r_net = r - COST_PCT
        pnl = r_net * risk_pct * ACCOUNT
        trades.append({'tag': tag, 'date': str(date.date()), 'r': r_net,
                       'win': r_net > 0, 'pnl': pnl})
    return trades

# ── Run full backtest ───────────────────────────────────────────────────────────
print("Loading data and running full V4 backtest trade log...")
print("(Requires H1 CSV files in working directory)\n")

all_trades = []
all_trades += run_orb('DAX',    'DAX_ORB', 8,  10, 12, 20,  200,  0.0075, 0.05)
all_trades += run_orb('NAS100', 'NAS_ORB', 14, 16, 18, 30,  1000, 0.0075, 0.05, skip_dow={0,2,3,4})
all_trades += run_orb('SP500',  'SP5_ORB', 14, 16, 19, 3,   150,  0.0040, 0.05, skip_dow={0,4})
all_trades += run_lc('EURUSD',  'LC_EUR',  0.0040, LC_MIN['EURUSD'], 0.05)
all_trades += run_lc('GBPUSD',  'LC_GBP',  0.0040, LC_MIN['GBPUSD'], 0.05)
all_trades += run_lc('DAX',     'LC_DAX',  0.0075, LC_MIN['DAX'],    0.05)
all_trades += run_lc('UK100',   'LC_UK',   0.0075, LC_MIN['UK100'],  0.05)
all_trades += run_lc('GOLD',    'LC_GOLD', 0.0040, LC_MIN['GOLD'],   0.05)

if not all_trades:
    print("No trades generated. Check that H1 CSV files are present.")
    sys.exit(1)

r_vals  = np.array([t['r'] for t in all_trades])
wins    = r_vals[r_vals > 0]
losses  = r_vals[r_vals <= 0]
wr      = len(wins) / len(r_vals)

print(f"{'═'*55}")
print(f"  BACKTEST TRADE LOG  ({len(all_trades):,} total trades)\n")
print(f"  Win rate          : {wr*100:.1f}%")
print(f"  Profit factor     : {wins.sum() / abs(losses.sum()):.2f}")
print(f"\n  WINNERS ({len(wins):,} trades):")
print(f"    Avg R           : {wins.mean():.2f}R")
print(f"    Median R        : {np.median(wins):.2f}R")
print(f"    Best R          : {wins.max():.2f}R")
print(f"    % >2R           : {(wins > 2).mean()*100:.1f}%")
print(f"    % >3R           : {(wins > 3).mean()*100:.1f}%")
print(f"\n  LOSERS ({len(losses):,} trades):")
print(f"    Avg R           : {losses.mean():.2f}R")
print(f"    Median R        : {np.median(losses):.2f}R")
print(f"    Worst R         : {losses.min():.2f}R")
print(f"\n  RRR (avg win / avg |loss|) : {wins.mean() / abs(losses.mean()):.2f}")
print(f"  Live RRR                   : 0.98  (gap: {wins.mean()/abs(losses.mean()) - 0.98:.2f}R)")
print(f"{'═'*55}")

# Per-strategy breakdown
print(f"\nPER-STRATEGY BREAKDOWN\n")
print(f"  {'Strategy':>10}  {'Trades':>7}  {'WR':>7}  {'Avg Win R':>10}  {'Avg Loss R':>11}  {'RRR':>6}  {'PF':>6}")
print(f"  {'─'*10}  {'─'*7}  {'─'*7}  {'─'*10}  {'─'*11}  {'─'*6}  {'─'*6}")

for tag in ['DAX_ORB', 'NAS_ORB', 'SP5_ORB', 'LC_EUR', 'LC_GBP', 'LC_DAX', 'LC_UK', 'LC_GOLD']:
    t_r = np.array([t['r'] for t in all_trades if t['tag'] == tag])
    if len(t_r) == 0:
        continue
    t_wins  = t_r[t_r > 0]
    t_loss  = t_r[t_r <= 0]
    t_wr    = len(t_wins) / len(t_r) if len(t_r) else 0
    avg_w   = t_wins.mean()  if len(t_wins) else 0
    avg_l   = t_loss.mean()  if len(t_loss) else 0
    rrr     = avg_w / abs(avg_l) if avg_l != 0 else 0
    pf      = (t_wins.sum() / abs(t_loss.sum())) if len(t_loss) else float('inf')
    print(f"  {tag:>10}  {len(t_r):>7}  {t_wr*100:>6.1f}%  {avg_w:>10.2f}R  {avg_l:>11.2f}R  {rrr:>6.2f}  {pf:>6.2f}")

# R distribution histogram (text-based)
print(f"\nR-MULTIPLE DISTRIBUTION (all trades)\n")
bins = [-3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3, 5, 10]
counts, edges = np.histogram(r_vals, bins=bins)
max_c = max(counts)
bar_w = 30
for i, c in enumerate(counts):
    label = f"{edges[i]:>5.1f} to {edges[i+1]:>5.1f}R"
    bar = "█" * int(c / max_c * bar_w)
    pct = c / len(r_vals) * 100
    print(f"  {label} | {bar:<{bar_w}} {c:>5} ({pct:>4.1f}%)")

print(f"\n  Median R (all trades): {np.median(r_vals):.2f}R")
print(f"  Mean R   (all trades): {r_vals.mean():.2f}R  ({'positive edge' if r_vals.mean() > 0 else 'negative edge'})")
