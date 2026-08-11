"""
ftmo_data_backtest.py

The definitive version of this question: does the strategy's edge
(validated at ~57-63% WR, PF 1.6-1.7 on OANDA's 8.5yr history) also
show up when backtested on FTMO's OWN broker-native M1 price history?
This removes any feed-discrepancy question entirely -- same exact
locked strategy logic, same exact data source the live EA actually
trades on.

FTMO's M1 history is likely much shorter than OANDA's (brokers
typically cache less M1 history than a full data vendor), so this
will cover whatever range is actually available -- reports total
WR/PF, and a walk-forward breakdown if there's enough history for one.

Run in Codespace: python -u ftmo_data_backtest.py
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
WALK_FORWARD_MONTHS = 1   # shorter window since FTMO history is likely much shorter than 8.5yr

SESSIONS = {'LONDON': 8, 'NY': 13}

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


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


print('Loading FTMO M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)}/{len(FILES)} instruments: {loaded}')
missing = [s for s in FILES if s not in loaded]
if missing:
    print(f'MISSING (file not found): {missing}')
print()

if loaded:
    for symbol in loaded:
        rng = _m1[symbol]
        print(f'  {symbol}: {len(rng)} bars, {rng.index.min()} -> {rng.index.max()}')
    print()

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades(symbol, session_hour))

df = pd.DataFrame(all_trades)
n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print(f'{"="*80}')
print(f'  FULL FTMO-DATA BACKTEST RESULT')
print(f'{"="*80}')
print(f'  Total trades: {n}   WR: {wr}%   PF: {pf}   Total R: {tot:+.1f}\n')

if len(df) > 0:
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    print(f'{"#"*90}')
    print(f'  MONTHLY BREAKDOWN (whatever range FTMO data actually covers)')
    print(f'{"#"*90}')
    for period in all_periods:
        window_rv = df[df['period'] == period]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        flag = ' <- LOSING' if tot2 < 0 else ''
        print(f'  {period}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}{flag}')

print('\nDone.')
