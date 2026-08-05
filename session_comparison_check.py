"""
session_comparison_check.py

Follow-up to london_zero_day_check.py -- user asked two things:
  1. Does the NY session fire trades more reliably (fewer zero-days)?
  2. WHY does London have so many zero-trade days -- is it just noise,
     or a real structural reason (e.g. 3 of the 8 instruments are US
     indices whose cash market hasn't opened yet during London hours)?

Same locked live parameters, no changes. Adds a per-instrument x
per-session breakdown to test the "US indices contribute less to
London" hypothesis directly with real data instead of guessing.

Run in Codespace: python -u session_comparison_check.py
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

session_trades = {}
for session_name, session_hour in SESSIONS.items():
    trades = []
    for symbol in loaded:
        trades.extend(find_reversion_trades(symbol, session_hour))
    session_trades[session_name] = pd.DataFrame(trades)

# ============================================================
#  PART 1: daily trade-count distribution, London vs NY
# ============================================================
print(f'{"#"*90}')
print(f'  PART 1: DAILY TRADE COUNT -- LONDON vs NY')
print(f'{"#"*90}')
for session_name, df in session_trades.items():
    df['day'] = df['entry_time'].dt.date
    min_day = df['entry_time'].min().normalize()
    max_day = df['entry_time'].max().normalize()
    all_weekdays = pd.date_range(min_day, max_day, freq='D')
    all_weekdays = [d.date() for d in all_weekdays if d.dayofweek < 5]
    counts_by_day = df.groupby('day').size()
    daily_counts = pd.Series([counts_by_day.get(d, 0) for d in all_weekdays], index=all_weekdays)
    n_days = len(daily_counts)
    n_zero = (daily_counts == 0).sum()
    print(f'\n  {session_name}:')
    print(f'    Total trades:      {len(df)}')
    print(f'    Mean trades/day:   {daily_counts.mean():.2f}')
    print(f'    Median trades/day: {daily_counts.median():.1f}')
    print(f'    Zero-trade days:   {n_zero}/{n_days} ({n_zero/n_days*100:.1f}%)')

# ============================================================
#  PART 2: per-instrument split -- does London under-serve the
#  US-index legs specifically (cash market not open yet)?
# ============================================================
print(f'\n{"#"*90}')
print(f'  PART 2: PER-INSTRUMENT TRADE COUNT -- LONDON vs NY')
print(f'{"#"*90}')
print(f'  {"Symbol":<10}{"LONDON":>12}{"NY":>12}{"NY/LONDON ratio":>20}')
for symbol in loaded:
    n_london = (session_trades['LONDON']['symbol'] == symbol).sum()
    n_ny = (session_trades['NY']['symbol'] == symbol).sum()
    ratio = f'{n_ny/n_london:.1f}x' if n_london > 0 else 'inf' if n_ny > 0 else 'n/a'
    print(f'  {symbol:<10}{n_london:>12}{n_ny:>12}{ratio:>20}')

# ============================================================
#  PART 3: COMBINED (LONDON + NY) DAILY TRADE COUNT DISTRIBUTION
# ============================================================
print(f'\n{"#"*90}')
print(f'  PART 3: COMBINED (LONDON + NY) DAILY TRADE COUNT -- full live system')
print(f'{"#"*90}')

combined = pd.concat([session_trades['LONDON'], session_trades['NY']], ignore_index=True)
combined['day'] = combined['entry_time'].dt.date
min_day = combined['entry_time'].min().normalize()
max_day = combined['entry_time'].max().normalize()
all_weekdays = pd.date_range(min_day, max_day, freq='D')
all_weekdays = [d.date() for d in all_weekdays if d.dayofweek < 5]
counts_by_day = combined.groupby('day').size()
daily_counts = pd.Series([counts_by_day.get(d, 0) for d in all_weekdays], index=all_weekdays)

print(f'  Days covered:      {len(daily_counts)} ({min_day.date()} -> {max_day.date()})')
print(f'  Mean trades/day:   {daily_counts.mean():.2f}')
print(f'  Median trades/day: {daily_counts.median():.1f}')
print(f'  Lowest trades/day: {daily_counts.min()}')
print(f'  Highest trades/day:{daily_counts.max():>3}   (on {daily_counts.idxmax()})')
print(f'  Zero-trade days:   {(daily_counts==0).sum()}/{len(daily_counts)} ({(daily_counts==0).sum()/len(daily_counts)*100:.1f}%)')
print(f'\n  Percentiles: 10th={daily_counts.quantile(0.10):.0f}  25th={daily_counts.quantile(0.25):.0f}  '
      f'75th={daily_counts.quantile(0.75):.0f}  90th={daily_counts.quantile(0.90):.0f}')

print('\nDone.')
