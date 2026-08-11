"""
atr_range_expansion_ftmo.py

Coarser, more robust cousin of the strategy that just failed. Same
underlying idea -- a genuine expansion in range implies continuation
-- but rebuilt specifically to avoid the failure mode: instead of
comparing one M1 candle's exact body to the previous one and stopping
at that candle's exact wick, this works on H1 bars and uses ATR (a
14-bar statistical average) for both the expansion threshold AND the
stop distance. ATR is far less sensitive to any single bar's precise
high/low than a raw wick comparison, so it should be much less prone
to the broker-feed sensitivity that killed the M1 version.

MECHANISM:
  1. Compute 14-period ATR on H1 bars (true range, handles gaps).
  2. A bar "qualifies" if its own true range >= ATR_EXPANSION_MULT x
     the ATR computed from the bars BEFORE it (no lookahead).
  3. Direction = bullish if close > open, bearish if close < open.
  4. Entry at the NEXT H1 bar's open.
  5. Stop = ATR_STOP_MULT x ATR beyond entry (not the signal bar's
     own wick).
  6. Target = stop distance x RR.
  7. Session filter: London (8-10 UTC) + NY (13-16 UTC) power hours,
     same real market-structure reasoning as everything else tonight.

Same locked IS/OOS split, real spread costs, confirmed UTC+3 broker
offset correction from the start.

Run in Codespace: python -u atr_range_expansion_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
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
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'GOLD':  'XAUUSD_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
}

_m1 = {}
_h1 = {}

def load(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    _m1[symbol] = df
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1['prev_close'] = h1['close'].shift(1)
    tr = pd.concat([
        h1['high'] - h1['low'],
        (h1['high'] - h1['prev_close']).abs(),
        (h1['low'] - h1['prev_close']).abs(),
    ], axis=1).max(axis=1)
    h1['tr'] = tr
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)   # shifted: ATR known BEFORE this bar, no lookahead
    _h1[symbol] = h1.dropna()
    return True


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


def find_trades(symbol):
    m1 = _m1[symbol]
    h1 = _h1[symbol]
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


print('Loading FTMO M1 data, building H1 + ATR...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for symbol in loaded:
    trades = find_trades(symbol)
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
