"""
lesser_traded_atr_expansion_ftmo.py

Same ATR range-expansion mechanism as atr_range_expansion_ftmo.py
(H1 bars, ATR-based expansion threshold AND stop distance -- robust
to broker-feed wick differences), now pointed at the 7 lesser-traded
instruments instead of the majors it failed on (IS PF 0.88, HOLDOUT
PF 0.94 there). Worth a clean re-test here: less competition from
institutional quant activity means a real continuation edge is more
plausible than in EURUSD/GBPUSD/major indices.

COST ESTIMATES ARE UNCALIBRATED -- see lesser_traded_donchian_ftmo.py
for the same caveat. 1.5x cost-stress multiplier applied as a buffer.

MECHANISM (unchanged from the majors version):
  1. Compute 14-period ATR on H1 bars (true range, handles gaps).
  2. A bar "qualifies" if its own true range >= ATR_EXPANSION_MULT x
     the ATR computed from the bars BEFORE it (no lookahead).
  3. Direction = bullish if close > open, bearish if close < open.
  4. Entry at the NEXT H1 bar's open.
  5. Stop = ATR_STOP_MULT x ATR beyond entry (not the signal bar's
     own wick).
  6. Target = stop distance x RR.
  7. Session filter: London (8-10 UTC) + NY (13-16 UTC) power hours.

Same locked IS/OOS split, confirmed UTC+3 broker offset correction
from the start.

Run in Codespace: python -u lesser_traded_atr_expansion_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

ATR_PERIOD = 14
ATR_EXPANSION_MULT = 1.5
ATR_STOP_MULT = 1.0
RR = 1.5
COST_MULT = 1.5
MAX_HOLD_HOURS = 12
BROKER_UTC_OFFSET_HOURS = 3
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

FILES = {
    'NATGAS': 'NATGAS_cash_M1_ftmo.csv',
    'UK100':  'UK100_cash_M1_ftmo.csv',
    'AUDNZD': 'AUDNZD_M1_ftmo.csv',
    'AUDCAD': 'AUDCAD_M1_ftmo.csv',
    'AUDCHF': 'AUDCHF_M1_ftmo.csv',
    'USDCHF': 'USDCHF_M1_ftmo.csv',
    'USDCAD': 'USDCAD_M1_ftmo.csv',
}
# UNCALIBRATED ESTIMATES -- see lesser_traded_donchian_ftmo.py
COST_POINTS = {
    'NATGAS': 0.008, 'UK100': 1.8, 'AUDNZD': 0.0004, 'AUDCAD': 0.0004,
    'AUDCHF': 0.0004, 'USDCHF': 0.00015, 'USDCAD': 0.00015,
}

# Loads/processes ONE instrument's price data at a time, then discards it --
# these 7 instruments now span up to 11 years of real M1 depth (4M+ bars
# each for several), and loading all of them into memory simultaneously via
# a dict OOM-killed the equivalent news-breakout script earlier tonight.

def load(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None, None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1['prev_close'] = h1['close'].shift(1)
    tr = pd.concat([
        h1['high'] - h1['low'],
        (h1['high'] - h1['prev_close']).abs(),
        (h1['low'] - h1['prev_close']).abs(),
    ], axis=1).max(axis=1)
    h1['tr'] = tr
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)   # shifted: ATR known BEFORE this bar, no lookahead
    h1 = h1.dropna()
    return df, h1


def is_power_hour(hour_utc):
    return (8 <= hour_utc <= 10) or (13 <= hour_utc <= 16)


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


def find_trades(symbol, m1, h1):
    m1_index = m1.index
    h1_index = h1.index
    trades = []

    for i in range(len(h1) - 1):
        bar_time = h1_index[i]
        if bar_time.dayofweek >= 5:
            continue
        if not is_power_hour(bar_time.hour):
            continue

        row = h1.iloc[i]
        if row['atr'] <= 0 or row['tr'] < ATR_EXPANSION_MULT * row['atr']:
            continue

        o, c = row['open'], row['close']
        direction = 1 if c > o else (-1 if c < o else 0)
        if direction == 0:
            continue

        entry_time = h1_index[i + 1]
        entry_m1_idx = m1_index.searchsorted(entry_time)
        if entry_m1_idx >= len(m1) - 1:
            continue
        entry_price = float(m1['open'].iloc[entry_m1_idx])
        stop_dist = ATR_STOP_MULT * row['atr']
        if stop_dist <= 0:
            continue
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        r_gross = simulate_forward(m1, m1_index, entry_m1_idx, direction, entry_price,
                                    stop_price, tp_price, MAX_HOLD_HOURS * 60)
        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        trades.append({'symbol': symbol, 'entry_time': m1_index[entry_m1_idx], 'r_net': r_gross - cost_r})

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading FTMO M1 data one instrument at a time, building H1 + ATR...')
all_trades = []
loaded = []
for symbol in FILES:
    m1, h1 = load(symbol)
    if m1 is None:
        continue
    loaded.append(symbol)
    trades = find_trades(symbol, m1, h1)
    print(f'  {symbol}: {len(trades)} trades')
    all_trades.extend(trades)
    del m1, h1
    gc.collect()

print(f'Loaded {len(loaded)} instruments: {loaded}\n')

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
