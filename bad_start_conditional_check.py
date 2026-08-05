"""
bad_start_conditional_check.py

Today (2026-08-05) the live account had a genuinely rough day: -£835.55
on a £70,501.90 start, -1.19%. User wants to know, specifically: out of
all the historically-grounded Monte Carlo account paths, what actually
happened in the ones where day 1 was ALSO a loss of similar size --
not the average across all paths, but conditioned specifically on
"started rough like this."

Same day-block bootstrap mechanic as the other Monte Carlo scripts,
same locked live settings (0.30% risk, 1.5x cost). The only difference
is we record each path's day-1 return and then filter down to the
subset where day 1 was a loss >= 1% (matching or worse than today),
and report the pass rate / days-to-pass distribution for THAT subset
specifically, next to the unconditional baseline for comparison.

Run in Codespace: python -u bad_start_conditional_check.py
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
MC_RUNS = 20000   # bigger sample since we're slicing into a subset
MAX_SIM_DAYS = 500
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
BAD_START_THRESHOLD = -0.01   # day-1 loss of 1%+ counts as "a bad start like today"

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


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades(symbol, session_hour))

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}\n')

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
    day1_return = None
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - BLOCK_DAYS))
        for b in range(BLOCK_DAYS):
            idx = start + b
            if idx >= n_days:
                break
            day_start_equity = equity
            for r in by_day[idx]:
                equity += equity * rpt * r
            day_ret = (equity - day_start_equity) / START_BAL
            if day1_return is None:
                day1_return = day_ret
            daily_loss = (day_start_equity - equity) / START_BAL
            if daily_loss > FTMO_DAILY:
                return 'FAILED_DAILY', day_i + 1, day1_return
            if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                return 'FAILED_TOTAL', day_i + 1, day1_return
            if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                return 'PASSED', day_i + 1, day1_return
            day_i += 1
            if day_i >= MAX_SIM_DAYS:
                break
    return 'TIMEOUT', MAX_SIM_DAYS, day1_return

rng = np.random.default_rng(11)
results = [simulate_one(rng) for _ in range(MC_RUNS)]
outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'day1_return'])

print(f'{"#"*90}')
print(f'  BASELINE (all {MC_RUNS} simulated account paths, unconditional)')
print(f'{"#"*90}')
n_pass = (outcomes['outcome']=='PASSED').sum()
passed = outcomes[outcomes['outcome']=='PASSED']
print(f'  Pass rate: {n_pass}/{MC_RUNS} ({n_pass/MC_RUNS*100:.2f}%)')
print(f'  Median days to pass: {passed["days"].median():.0f}   Mean: {passed["days"].mean():.1f}')

print(f'\n{"#"*90}')
print(f'  CONDITIONAL: only paths where DAY 1 was a loss of {BAD_START_THRESHOLD*100:.0f}%+ '
      f'(today was -1.19%)')
print(f'{"#"*90}')
bad_start = outcomes[outcomes['day1_return'] <= BAD_START_THRESHOLD]
print(f'  Paths matching "bad start like today": {len(bad_start)} '
      f'({len(bad_start)/MC_RUNS*100:.2f}% of all simulated paths)')

if len(bad_start) > 0:
    n_pass_bs = (bad_start['outcome']=='PASSED').sum()
    passed_bs = bad_start[bad_start['outcome']=='PASSED']
    n_daily_bs = (bad_start['outcome']=='FAILED_DAILY').sum()
    print(f'  Pass rate given a bad start: {n_pass_bs}/{len(bad_start)} ({n_pass_bs/len(bad_start)*100:.2f}%)')
    print(f'  Failed on daily limit (that same bad day): {n_daily_bs}/{len(bad_start)} ({n_daily_bs/len(bad_start)*100:.2f}%)')
    if len(passed_bs) > 0:
        print(f'\n  Days to pass, GIVEN a bad start:')
        print(f'    Median: {passed_bs["days"].median():.0f}   Mean: {passed_bs["days"].mean():.1f}')
        for p in [50, 75, 90, 95]:
            print(f'    {p}th percentile: {passed_bs["days"].quantile(p/100):.0f} days')
else:
    print('  No matching paths in this sample -- try a larger MC_RUNS or a less extreme threshold.')

print('\nDone.')
