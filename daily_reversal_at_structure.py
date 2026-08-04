"""
daily_reversal_at_structure.py

Genuinely distinct from everything tested tonight: not continuation
(OB retest), not the break itself (HTF structure-break), not plain
trend-following (Turtle). This is REVERSAL, but only at a level that
already has real significance -- not any pin bar, only ones forming at
a genuine prior swing high/low.

MECHANISM (daily bars, one instrument = one chart, max ~1 signal/day):
  1. Detect confirmed swing highs/lows (proven fractal zigzag logic,
     reused from htf_structure_break.py -- 2-bar lag, no lookahead).
  2. Each confirmed swing establishes a "key level".
  3. Watch forward (up to 60 trading days) for price to RETEST that
     level AND that retest day's candle to be a genuine rejection
     (pin bar: long wick, small body) -- both conditions required,
     not just proximity to the level.
  4. Retest of a LOW that rejects (bullish pin bar) -> LONG.
     Retest of a HIGH that rejects (bearish pin bar) -> SHORT.
  5. Stop = beyond the pin bar's own wick extreme. Target = 2R (fixed,
     not swept, to avoid a fresh multiple-comparisons dimension on a
     brand new hypothesis).
  6. Enter next day's open (real M1 data used for that day's actual
     price path -- no lookahead).

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u daily_reversal_at_structure.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

FRACTAL_LAG = 2
RETEST_WINDOW_DAYS = 60
RETEST_TOLERANCE_PCT = 0.3   # % of price -- how close is "at" the level
PIN_WICK_TO_BODY = 2.0
PIN_WICK_TO_RANGE = 0.5
TP_R = 2.0
MAX_HOLD_DAYS = 20
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

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


def find_zigzag_swings(daily, lag=FRACTAL_LAG):
    highs = daily['high'].values
    lows  = daily['low'].values
    n = len(daily)
    raw = []
    for i in range(lag, n - lag):
        window_h = highs[i-lag:i+lag+1]
        window_l = lows[i-lag:i+lag+1]
        if highs[i] >= window_h.max():
            raw.append({'type':'HIGH', 'price': float(highs[i]), 'idx': i, 'confirm_idx': i+lag})
        if lows[i] <= window_l.min():
            raw.append({'type':'LOW', 'price': float(lows[i]), 'idx': i, 'confirm_idx': i+lag})
    raw.sort(key=lambda s: s['confirm_idx'])

    zigzag = []
    for s in raw:
        if not zigzag:
            zigzag.append(s)
            continue
        last = zigzag[-1]
        if s['type'] == last['type']:
            if s['type'] == 'HIGH' and s['price'] > last['price']:
                zigzag[-1] = s
            elif s['type'] == 'LOW' and s['price'] < last['price']:
                zigzag[-1] = s
        else:
            zigzag.append(s)
    return zigzag


def is_pin_bar(o, h, l, c):
    body = abs(c - o)
    rng = h - l
    if rng <= 0 or body < rng * 0.02:
        return 0
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    min_wick = max(body, rng * 0.001)
    if lower_wick >= PIN_WICK_TO_BODY * min_wick and lower_wick >= PIN_WICK_TO_RANGE * rng:
        return 1    # bullish pin bar (rejection of lower prices)
    if upper_wick >= PIN_WICK_TO_BODY * min_wick and upper_wick >= PIN_WICK_TO_RANGE * rng:
        return -1   # bearish pin bar (rejection of higher prices)
    return 0


def simulate_forward(m1, m1_index, entry_index, direction, entry_price, stop_price, tp_price, max_days):
    max_minutes = max_days * 24 * 60
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
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    n = len(daily)
    if n < FRACTAL_LAG * 6:
        return []

    swings = find_zigzag_swings(daily)
    trades = []
    used_level_idx = set()   # each swing level retested at most once

    for lvl_i, level in enumerate(swings):
        watch_start_idx = level['confirm_idx'] + 1
        watch_end_idx = min(level['confirm_idx'] + RETEST_WINDOW_DAYS, n - 1)
        if watch_start_idx >= watch_end_idx:
            continue

        level_price = level['price']
        for day_idx in range(watch_start_idx, watch_end_idx):
            o = daily['open'].iloc[day_idx]; h = daily['high'].iloc[day_idx]
            l = daily['low'].iloc[day_idx]; c = daily['close'].iloc[day_idx]
            if o <= 0:
                continue
            touched = (l <= level_price * (1 + RETEST_TOLERANCE_PCT/100.0) and
                       h >= level_price * (1 - RETEST_TOLERANCE_PCT/100.0))
            if not touched:
                continue

            pin = is_pin_bar(o, h, l, c)
            if pin == 0:
                continue
            # only trade a rejection that matches the level's own type:
            # a LOW retested and rejected (bullish pin) -> long;
            # a HIGH retested and rejected (bearish pin) -> short
            if level['type'] == 'LOW' and pin != 1:
                continue
            if level['type'] == 'HIGH' and pin != -1:
                continue

            direction = pin
            stop_price = l if direction == 1 else h
            entry_ts_day = daily.index[day_idx] + pd.Timedelta(days=1)
            entry_idx = m1_index.searchsorted(entry_ts_day)
            if entry_idx >= len(m1) - 1:
                break
            entry_price = float(m1['open'].iloc[entry_idx])
            stop_dist = abs(entry_price - stop_price)
            if stop_dist <= 0:
                break
            tp_price = entry_price + stop_dist * TP_R if direction == 1 else entry_price - stop_dist * TP_R

            r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                        stop_price, tp_price, MAX_HOLD_DAYS)
            cost_r = COST_POINTS[symbol] / stop_dist
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx],
                           'r_net': r_gross - cost_r})
            break   # this level is used up after its first valid retest

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

all_trades = []
for symbol in loaded:
    trades = find_setups(symbol)
    print(f'  {symbol}: {len(trades)} trades')
    all_trades.extend(trades)

df = pd.DataFrame(all_trades)
print(f'\nTotal trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

if len(df) > 0:
    is_df = df[df['entry_time'] < IS_OOS_SPLIT]
    oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]
    print()
    n, wr, pf, tot = compute_stats(is_df['r_net'].values)
    print_row('IN-SAMPLE (all)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
    print_row('HOLDOUT (all)', n, wr, pf, tot)
    print()
    for symbol in loaded:
        rv_is = is_df[is_df['symbol'] == symbol]['r_net'].values
        rv_oos = oos_df[oos_df['symbol'] == symbol]['r_net'].values
        n, wr, pf, tot = compute_stats(rv_is)
        print_row(f'  {symbol} IS', n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(rv_oos)
        print_row(f'  {symbol} HOLDOUT', n, wr, pf, tot)

print('\nDone.')
