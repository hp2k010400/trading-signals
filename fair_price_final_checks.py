"""
fair_price_final_checks.py

Combines the three remaining checks into one run:

  1. R:R SENSITIVITY -- we've only ever tested a fixed 1:1.5. Sweeps
     1.2/1.3/1.5/1.7/2.0 to see if nearby values also work (robust) or if
     performance collapses sharply away from 1.5 (a sign of overfitting
     to one specific number).

  2. ROLLING PF -- checks whether the edge (PF) has been stable across
     rolling 12-month windows through the ~8.5 year history, or quietly
     decaying as markets evolve.

  3. EXTRA INSTRUMENTS -- checks whether OANDA M1 data exists for the
     other symbols visible in your Market Watch (UK100, AUDUSD, AUDJPY,
     AUDNZD, AUDCAD, AUDCHF, USDCHF, USDCAD, NATGAS). Tests any that are
     actually present; clearly reports which ones are missing rather
     than silently skipping them.

Locked configuration throughout: 0.10% displacement threshold,
NY+London sessions, real-spread-calibrated costs at 1.5x.

Run in Codespace: python -u fair_price_final_checks.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
COST_MULT = 1.5
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

SESSIONS = {'LONDON': 8, 'NY': 13}

CORE_FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
CORE_COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
}

# candidate extra instruments -- filenames are guesses at the OANDA naming
# convention used all night; script reports which actually exist rather
# than assuming
EXTRA_CANDIDATES = {
    'UK100':  ('UK100_M1_oanda.csv', 8.0),
    'AUDUSD': ('AUDUSD_M1_oanda.csv', 0.00015),
    'AUDJPY': ('AUDJPY_M1_oanda.csv', 0.02),
    'AUDNZD': ('AUDNZD_M1_oanda.csv', 0.0002),
    'AUDCAD': ('AUDCAD_M1_oanda.csv', 0.0002),
    'AUDCHF': ('AUDCHF_M1_oanda.csv', 0.0002),
    'USDCHF': ('USDCHF_M1_oanda.csv', 0.00015),
    'USDCAD': ('USDCAD_M1_oanda.csv', 0.00015),
    'NATGAS': ('NATGAS_M1_oanda.csv', 0.005),
}

_m1 = {}

def load(symbol, fn):
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[symbol] = df.dropna()
    return True


def simulate_forward(m1, m1_index, entry_index, direction, entry_price, stop_price, tp_price, max_minutes, rr):
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
            if highs[k] >= tp_price: return rr
            if lows[k] <= stop_price: return -1.0
        else:
            if lows[k] <= tp_price: return rr
            if highs[k] >= stop_price: return -1.0
    final_close = closes[-1]
    return ((final_close - entry_price) / stop_distance if direction == 1
            else (entry_price - final_close) / stop_distance)


def find_reversion_trades(symbol, session_name, session_hour, rr, cost_points):
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
            tp_price = entry_price + stop_dist * rr if direction == 1 else entry_price - stop_dist * rr
            r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                        stop_price, tp_price, MAX_HOLD_MIN, rr)
            cost_r = cost_points / stop_dist * COST_MULT
            r_net = r_gross - cost_r
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_net})
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


print('Loading core 8 instruments...')
loaded_core = [s for s in CORE_FILES if load(s, CORE_FILES[s])]
print(f'Loaded: {loaded_core}\n')

# ============================================================
#  CHECK 1: R:R SENSITIVITY
# ============================================================
print(f'{"#"*90}')
print('  CHECK 1: R:R SENSITIVITY SWEEP')
print(f'{"#"*90}')
RR_SWEEP = [1.2, 1.3, 1.5, 1.7, 2.0]
for rr in RR_SWEEP:
    all_trades = []
    for session_name, session_hour in SESSIONS.items():
        for symbol in loaded_core:
            all_trades.extend(find_reversion_trades(symbol, session_name, session_hour, rr, CORE_COST_POINTS[symbol]))
    df = pd.DataFrame(all_trades)
    is_rv = df[df['entry_time'] < IS_OOS_SPLIT]['r_net'].values
    oos_rv = df[df['entry_time'] >= IS_OOS_SPLIT]['r_net'].values
    n_is, wr_is, pf_is, tot_is = compute_stats(is_rv)
    n_oos, wr_oos, pf_oos, tot_oos = compute_stats(oos_rv)
    print(f'  RR={rr:.1f}   IS: N={n_is:>6} WR={wr_is:>5.1f}% PF={pf_is:>5.2f}   '
          f'HOLDOUT: N={n_oos:>6} WR={wr_oos:>5.1f}% PF={pf_oos:>5.2f}')

# ============================================================
#  CHECK 2: ROLLING PF (12-month windows, RR=1.5 locked)
# ============================================================
print(f'\n{"#"*90}')
print('  CHECK 2: ROLLING 12-MONTH PF (RR=1.5, the locked configuration)')
print(f'{"#"*90}')
all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded_core:
        all_trades.extend(find_reversion_trades(symbol, session_name, session_hour, 1.5, CORE_COST_POINTS[symbol]))
df = pd.DataFrame(all_trades)
df['month'] = df['entry_time'].dt.to_period('M')

months_sorted = sorted(df['month'].unique())
for i in range(11, len(months_sorted)):
    window_months = months_sorted[i-11:i+1]
    window_rv = df[df['month'].isin(window_months)]['r_net'].values
    n, wr, pf, tot = compute_stats(window_rv)
    flag = ' <- LOSING WINDOW' if tot < 0 else ''
    print(f'  {window_months[0]} -> {window_months[-1]}   N={n:>6}  PF={pf:>5.2f}{flag}')

# ============================================================
#  CHECK 3: EXTRA INSTRUMENTS
# ============================================================
print(f'\n{"#"*90}')
print('  CHECK 3: EXTRA INSTRUMENTS (checking data availability first)')
print(f'{"#"*90}')
loaded_extra = []
for sym, (fn, cost) in EXTRA_CANDIDATES.items():
    if load(sym, fn):
        loaded_extra.append(sym)
        print(f'  {sym}: found ({fn}) -- will test')
    else:
        print(f'  {sym}: NOT FOUND ({fn} missing) -- skipped')

if loaded_extra:
    print(f'\n  Testing {len(loaded_extra)} extra instrument(s), RR=1.5, NY+London:')
    for symbol in loaded_extra:
        cost = EXTRA_CANDIDATES[symbol][1]
        trades = []
        for session_name, session_hour in SESSIONS.items():
            trades.extend(find_reversion_trades(symbol, session_name, session_hour, 1.5, cost))
        rdf = pd.DataFrame(trades)
        if len(rdf) == 0:
            print(f'    {symbol}: no trades found')
            continue
        is_rv = rdf[rdf['entry_time'] < IS_OOS_SPLIT]['r_net'].values
        oos_rv = rdf[rdf['entry_time'] >= IS_OOS_SPLIT]['r_net'].values
        n_is, wr_is, pf_is, tot_is = compute_stats(is_rv)
        n_oos, wr_oos, pf_oos, tot_oos = compute_stats(oos_rv)
        print(f'    {symbol}   IS: N={n_is:>6} PF={pf_is:>5.2f}   HOLDOUT: N={n_oos:>6} PF={pf_oos:>5.2f}')
else:
    print('\n  None of the extra instrument files exist in this Codespace -- would need downloading first.')

print('\nDone.')
