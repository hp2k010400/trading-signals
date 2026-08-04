"""
asian_range_breakout.py

Genuinely different mechanism from anything tested tonight (not a
re-run of displacement-candle logic on a different session).

RATIONALE: Asian hours (00:00-08:00 UTC) are off-hours for European and
US instruments -- low liquidity, low participation, price tends to
consolidate into a tight range. When London opens and real volume
arrives, a break of that established range reflects genuine new
participation, not noise.

MECHANISM:
  1. Mark the Asian session's high/low (00:00-08:00 UTC) for each day.
  2. Watch the following 4 hours (08:00-12:00 UTC, covering London open
     and into the early NY pre-market) for price to break that range.
  3. Enter at the literal broken level (real M1 bar-by-bar scan, no
     lookahead), in the direction of the break.
  4. Stop = opposite side of the Asian range (a natural structural stop).
  5. Target = 2R (kept simple and fixed -- not swept, to avoid adding a
     fresh multiple-comparisons dimension on a brand new hypothesis).

Tests DAX/NAS100/SP500/US30/EURUSD/GBPUSD (instruments where "Asian =
off-hours" genuinely applies) separately from GOLD/USDJPY (which trade
actively during Asian/Tokyo hours, so the same rationale doesn't cleanly
apply -- reported separately for comparison, not pooled in).

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u asian_range_breakout.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ASIAN_START_HOUR = 0
ASIAN_END_HOUR = 8
WATCH_END_HOUR = 12   # watch for the breakout until 12:00 UTC
TP_R = 2.0
MAX_HOLD_MIN = 240
MIN_RANGE_PCT = 0.05   # % of price -- Asian range must be at least this wide to count (filters dead/no-data days)
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

CORE_SET = ['DAX', 'NAS100', 'SP500', 'US30', 'EURUSD', 'GBPUSD']
NATIVE_SESSION_SET = ['GOLD', 'USDJPY']   # trade actively during Asian hours, reported separately

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
            if highs[k] >= tp_price: return TP_R
            if lows[k] <= stop_price: return -1.0
        else:
            if lows[k] <= tp_price: return TP_R
            if highs[k] >= stop_price: return -1.0
    final_close = closes[-1]
    return ((final_close - entry_price) / stop_distance if direction == 1
            else (entry_price - final_close) / stop_distance)


def find_setups(symbol):
    m1 = _m1[symbol]
    m1_index = m1.index
    days = pd.date_range(m1_index.min().normalize(), m1_index.max().normalize(), freq='D')
    trades = []
    for day in days:
        if day.dayofweek >= 5:
            continue
        asian_start = day + pd.Timedelta(hours=ASIAN_START_HOUR)
        asian_end   = day + pd.Timedelta(hours=ASIAN_END_HOUR)
        asian_window = m1[(m1_index >= asian_start) & (m1_index < asian_end)]
        if len(asian_window) < 60:
            continue
        asian_high = float(asian_window['high'].max())
        asian_low = float(asian_window['low'].min())
        asian_range = asian_high - asian_low
        mid_price = (asian_high + asian_low) / 2
        if mid_price <= 0 or asian_range / mid_price < MIN_RANGE_PCT / 100.0:
            continue

        watch_end = day + pd.Timedelta(hours=WATCH_END_HOUR)
        watch_window = m1[(m1_index >= asian_end) & (m1_index < watch_end)]
        if len(watch_window) == 0:
            continue

        direction = 0; entry_price = None; entry_idx_local = -1
        for j in range(len(watch_window)):
            bar = watch_window.iloc[j]
            if bar['high'] > asian_high:
                direction = 1; entry_price = asian_high; entry_idx_local = j; break
            if bar['low'] < asian_low:
                direction = -1; entry_price = asian_low; entry_idx_local = j; break
        if direction == 0:
            continue

        stop_price = asian_low if direction == 1 else asian_high
        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0:
            continue
        tp_price = entry_price + stop_dist * TP_R if direction == 1 else entry_price - stop_dist * TP_R

        entry_ts = watch_window.index[entry_idx_local]
        entry_idx = m1_index.searchsorted(entry_ts)
        if entry_idx >= len(m1):
            continue

        r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                    stop_price, tp_price, MAX_HOLD_MIN)
        cost_r = COST_POINTS[symbol] / stop_dist
        trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_gross - cost_r})
    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

for group_name, symbols in [('CORE SET (Asian = off-hours)', CORE_SET),
                             ('NATIVE-SESSION SET (trades actively in Asian hours)', NATIVE_SESSION_SET)]:
    print(f'{"#"*90}')
    print(f'  {group_name}')
    print(f'{"#"*90}')
    all_trades = []
    for symbol in symbols:
        if symbol not in loaded:
            continue
        trades = find_setups(symbol)
        print(f'  {symbol}: {len(trades)} trades')
        all_trades.extend(trades)

    df = pd.DataFrame(all_trades)
    if len(df) == 0:
        print('  No trades.\n')
        continue
    is_df = df[df['entry_time'] < IS_OOS_SPLIT]
    oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]
    print()
    n, wr, pf, tot = compute_stats(is_df['r_net'].values)
    print_row('IN-SAMPLE (group)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
    print_row('HOLDOUT (group)', n, wr, pf, tot)
    print()
    for symbol in symbols:
        if symbol not in loaded:
            continue
        rv_is = is_df[is_df['symbol'] == symbol]['r_net'].values
        rv_oos = oos_df[oos_df['symbol'] == symbol]['r_net'].values
        n, wr, pf, tot = compute_stats(rv_is)
        print_row(f'  {symbol} IS', n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(rv_oos)
        print_row(f'  {symbol} HOLDOUT', n, wr, pf, tot)
    print()

print('Done.')
