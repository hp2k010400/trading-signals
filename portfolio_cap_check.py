"""
portfolio_cap_check.py

Before applying the new 4-simultaneous-position cap to the live EA:
the validated 38,498-trade backtest never had any such limit, so the
cap could exclude trades that were genuinely part of the proven edge
(e.g. the 5th correlated trade firing at the same moment). Need to
know if capping actually costs meaningful performance before trusting
it live.

Generates the full trade set exactly as validated (same locked logic
as the live EA), but now also tracks each trade's real EXIT time (not
just entry), then walks through chronologically enforcing a max of
MAX_SIMULTANEOUS open positions at any moment -- exactly mimicking
what the EA's CountOpenPositions() check would actually do live.
Compares capped vs uncapped: trade count, WR, PF, and a walk-forward
check on the capped set too.

Run in Codespace: python -u portfolio_cap_check.py
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
MAX_SIMULTANEOUS = 4
WALK_FORWARD_MONTHS = 6

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
    """Same as validated logic, but also returns how many bars until exit
    so we can track the trade's real close time for concurrency purposes."""
    window_end = min(entry_index + 1 + max_minutes, len(m1))
    future = m1.iloc[entry_index + 1: window_end]
    if len(future) == 0:
        return -1.0, 0
    highs = future['high'].values
    lows  = future['low'].values
    closes = future['close'].values
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0.0, 0
    for k in range(len(future)):
        if direction == 1:
            if highs[k] >= tp_price: return RR, k
            if lows[k] <= stop_price: return -1.0, k
        else:
            if lows[k] <= tp_price: return RR, k
            if highs[k] >= stop_price: return -1.0, k
    final_close = closes[-1]
    r = ((final_close - entry_price) / stop_distance if direction == 1
         else (entry_price - final_close) / stop_distance)
    return r, len(future) - 1


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
            r_gross, bars_held = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                                    stop_price, tp_price, MAX_HOLD_MIN)
            cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
            entry_time = m1_index[entry_idx]
            exit_pos = min(entry_idx + 1 + bars_held, len(m1) - 1)
            exit_time = m1_index[exit_pos]
            trades.append({'symbol': symbol, 'entry_time': entry_time, 'exit_time': exit_time,
                            'r_net': r_gross - cost_r})
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

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades(symbol, session_hour))

df = pd.DataFrame(all_trades).sort_values('entry_time').reset_index(drop=True)
n, wr, pf, tot = compute_stats(df['r_net'].values)
print(f'{"="*80}')
print(f'  UNCAPPED (as validated -- no simultaneous-position limit)')
print(f'{"="*80}')
print(f'  Total trades: {n}   WR: {wr}%   PF: {pf}   Total R: {tot:+.1f}\n')

# ============================================================
#  Walk chronologically, enforcing the same cap the EA now applies
# ============================================================
open_exits = []   # exit times of currently "open" trades, kept sorted
kept_mask = []
skipped = 0
for _, row in df.iterrows():
    entry_t = row['entry_time']
    # drop any open positions that have already closed by this entry time
    open_exits = [t for t in open_exits if t > entry_t]
    if len(open_exits) >= MAX_SIMULTANEOUS:
        kept_mask.append(False)
        skipped += 1
        continue
    open_exits.append(row['exit_time'])
    kept_mask.append(True)

df_capped = df[pd.Series(kept_mask, index=df.index)].reset_index(drop=True)
n2, wr2, pf2, tot2 = compute_stats(df_capped['r_net'].values)
print(f'{"="*80}')
print(f'  CAPPED (max {MAX_SIMULTANEOUS} simultaneous positions -- matches the new EA logic)')
print(f'{"="*80}')
print(f'  Trades skipped due to cap: {skipped} ({skipped/len(df)*100:.2f}% of all trades)')
print(f'  Total trades: {n2}   WR: {wr2}%   PF: {pf2}   Total R: {tot2:+.1f}\n')

# ============================================================
#  Walk-forward on the CAPPED set
# ============================================================
print(f'{"#"*90}')
print(f'  WALK-FORWARD ON THE CAPPED TRADE SET ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
print(f'{"#"*90}')
df_capped['period'] = df_capped['entry_time'].dt.to_period('M')
all_periods = sorted(df_capped['period'].unique())
n_losing = 0
n_total = 0
for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
    window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
    label_suffix = ' (partial window)' if len(window_periods) < WALK_FORWARD_MONTHS else ''
    window_rv = df_capped[df_capped['period'].isin(window_periods)]['r_net'].values
    n, wr, pf, tot = compute_stats(window_rv)
    flag = ' <- LOSING' if tot < 0 else ''
    n_total += 1
    if tot < 0:
        n_losing += 1
    print(f'  {window_periods[0]} -> {window_periods[-1]}{label_suffix}   N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}{flag}')

print(f'\n  Losing windows: {n_losing}/{n_total}')
print('\nDone.')
