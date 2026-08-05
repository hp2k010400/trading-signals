"""
london_zero_day_check.py

User is seeing zero trades fire in the London session (08:05-09:30 UTC)
for 2 days running (2026-08-04, 2026-08-05) on the live VPS instance,
despite the VPS being confirmed healthy (correct config, single instance,
stable connection, no errors in the Expert log). Before concluding this
is normal variance, check it against the real historical record:

  1. What's the historical distribution of daily trade counts in the
     London window alone, across all 8 instruments combined?
  2. How often has a 2+ consecutive zero-trade-day streak happened before?
  3. Are the most recent ~40 trading days (leading up to now) already
     showing a lower rate than the long-run average -- i.e. is this a
     continuation of an existing recent lull, or a sudden new drop?

Uses the exact same locked, live parameters as the deployed EA
(0.10% displacement, RR=1.2, real-spread costs at 1.5x) -- no changes.

Run in Codespace: python -u london_zero_day_check.py
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
LONDON_HOUR = 8

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
for symbol in loaded:
    all_trades.extend(find_reversion_trades(symbol, LONDON_HOUR))

df = pd.DataFrame(all_trades)
print(f'Total LONDON-session trades (all instruments combined): {len(df)}\n')

df['day'] = df['entry_time'].dt.date

# build the full calendar of weekdays actually covered by the data
min_day = df['entry_time'].min().normalize()
max_day = df['entry_time'].max().normalize()
all_weekdays = pd.date_range(min_day, max_day, freq='D')
all_weekdays = [d.date() for d in all_weekdays if d.dayofweek < 5]

counts_by_day = df.groupby('day').size()
daily_counts = pd.Series([counts_by_day.get(d, 0) for d in all_weekdays], index=all_weekdays)

n_days = len(daily_counts)
n_zero = (daily_counts == 0).sum()
print(f'{"#"*90}')
print(f'  LONDON SESSION -- DAILY TRADE COUNT DISTRIBUTION ({n_days} weekdays, {min_day.date()} -> {max_day.date()})')
print(f'{"#"*90}')
print(f'  Mean trades/day:   {daily_counts.mean():.2f}')
print(f'  Median trades/day: {daily_counts.median():.1f}')
print(f'  Zero-trade days:   {n_zero}/{n_days} ({n_zero/n_days*100:.1f}%)')

# streaks of consecutive zero-trade days
streaks = []
cur = 0
for v in daily_counts.values:
    if v == 0:
        cur += 1
    else:
        if cur > 0:
            streaks.append(cur)
        cur = 0
if cur > 0:
    streaks.append(cur)

streaks = np.array(streaks)
n_streaks_2plus = (streaks >= 2).sum()
n_streaks_3plus = (streaks >= 3).sum()
max_streak = streaks.max() if len(streaks) else 0

print(f'\n  Zero-trade-day streaks found: {len(streaks)} total')
print(f'  Streaks of 2+ consecutive zero days: {n_streaks_2plus}')
print(f'  Streaks of 3+ consecutive zero days: {n_streaks_3plus}')
print(f'  Longest zero-trade streak ever: {max_streak} days')

print(f'\n{"#"*90}')
print(f'  MOST RECENT 40 TRADING DAYS (leading up to end of dataset)')
print(f'{"#"*90}')
recent = daily_counts.tail(40)
for d, v in recent.items():
    flag = ' <- ZERO' if v == 0 else ''
    print(f'  {d}   trades={v}{flag}')

recent_mean = recent.mean()
overall_mean = daily_counts.mean()
print(f'\n  Recent 40-day mean: {recent_mean:.2f}  vs  full-history mean: {overall_mean:.2f}')
if recent_mean < overall_mean * 0.6:
    print('  NOTE: recent rate is meaningfully below the long-run average -- possible regime/volatility lull.')
else:
    print('  Recent rate is broadly in line with the long-run average.')

print('\nDone.')
