"""
fair_price_breakdown.py

The one diagnostic we haven't run on the fair-pricing displacement signal
at its final, validated settings (0.10% threshold, real-spread-calibrated
costs): is the edge genuinely broad-based across the 8 instruments, or is
the aggregate PF ~1.59 secretly being carried by just one or two of them?
Same coherence check that's flagged noise in nearly every other strategy
tested tonight -- an edge concentrated in one instrument is a much
weaker, more fragile claim than one that shows up consistently across
most of the book.

Also splits NY vs London separately (previously only reported combined)
to see if one session is doing most of the work.

Run in Codespace: python -u fair_price_breakdown.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
COST_MULT = 1.5
RR = 1.5
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

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


def find_reversion_trades(symbol, session_name, session_hour):
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
            r_net = r_gross - cost_r
            trades.append({'symbol': symbol, 'session': session_name,
                           'entry_time': m1_index[entry_idx], 'r_net': r_net})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)
    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=24):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        trades = find_reversion_trades(symbol, session_name, session_hour)
        all_trades.extend(trades)

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}\n')

print(f'{"="*80}')
print('  PER-INSTRUMENT BREAKDOWN (all sessions combined, IS + holdout)')
print(f'{"="*80}')
for sym in sorted(loaded, key=lambda s: -df[df['symbol']==s]['r_net'].sum() if s in df['symbol'].values else 0):
    rv = df[df['symbol'] == sym]['r_net'].values
    n, wr, pf, tot = compute_stats(rv)
    print_row(sym, n, wr, pf, tot)

print(f'\n{"="*80}')
print('  PER-INSTRUMENT, HOLDOUT ONLY (>= 2025-02-01)')
print(f'{"="*80}')
oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]
for sym in sorted(loaded, key=lambda s: -oos_df[oos_df['symbol']==s]['r_net'].sum() if s in oos_df['symbol'].values else 0):
    rv = oos_df[oos_df['symbol'] == sym]['r_net'].values
    n, wr, pf, tot = compute_stats(rv)
    print_row(sym, n, wr, pf, tot)

print(f'\n{"="*80}')
print('  NY vs LONDON (all instruments combined)')
print(f'{"="*80}')
for session_name in SESSIONS:
    is_rv = df[(df['session']==session_name) & (df['entry_time'] < IS_OOS_SPLIT)]['r_net'].values
    oos_rv = df[(df['session']==session_name) & (df['entry_time'] >= IS_OOS_SPLIT)]['r_net'].values
    n, wr, pf, tot = compute_stats(is_rv)
    print_row(f'{session_name} IS', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_rv)
    print_row(f'{session_name} HOLDOUT', n, wr, pf, tot)

print(f'\n{"="*80}')
print('  HOW MANY INSTRUMENTS ARE ACTUALLY PROFITABLE?')
print(f'{"="*80}')
n_profitable = sum(1 for s in loaded if df[df['symbol']==s]['r_net'].sum() > 0)
print(f'  {n_profitable}/{len(loaded)} instruments net profitable overall')
n_profitable_oos = sum(1 for s in loaded if oos_df[oos_df['symbol']==s]['r_net'].sum() > 0)
print(f'  {n_profitable_oos}/{len(loaded)} instruments net profitable in holdout alone')

print('\nDone.')
