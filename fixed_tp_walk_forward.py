"""
fixed_tp_walk_forward.py

The FIXED entry/TP logic (target and cost both recomputed against the
TRUE entry-to-stop distance, not the stale signal-candle-close
distance) showed a big aggregate jump on the full dataset -- PF 1.688
-> 3.418, WR 63.19% -> 77.84%. Too large a claim to accept from one
aggregate number alone, especially tonight. Same discipline as the
original strategy validation: non-overlapping 6-month walk-forward
across the full 8.5yr history, plus Monte Carlo at the live 0.30%
risk setting, using the FIXED logic exclusively.

If this holds up across walk-forward windows the same way the
original logic did (most/all windows profitable, no single period
carrying the whole result), that's real evidence the fix is genuine.
If a couple of windows are doing all the work, that's a red flag the
aggregate number is misleading.

Run in Codespace: python -u fixed_tp_walk_forward.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RR = 1.2
COST_MULT = 1.5
RISK_PCT = 0.30
BLOCK_DAYS = 5
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 5000
MAX_SIM_DAYS = 500
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
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


def find_reversion_trades_FIXED(symbol, session_hour):
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
            true_stop_dist = abs(entry_price - stop_price)
            if true_stop_dist <= 0 or true_stop_dist / entry_price < MIN_DISPLACEMENT_PCT:
                continue
            tp_price = entry_price + true_stop_dist * RR if direction == 1 else entry_price - true_stop_dist * RR
            r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                        stop_price, tp_price, MAX_HOLD_MIN)
            cost_r = COST_POINTS[symbol] / true_stop_dist * COST_MULT
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_gross - cost_r})
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


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades_FIXED(symbol, session_hour))

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}\n')

n, wr, pf, tot = compute_stats(df['r_net'].values)
print(f'Overall: N={n}  WR={wr}%  PF={pf}  Total R={tot:+.1f}\n')

# ============================================================
#  PART 1: WALK-FORWARD (non-overlapping 6-month windows)
# ============================================================
print(f'{"#"*90}')
print(f'  PART 1: WALK-FORWARD VALIDATION OF THE FIXED LOGIC ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
print(f'{"#"*90}')
df['period'] = df['entry_time'].dt.to_period('M')
all_periods = sorted(df['period'].unique())
n_losing_windows = 0
n_total_windows = 0
for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
    window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
    label_suffix = ' (partial window)' if len(window_periods) < WALK_FORWARD_MONTHS else ''
    window_rv = df[df['period'].isin(window_periods)]['r_net'].values
    n, wr, pf, tot = compute_stats(window_rv)
    flag = ' <- LOSING' if tot < 0 else ''
    n_total_windows += 1
    if tot < 0:
        n_losing_windows += 1
    print(f'  {window_periods[0]} -> {window_periods[-1]}{label_suffix}   N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}{flag}')

print(f'\n  Losing windows: {n_losing_windows}/{n_total_windows}')

# ============================================================
#  PART 2: MONTE CARLO AT LIVE SETTING (0.30% risk) -- FIXED logic
# ============================================================
print(f'\n{"#"*90}')
print(f'  PART 2: MONTE CARLO AT LIVE SETTING (Risk={RISK_PCT}%, Cost={COST_MULT}x) -- FIXED logic')
print(f'{"#"*90}')

df['day'] = df['entry_time'].dt.date
days_sorted = sorted(df['day'].unique())
day_index = {d: i for i, d in enumerate(days_sorted)}
n_days = len(days_sorted)
by_day = [None] * n_days
for d, g in df.groupby('day'):
    by_day[day_index[d]] = g['r_net'].values

rpt = RISK_PCT / 100.0

def simulate_one(rng):
    equity = START_BAL
    day_i = 0
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - BLOCK_DAYS))
        for b in range(BLOCK_DAYS):
            idx = start + b
            if idx >= n_days:
                break
            day_start_equity = equity
            for r in by_day[idx]:
                equity += equity * rpt * r
            daily_loss = (day_start_equity - equity) / START_BAL
            if daily_loss > FTMO_DAILY:
                return 'FAILED_DAILY', day_i + 1
            if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                return 'FAILED_TOTAL', day_i + 1
            if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                return 'PASSED', day_i + 1
            day_i += 1
            if day_i >= MAX_SIM_DAYS:
                break
    return 'TIMEOUT', MAX_SIM_DAYS

rng = np.random.default_rng(7)
results = [simulate_one(rng) for _ in range(MC_RUNS)]
outcomes = pd.DataFrame(results, columns=['outcome', 'days'])
n_pass = (outcomes['outcome']=='PASSED').sum()
passed = outcomes[outcomes['outcome']=='PASSED']

print(f'  PASSED: {n_pass}/{MC_RUNS} ({n_pass/MC_RUNS*100:.2f}%)')
if len(passed) > 0:
    print(f'  Median days to pass: {passed["days"].median():.0f}   Mean: {passed["days"].mean():.1f}')

print('\nDone.')
