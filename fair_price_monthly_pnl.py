"""
fair_price_monthly_pnl.py

Different view from the Monte Carlo: instead of bootstrap-resampling
days with replacement, this walks through the REAL historical calendar
once, month by month, and shows what actually would have happened --
best real month, worst real month, typical month, over the ~8 years of
OANDA history. Each month is simulated starting fresh from £70,000 (not
compounding across months) so months from different points in history
are comparable on equal footing.

Same locked configuration as the live EA: 0.10% displacement threshold,
NY+London sessions, 1:1.2 R:R, 0.30% risk/trade (the actual live
setting), real-spread-calibrated costs at 1.5x (the realistic middle
stress scenario -- real spread plus ~50% slippage on top).

Also adds a Monte Carlo days-to-pass summary (mean/median) at the end,
using the same day-bundled bootstrap as fair_price_final_stress_test.py,
so the monthly P&L view and the FTMO-challenge-speed view sit side by
side in one report.

Run in Codespace: python -u fair_price_monthly_pnl.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RISK_PCT = 0.30   # the actual live setting
COST_MULT = 1.5   # the realistic middle scenario from the calibrated run
START_BAL = 70000.0
BLOCK_DAYS = 5
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 5000
MAX_SIM_DAYS = 500

RR = 1.2   # switched from 1.5 -- sensitivity sweep showed 1.2 consistently stronger (IS PF 1.72 vs 1.50)
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240

SESSIONS = {'LONDON': 8, 'NY': 13}

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
}

_m1 = {}

def load(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[symbol] = df.dropna()
    return True


def simulate_forward(m1, m1_index, entry_index, direction, entry_price, stop_price, tp_price, max_minutes):
    window_end = min(entry_index + 1 + max_minutes, len(m1))
    future = m1.iloc[entry_index + 1: window_end]
    if len(future) == 0:
        return -1.0
    highs = future['high'].values
    lows  = future['low'].values
    closes = future['close'].values
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0.0
    for k in range(len(future)):
        if direction == 1:
            if highs[k] >= tp_price:
                return RR
            if lows[k] <= stop_price:
                return -1.0
        else:
            if lows[k] <= tp_price:
                return RR
            if highs[k] >= stop_price:
                return -1.0
    final_close = closes[-1]
    return ((final_close - entry_price) / stop_distance if direction == 1
            else (entry_price - final_close) / stop_distance)


def find_reversion_trades(symbol, session_name, session_hour):
    m1 = _m1[symbol]
    m1_index = m1.index
    days = pd.date_range(m1_index.min().normalize(), m1_index.max().normalize(), freq='D')
    trades = []

    for day in days:
        if day.dayofweek >= 5:
            continue
        session_start = day + pd.Timedelta(hours=session_hour)
        rev_start = session_start + pd.Timedelta(minutes=5)
        rev_end = session_start + pd.Timedelta(minutes=REVERSION_WINDOW_MIN)
        rev_window = m1[(m1_index >= rev_start - pd.Timedelta(minutes=1)) & (m1_index < rev_end)]
        if len(rev_window) < 3:
            continue
        bodies = (rev_window['close'] - rev_window['open']).values
        opens = rev_window['open'].values
        closes = rev_window['close'].values
        highs = rev_window['high'].values
        lows = rev_window['low'].values
        idx_labels = rev_window.index

        busy_until = None
        for i in range(1, len(rev_window)):
            ts = idx_labels[i]
            if busy_until is not None and ts < busy_until:
                continue
            if ts < rev_start:
                continue
            body_cur = abs(bodies[i])
            body_prev = abs(bodies[i-1])
            if body_cur <= body_prev:
                continue
            px = float(closes[i])
            if px <= 0 or body_cur / px < MIN_DISPLACEMENT_PCT:
                continue

            direction = 1 if closes[i] > opens[i] else (-1 if closes[i] < opens[i] else 0)
            if direction == 0:
                continue
            entry_price = float(closes[i])
            stop_price = float(lows[i]) if direction == 1 else float(highs[i])
            stop_dist = abs(entry_price - stop_price)
            if stop_dist <= 0:
                continue

            entry_ts = idx_labels[i]
            entry_idx = m1_index.searchsorted(entry_ts)
            if entry_idx >= len(m1) - 1:
                continue
            entry_idx += 1
            entry_price = float(m1['open'].iloc[entry_idx])
            if abs(entry_price - stop_price) <= 0:
                continue
            tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

            r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                        stop_price, tp_price, MAX_HOLD_MIN)
            cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
            r_net = r_gross - cost_r
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_net})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)

    return trades


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        trades = find_reversion_trades(symbol, session_name, session_hour)
        all_trades.extend(trades)

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}  (cost stress: {COST_MULT}x real spread)\n')

df['month'] = df['entry_time'].dt.to_period('M')
rpt = RISK_PCT / 100.0

rows = []
for month, g in df.groupby('month'):
    equity = START_BAL
    for r in g.sort_values('entry_time')['r_net']:
        equity += equity * rpt * r
    pnl = equity - START_BAL
    pnl_pct = pnl / START_BAL * 100
    rows.append({'month': str(month), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl_pct})

monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
print(f'Months with trading activity: {len(monthly)}\n')

print(f'{"="*70}')
print(f'  MONTHLY P&L SUMMARY (each month simulated fresh from £70,000)')
print(f'{"="*70}')
print(f'  Best month:    {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  '
      f'£{monthly["pnl_gbp"].max():>+10,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
print(f'  Worst month:   {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  '
      f'£{monthly["pnl_gbp"].min():>+10,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
print(f'  Median month:  £{monthly["pnl_gbp"].median():>+10,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
print(f'  Mean month:    £{monthly["pnl_gbp"].mean():>+10,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

print(f'\n  Top 5 best months:')
for _, r in monthly.nlargest(5, 'pnl_gbp').iterrows():
    print(f'    {r["month"]}  £{r["pnl_gbp"]:>+10,.0f}  ({r["pnl_pct"]:+.2f}%)  N={r["trades"]:.0f} trades')

print(f'\n  Top 5 worst months:')
for _, r in monthly.nsmallest(5, 'pnl_gbp').iterrows():
    print(f'    {r["month"]}  £{r["pnl_gbp"]:>+10,.0f}  ({r["pnl_pct"]:+.2f}%)  N={r["trades"]:.0f} trades')

print(f'\n  Full month-by-month (year-month, £pnl, %, trades):')
for _, r in monthly.iterrows():
    print(f'    {r["month"]}  £{r["pnl_gbp"]:>+9,.0f}  {r["pnl_pct"]:>+6.2f}%  N={r["trades"]:.0f}')

# ============================================================
#  MONTE CARLO -- DAYS TO PASS AN FTMO CHALLENGE AT THIS RISK
# ============================================================
print(f'\n{"="*70}')
print(f'  MONTE CARLO -- DAYS TO PASS (Risk={RISK_PCT}%, Cost={COST_MULT}x)')
print(f'{"="*70}')

df['day'] = df['entry_time'].dt.date
days_sorted = sorted(df['day'].unique())
day_index = {d: i for i, d in enumerate(days_sorted)}
n_days = len(days_sorted)
by_day = [None] * n_days
for d, g in df.groupby('day'):
    by_day[day_index[d]] = g['r_net'].values

def simulate_one(rng):
    equity = START_BAL
    day_i = 0
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - BLOCK_DAYS))
        for b in range(BLOCK_DAYS):
            idx = start + b
            if idx >= n_days:
                break
            day_start_equity = equity
            for r in by_day[idx]:
                equity += equity * rpt * r
            daily_loss = (day_start_equity - equity) / START_BAL
            if daily_loss > FTMO_DAILY:
                return 'FAILED_DAILY', day_i + 1
            if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                return 'FAILED_TOTAL', day_i + 1
            if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                return 'PASSED', day_i + 1
            day_i += 1
            if day_i >= MAX_SIM_DAYS:
                break
    return 'TIMEOUT', MAX_SIM_DAYS

rng = np.random.default_rng(7)
results = [simulate_one(rng) for _ in range(MC_RUNS)]
outcomes = pd.DataFrame(results, columns=['outcome', 'days'])
n_pass = (outcomes['outcome']=='PASSED').sum()
passed = outcomes[outcomes['outcome']=='PASSED']

print(f'  Pass rate: {n_pass}/{MC_RUNS} ({n_pass/MC_RUNS*100:.2f}%)')
if len(passed) > 0:
    print(f'  Mean days to pass:   {passed["days"].mean():.1f}')
    print(f'  Median days to pass: {passed["days"].median():.0f}')
    print(f'  Fastest pass: {passed["days"].min():.0f} days   Slowest pass: {passed["days"].max():.0f} days')
else:
    print('  No passing runs in this sample.')

print('\nDone.')
