"""
five_day_drawdown_conditional.py

Real situation right now: 5 trading days into live running (Aug 4, 5,
6, 7, 10), the account is down roughly -£777 from the £70,000 start,
about -1.1%. Not one bad day in isolation this time -- a genuine
cumulative rough stretch across the first working week. This is the
honest, specific thing to check: out of all the simulated Monte Carlo
account paths, filter to the ones where the first 5 trading days were
ALSO cumulatively down 1%+ (matching or worse than what's actually
happened), and see what happened to THOSE paths afterward -- pass
rate and days to pass, same rigor as the single-bad-day conditional
check from earlier, just correctly scoped to the real multi-day
pattern instead of a single day.

Same locked live parameters: 0.10% displacement, RR=1.2, 0.30% risk,
real-spread costs at 1.5x, day-block bootstrap against real FTMO
account rules.

Run in Codespace: python -u five_day_drawdown_conditional.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RR = 1.2
COST_MULT = 1.5
RISK_PCT = 0.30
BLOCK_DAYS = 5
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 20000
MAX_SIM_DAYS = 500
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
FIRST_N_DAYS = 5
BAD_STRETCH_THRESHOLD = -0.01   # cumulative loss of 1%+ over the first 5 days

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
            if highs[k] >= tp_price: return RR
            if lows[k] <= stop_price: return -1.0
        else:
            if lows[k] <= tp_price: return RR
            if highs[k] >= stop_price: return -1.0
    final_close = closes[-1]
    return ((final_close - entry_price) / stop_distance if direction == 1
            else (entry_price - final_close) / stop_distance)


def find_reversion_trades(symbol, session_hour):
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
            body_cur = abs(bodies[i]); body_prev = abs(bodies[i-1])
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
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_gross - cost_r})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)
    return trades


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades(symbol, session_hour))

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}\n')

df['day'] = df['entry_time'].dt.date
days_sorted = sorted(df['day'].unique())
day_index = {d: i for i, d in enumerate(days_sorted)}
n_days = len(days_sorted)
by_day = [None] * n_days
for d, g in df.groupby('day'):
    by_day[day_index[d]] = g['r_net'].values

rpt = RISK_PCT / 100.0

def simulate_one(rng):
    equity = START_BAL
    day_i = 0
    first5_return = None
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
                return 'FAILED_DAILY', day_i + 1, first5_return
            if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                return 'FAILED_TOTAL', day_i + 1, first5_return
            if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                return 'PASSED', day_i + 1, first5_return
            day_i += 1
            if day_i == FIRST_N_DAYS:
                first5_return = (equity - START_BAL) / START_BAL
            if day_i >= MAX_SIM_DAYS:
                break
    return 'TIMEOUT', MAX_SIM_DAYS, first5_return

rng = np.random.default_rng(13)
results = [simulate_one(rng) for _ in range(MC_RUNS)]
outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'first5_return'])

print(f'{"#"*90}')
print(f'  BASELINE (all {MC_RUNS} simulated account paths, unconditional)')
print(f'{"#"*90}')
n_pass = (outcomes['outcome']=='PASSED').sum()
passed = outcomes[outcomes['outcome']=='PASSED']
print(f'  Pass rate: {n_pass}/{MC_RUNS} ({n_pass/MC_RUNS*100:.2f}%)')
print(f'  Median days to pass: {passed["days"].median():.0f}')

print(f'\n{"#"*90}')
print(f'  CONDITIONAL: paths where the first {FIRST_N_DAYS} days were cumulatively down '
      f'{BAD_STRETCH_THRESHOLD*100:.0f}%+ (today is roughly -1.1%)')
print(f'{"#"*90}')
rough_start = outcomes[outcomes['first5_return'] <= BAD_STRETCH_THRESHOLD]
print(f'  Paths matching this rough-5-day-start pattern: {len(rough_start)} '
      f'({len(rough_start)/MC_RUNS*100:.2f}% of all simulated paths)')

if len(rough_start) > 0:
    n_pass_rs = (rough_start['outcome']=='PASSED').sum()
    passed_rs = rough_start[rough_start['outcome']=='PASSED']
    n_daily_rs = (rough_start['outcome']=='FAILED_DAILY').sum()
    n_total_rs = (rough_start['outcome']=='FAILED_TOTAL').sum()
    print(f'  Pass rate given this rough start: {n_pass_rs}/{len(rough_start)} ({n_pass_rs/len(rough_start)*100:.2f}%)')
    print(f'  Failed on daily limit: {n_daily_rs}/{len(rough_start)} ({n_daily_rs/len(rough_start)*100:.2f}%)')
    print(f'  Failed on total drawdown: {n_total_rs}/{len(rough_start)} ({n_total_rs/len(rough_start)*100:.2f}%)')
    if len(passed_rs) > 0:
        print(f'\n  Days to pass, GIVEN this rough 5-day start:')
        print(f'    Median: {passed_rs["days"].median():.0f}   Mean: {passed_rs["days"].mean():.1f}')
else:
    print('  No matching paths in this sample.')

print('\nDone.')
