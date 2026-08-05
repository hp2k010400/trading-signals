"""
consecutive_weak_days_check.py

User's real concern: Aug 4 (33.3% WR) and Aug 5 (38% WR) back to back
-- two weak days in a row. Track record tonight is that bad numbers
sometimes DID mean a real bug (the fake original backtest, the EA
restart issue) -- both found by directly auditing code, not by
pattern-matching bad outcomes, but the concern is fair: is 2 weak
days in a row itself unusual for this system?

Directly checks the real 8.5-year record: on each trading day with a
meaningful sample of trades, compute that day's win rate. Then check
how often two (or more) CONSECUTIVE trading days both come in at or
below a "weak" threshold (<=40% WR, matching Aug4/Aug5), with no code
bug present in the historical data -- it's pure market history.

If this has happened many times before across 8.5 years of a system
we've now independently verified is not fabricated, that's real
evidence this pattern is normal variance clustering, not a signal.

Run in Codespace: python -u consecutive_weak_days_check.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RR = 1.2
COST_MULT = 1.5
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
WEAK_WR_THRESHOLD = 40.0   # % -- matches Aug4 (33.3%) / Aug5 (38%)
MIN_TRADES_FOR_DAY = 10    # ignore days with too few trades to say anything about WR

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
df['win'] = df['r_net'] > 0

daily = df.groupby('day').agg(n=('r_net', 'size'), wins=('win', 'sum')).reset_index()
daily['wr'] = daily['wins'] / daily['n'] * 100
daily = daily.sort_values('day').reset_index(drop=True)

qualifying = daily[daily['n'] >= MIN_TRADES_FOR_DAY].reset_index(drop=True)
print(f'Days with >= {MIN_TRADES_FOR_DAY} trades (enough to judge WR): {len(qualifying)}\n')

qualifying['weak'] = qualifying['wr'] <= WEAK_WR_THRESHOLD
n_weak = qualifying['weak'].sum()
print(f'Days at or below {WEAK_WR_THRESHOLD}% WR: {n_weak}/{len(qualifying)} ({n_weak/len(qualifying)*100:.1f}%)')

# find consecutive-CALENDAR-DAY streaks of weak trading days (allowing normal
# weekday gaps, i.e. Friday->Monday still counts as "consecutive trading days")
streaks = []
cur = 0
streak_examples = []
cur_start = None
for i, row in qualifying.iterrows():
    if row['weak']:
        if cur == 0:
            cur_start = row['day']
        cur += 1
    else:
        if cur >= 2:
            streaks.append(cur)
            streak_examples.append((cur_start, qualifying.iloc[i-1]['day'], cur))
        cur = 0
if cur >= 2:
    streaks.append(cur)
    streak_examples.append((cur_start, qualifying.iloc[len(qualifying)-1]['day'], cur))

print(f'\n{"#"*90}')
print(f'  CONSECUTIVE WEAK-WR TRADING DAYS (<= {WEAK_WR_THRESHOLD}% WR back to back)')
print(f'{"#"*90}')
print(f'  Streaks of 2+ consecutive weak days found: {len(streaks)}')
if streaks:
    print(f'  Longest such streak: {max(streaks)} consecutive weak days')
    print(f'\n  All occurrences:')
    for start, end, length in streak_examples:
        print(f'    {start} -> {end}   ({length} consecutive weak days)')
else:
    print('  None found in the entire historical record -- this would be a genuine first.')

print('\nDone.')
