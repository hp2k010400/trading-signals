"""
mc_current_scenario.py  -  Monte Carlo for current FTMO position
=================================================================
Simulates the remaining challenge from Harry's exact current state:

  Starting balance : £67,624  (after V3 losses + V4 bug losses)
  FTMO target      : £77,000  (fixed - 10% on original £70k)
  FTMO floor       : £63,000  (fixed - 10% drawdown on original £70k)
  FTMO daily limit : £3,500   (fixed - 5% of original £70k)

Uses daily P&L distribution from the 8.5-year V4 backtest baseline.
Run: python mc_current_scenario.py
"""
import pandas as pd
import numpy as np
import os, warnings, random
from collections import defaultdict
warnings.filterwarnings('ignore')
random.seed(42)

# ── FTMO parameters (absolute, based on original £70k) ────────────────────────
START_BAL    = 67_624   # current balance
TARGET       = 77_000   # must reach this to pass Phase 1
FLOOR        = 63_000   # breach = immediate fail
DAILY_LIMIT  = 3_500    # single day loss limit
MC_RUNS      = 10_000

# ── Load H1 data ───────────────────────────────────────────────────────────────
CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

RISK = {'DAX_ORB':0.75,'NAS_ORB':0.75,'SP5_ORB':0.40,
        'LC_EUR':0.40,'LC_GBP':0.40,'LC_DAX':0.75,'LC_UK':0.75,'LC_GOLD':0.40}

COST_SCALE = 1.5
BASE = {'DAX':0.07,'NAS100':0.06,'SP500':0.06,'EURUSD':0.08,
        'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08}

def cost_r(key, sl_d, v):
    return BASE.get(key, 0.07) * COST_SCALE

# ── Reuse strategy logic from backtest_v4_monthly.py ──────────────────────────
def load_data():
    data = {}
    for key, fn in CSVSYMS.items():
        if not os.path.exists(fn):
            print(f"  Missing: {fn}")
            continue
        df = pd.read_csv(fn)
        df['time'] = pd.to_datetime(df['time'])
        df = df.sort_values('time').reset_index(drop=True)
        data[key] = df
    return data

def get_bar(df, dt):
    idx = df['time'].searchsorted(dt)
    if idx < len(df) and df.iloc[idx]['time'] == dt:
        return df.iloc[idx]
    return None

def run_orb(key, df, date, ref_h, win_s, win_e, days_ok, rmin, rmax, risk, eq):
    dow = date.weekday()
    if days_ok and dow not in days_ok:
        return []
    ref_dt = pd.Timestamp(date.year, date.month, date.day, ref_h)
    bar = get_bar(df, ref_dt)
    if bar is None:
        return []
    rng = bar['high'] - bar['low']
    if rng < rmin or rng > rmax:
        return []
    trades = []
    for h in range(win_s, win_e):
        entry_dt = pd.Timestamp(date.year, date.month, date.day, h)
        eb = get_bar(df, entry_dt)
        if eb is None:
            continue
        if eb['close'] > bar['high']:
            d, entry, sl = 1, eb['close'], bar['low']
        elif eb['close'] < bar['low']:
            d, entry, sl = -1, eb['close'], bar['high']
        else:
            continue
        sl_d = abs(entry - sl)
        if sl_d <= 0:
            continue
        c = cost_r(key, sl_d, 1)
        pnl_r = -1 - c
        for fh in range(h+1, 24):
            fb = get_bar(df, pd.Timestamp(date.year, date.month, date.day, fh))
            if fb is None:
                break
            if d == 1 and fb['low'] < sl:
                break
            if d == -1 and fb['high'] > sl:
                break
            move = (fb['close'] - entry) * d
            if move >= sl_d:
                pnl_r = move/sl_d - c
                break
        trades.append(pnl_r * risk/100 * eq)
        break
    return trades

def run_lc(key, df, date, risk, min_move, eq):
    dow = date.weekday()
    if dow == 4:
        return []
    bar07 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 7))
    bar15 = get_bar(df, pd.Timestamp(date.year, date.month, date.day, 15))
    if bar07 is None or bar15 is None:
        return []
    move = bar15['close'] - bar07['open']
    if abs(move) < min_move:
        return []
    sess_bars = []
    for h in range(7, 16):
        b = get_bar(df, pd.Timestamp(date.year, date.month, date.day, h))
        if b is not None:
            sess_bars.append(b)
    if len(sess_bars) < 2:
        return []
    d_hi = max(b['high'] for b in sess_bars)
    d_lo = min(b['low']  for b in sess_bars)
    buf  = (d_hi - d_lo) * 0.03
    d    = -1 if move > 0 else 1
    entry = bar15['close']
    sl    = d_hi + buf if d == -1 else d_lo - buf
    sl_d  = abs(entry - sl)
    if sl_d <= 0:
        return []
    c = cost_r(key, sl_d, 1)
    pnl_r = -1 - c
    for h in range(16, 24):
        fb = get_bar(df, pd.Timestamp(date.year, date.month, date.day, h))
        if fb is None:
            break
        if d == 1 and fb['low'] < sl:
            break
        if d == -1 and fb['high'] > sl:
            break
        move2 = (fb['close'] - entry) * d
        if move2 >= sl_d:
            pnl_r = move2/sl_d - c
            break
    return [pnl_r * risk/100 * eq]

LC_MIN = {'EURUSD':0.0010,'GBPUSD':0.0025,'DAX':50.0,'UK100':30.0,'GOLD':4.0}

def build_daily_pnl(data, account=70_000):
    dates = sorted(set(
        d for key in data for d in data[key]['time'].dt.normalize().unique()
    ))
    daily = {}
    for date in dates:
        eq = account
        day_pnl = 0
        day_pnl += sum(run_orb('DAX',   data['DAX'],   date, 8, 10,12, None,      20,200, 0.75, eq))
        day_pnl += sum(run_orb('NAS100',data['NAS100'],date,14, 16,18, [1,3],     30,1000,0.75, eq))
        day_pnl += sum(run_orb('SP500', data['SP500'], date,14, 16,19, [1,2,3,4], 3,150,  0.40, eq))
        day_pnl += sum(run_lc('EURUSD',data['EURUSD'],date,0.40,LC_MIN['EURUSD'],eq))
        day_pnl += sum(run_lc('GBPUSD',data['GBPUSD'],date,0.40,LC_MIN['GBPUSD'],eq))
        day_pnl += sum(run_lc('DAX',   data['DAX'],   date,0.75,LC_MIN['DAX'],   eq))
        day_pnl += sum(run_lc('UK100', data['UK100'], date,0.75,LC_MIN['UK100'], eq))
        day_pnl += sum(run_lc('GOLD',  data['GOLD'],  date,0.40,LC_MIN['GOLD'],  eq))
        daily[date] = day_pnl
    return daily

def run_mc(daily_pnl_arr, n_runs=MC_RUNS):
    passes = 0
    floors = 0
    daily_fails = 0
    peak_balances = []
    days_to_pass = []

    arr = np.array(daily_pnl_arr)

    for _ in range(n_runs):
        shuffled = arr.copy()
        np.random.shuffle(shuffled)
        bal = START_BAL
        passed = False
        floored = False
        daily_failed = False
        peak = START_BAL
        day_count = 0

        for daily in shuffled:
            day_count += 1
            bal += daily
            peak = max(peak, bal)

            if daily < -DAILY_LIMIT:
                daily_failed = True
                floored = True
                break
            if bal <= FLOOR:
                floored = True
                break
            if bal >= TARGET:
                passed = True
                days_to_pass.append(day_count)
                break

        peak_balances.append(peak)
        if passed:
            passes += 1
        elif floored:
            floors += 1
            if daily_failed:
                daily_fails += 1

    pass_rate    = passes / n_runs * 100
    floor_rate   = floors / n_runs * 100
    timeout_rate = (n_runs - passes - floors) / n_runs * 100
    avg_days     = np.mean(days_to_pass) if days_to_pass else None

    return pass_rate, floor_rate, timeout_rate, daily_fails/n_runs*100, avg_days

# ── Main ───────────────────────────────────────────────────────────────────────
print("Loading data...")
data = load_data()
if not data:
    print("No CSV files found. Run from trading-signals directory.")
    exit(1)

print(f"Building daily P&L from {len(data)} instruments...")
daily = build_daily_pnl(data)
arr   = list(daily.values())

print(f"  {len(arr)} trading days | Mean £{np.mean(arr):,.0f}/day | "
      f"Std £{np.std(arr):,.0f}/day")
print(f"\nRunning {MC_RUNS:,} Monte Carlo simulations...")
print(f"  Start:  £{START_BAL:,}")
print(f"  Target: £{TARGET:,}  (need +£{TARGET-START_BAL:,})")
print(f"  Floor:  £{FLOOR:,}   (room: £{START_BAL-FLOOR:,})")
print(f"  Daily:  -£{DAILY_LIMIT:,} limit")

pass_r, floor_r, timeout_r, daily_fail_r, avg_days = run_mc(arr)

print(f"\n{'='*50}")
print(f"  PASS  (reach £77k)    : {pass_r:.1f}%")
print(f"  FLOOR (hit £63k)      : {floor_r:.1f}%")
print(f"  TIMEOUT (never finish): {timeout_r:.1f}%")
print(f"  Daily limit breach    : {daily_fail_r:.1f}% of runs")
if avg_days:
    print(f"  Avg days to pass      : {avg_days:.0f} trading days")
print(f"{'='*50}")

# ── Compare to clean start ─────────────────────────────────────────────────────
print(f"\nFor context — original clean-start pass rate was ~99.8%")
print(f"Current scenario pass rate: {pass_r:.1f}%")
print(f"Deficit from bugs/V3: £{70_000 - START_BAL:,} cost you "
      f"{99.8 - pass_r:.1f} percentage points of pass probability")
