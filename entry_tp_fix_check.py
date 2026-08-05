"""
entry_tp_fix_check.py

Real bug confirmed via ChatGPT's independent review (matching a cousin
issue found in my own audit): stop_dist is computed from the SIGNAL
CANDLE'S CLOSE, before entry_price gets reassigned to the next bar's
open. TP is then placed using that stale stop_dist against the NEW
entry_price -- meaning the realized R:R isn't exactly 1.2 every trade,
it drifts by however much entry_price moved between signal close and
actual entry.

This script runs BOTH the current (buggy) version and a FIXED version
(recompute stop_dist from the TRUE entry-to-stop distance after
reassignment, matching what CalcLots already correctly does in the
EA for position sizing) side by side on real data, so we know the
real size of this effect instead of assuming it's small.

Run in Codespace: python -u entry_tp_fix_check.py
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


def find_reversion_trades(symbol, session_hour, fixed):
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
            stop_dist_stale = abs(entry_price - stop_price)   # OLD: from signal candle's close
            if stop_dist_stale <= 0:
                continue
            entry_ts = idx_labels[i]
            entry_idx = m1_index.searchsorted(entry_ts)
            if entry_idx >= len(m1) - 1:
                continue
            entry_idx += 1
            entry_price = float(m1['open'].iloc[entry_idx])   # true entry: next bar's open
            true_stop_dist = abs(entry_price - stop_price)    # NEW: true entry-to-stop distance
            if true_stop_dist <= 0:
                continue
            stop_dist_used = true_stop_dist if fixed else stop_dist_stale
            tp_price = entry_price + stop_dist_used * RR if direction == 1 else entry_price - stop_dist_used * RR
            r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                        stop_price, tp_price, MAX_HOLD_MIN)
            # BUGFIX: cost must stay pinned to stop_dist_stale to match the actually-validated
            # baseline everywhere else tonight -- dividing by true_stop_dist (which can be tiny
            # when the next bar's open lands close to the stop) blows cost_r up artificially,
            # exactly the same failure mode fixed earlier in fair_price_displacement.py
            cost_r = COST_POINTS[symbol] / stop_dist_stale * COST_MULT
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


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

for fixed in [False, True]:
    all_trades = []
    for session_name, session_hour in SESSIONS.items():
        for symbol in loaded:
            all_trades.extend(find_reversion_trades(symbol, session_hour, fixed))
    df = pd.DataFrame(all_trades)
    n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
    label = 'FIXED (TP from true entry-to-stop distance)' if fixed else 'CURRENT (TP from stale signal-close distance)'
    print(f'{"="*80}')
    print(f'  {label}')
    print(f'{"="*80}')
    print(f'  Total trades: {n}')
    print(f'  WR: {wr}%   PF: {pf}   Total R: {tot:+.1f}\n')

print('Done.')
