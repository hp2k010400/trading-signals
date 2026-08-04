"""
fair_price_no_pause.py

Variant of fair_price_calibrated.py with the 1-minute "busy_until" gap
between entries REMOVED -- every qualifying bar can trigger its own
trade with no minimum spacing, instead of skipping the minute right
after each entry. This is a Python-only exploration (does NOT affect
the live EA, which keeps its own equivalent pacing) -- safe to test
here because each bar is only ever evaluated once regardless, so this
just answers "does removing the minimum gap between entries help or
just add more low-quality, tightly-clustered trades and cost drag".

Recalibrates the cost model using REAL spread readings pulled from the
live MT5 Market Watch (18:55 UTC, 2026-08-03), instead of estimates, for
the 5 instruments where we have them. Kept the original estimate for the
3 we don't have real data on (NAS100, SP500, US30).

  Real spread readings (Ask - Bid):
    EURUSD: ~0.0001   (was estimated 0.00015 -- real is tighter)
    GBPUSD: ~0.00003  (was estimated 0.00020 -- real is much tighter)
    USDJPY: ~0.011    (was estimated 0.02     -- real is tighter)
    DAX:    ~1.33     (was estimated 1.5      -- close)
    GOLD:   ~0.40     (was estimated 0.25     -- real is WIDER, worse)

This is still spread only, not slippage -- so treat "1x" here as a
better-informed floor, not a final number. Stress multipliers on top of
THIS baseline are now testing "what if slippage adds this much on top of
real spread", a more meaningful question than stressing a pure guess.

Locked to the winning configuration from the sweep: 0.10% displacement
threshold, NY+London sessions, 1:1.5 R:R, 0.08% risk/trade. Reports
pass rate and time-to-pass in both days AND calendar months for a
£70,000 account.

Run in Codespace: python -u fair_price_calibrated.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RISK_PCT = 0.08
COST_MULTIPLIERS = [1.0, 1.5, 2.0]   # stress ON TOP OF the real-spread-calibrated baseline
BLOCK_DAYS = 5
START_BAL = 70000.0
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
# recalibrated with real Market Watch spread where available; NAS100/SP500/US30 unchanged
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

        for i in range(1, len(rev_window)):
            ts = idx_labels[i]
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
            raw_cost_r = COST_POINTS[symbol] / stop_dist
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx],
                           'r_gross': r_gross, 'raw_cost_r': raw_cost_r})

    return trades


def simulate_one(rng, rpt, cost_mult, block_days, by_day_gross, by_day_cost, n_days):
    equity = START_BAL
    day_i = 0
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - block_days))
        for b in range(block_days):
            idx = start + b
            if idx >= n_days:
                break
            gross = by_day_gross[idx]
            cost = by_day_cost[idx] * cost_mult
            r_net_day = gross - cost
            day_start_equity = equity
            for r in r_net_day:
                equity += equity * rpt * r
            daily_loss = (day_start_equity - equity) / START_BAL
            if daily_loss > FTMO_DAILY:
                return 'FAILED_DAILY', day_i + 1, equity
            if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                return 'FAILED_TOTAL', day_i + 1, equity
            if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                return 'PASSED', day_i + 1, equity
            day_i += 1
            if day_i >= MAX_SIM_DAYS:
                break
    return 'TIMEOUT', MAX_SIM_DAYS, equity


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        trades = find_reversion_trades(symbol, session_name, session_hour)
        all_trades.extend(trades)

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}')
n_days_span = (df['entry_time'].max() - df['entry_time'].min()).days
print(f'~{len(df) / max(1, n_days_span) * 7/5:.1f} trades/weekday\n')

df['day'] = df['entry_time'].dt.date
days_sorted = sorted(df['day'].unique())
day_index = {d: i for i, d in enumerate(days_sorted)}
n_days = len(days_sorted)
by_day_gross = [None] * n_days
by_day_cost = [None] * n_days
for d, g in df.groupby('day'):
    by_day_gross[day_index[d]] = g['r_gross'].values
    by_day_cost[day_index[d]] = g['raw_cost_r'].values

RISK_PER_R = START_BAL * RISK_PCT / 100.0
print(f'Risk/trade: {RISK_PCT}%  =>  £{RISK_PER_R:.2f} per R\n')

print(f'{"="*90}')
print(f'  {"Cost stress":>12}  {"PASSED":>8}  {"FAILED_DAILY":>13}  {"FAILED_TOTAL":>13}  '
      f'{"Median days":>12}  {"Median months":>14}')
print(f'  {"-"*88}')

all_outcomes = {}
for cost_mult in COST_MULTIPLIERS:
    rpt = RISK_PCT / 100.0
    rng = np.random.default_rng(7)
    results = [simulate_one(rng, rpt, cost_mult, BLOCK_DAYS, by_day_gross, by_day_cost, n_days)
               for _ in range(MC_RUNS)]
    outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'final_equity'])
    all_outcomes[cost_mult] = outcomes
    n_pass = (outcomes['outcome'] == 'PASSED').sum()
    n_daily = (outcomes['outcome'] == 'FAILED_DAILY').sum()
    n_total = (outcomes['outcome'] == 'FAILED_TOTAL').sum()
    passed = outcomes[outcomes['outcome'] == 'PASSED']
    med = passed['days'].median() if len(passed) else float('nan')
    med_months = med / 30.44 if not np.isnan(med) else float('nan')
    label = f'{cost_mult:.1f}x real'
    print(f'  {label:>12}  {n_pass:>6}/{MC_RUNS}  {n_daily:>11}/{MC_RUNS}  '
          f'{n_total:>11}/{MC_RUNS}  {med:>12.0f}  {med_months:>14.1f}')

print(f'{"="*90}')
print('\n"1.0x real" = pure real spread, zero slippage assumed -- unrealistic best case.')
print('"1.5x/2.0x real" = real spread plus slippage adding 50-100% on top -- more realistic range.')

MONTH_MARKS = [1, 2, 3, 4, 6]
print(f'\n{"="*90}')
print(f'  MONTHLY PASS-RATE BREAKDOWN (% of all {MC_RUNS:,} simulated accounts passed BY end of month N)')
print(f'{"="*90}')
print(f'  {"Cost stress":>12}' + ''.join(f'{"By month "+str(m):>14}' for m in MONTH_MARKS))
print(f'  {"-"*88}')
for cost_mult in COST_MULTIPLIERS:
    outcomes = all_outcomes[cost_mult]
    passed = outcomes[outcomes['outcome'] == 'PASSED']
    row = f'  {cost_mult:.1f}x real'.ljust(14)
    for m in MONTH_MARKS:
        day_limit = m * 30.44
        pct = (passed['days'] <= day_limit).sum() / MC_RUNS * 100
        row += f'{pct:>13.1f}%'
    print(row)
print(f'  {"-"*88}')

print('\nDone.')
