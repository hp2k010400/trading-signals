"""
fair_price_size_sweep.py

The fair-pricing displacement signal looked bulletproof at 1x estimated
cost (94-100% pass rate) but collapsed to under 8% pass rate at 2x cost,
and under 1.5% at 3x cost. That's because the fixed point-cost eats a
bigger share of a SMALL displacement candle's stop distance than a big
one -- cost is fixed in points, stop distance scales with the move.

This sweeps the minimum-displacement-size filter (currently 0.04% of
price -- basically "any candle bigger than the last one") up to 0.10%
and 0.20%, trading frequency for robustness: fewer, larger, cleaner
signals where the same fixed cost is a much smaller fraction of risk.
For each threshold, re-runs the same 2x/3x cost stress test to see
whether there's a size where the edge survives being handicapped instead
of only working under optimistic cost assumptions.

Only NY + London sessions (Asian already dropped), only the two risk
levels actually under consideration (0.05%, 0.08%), 5-day block bootstrap
throughout -- narrowed scope specifically to keep this a single
practical run given how long the full trade-finding pass already takes.

Run in Codespace: python -u fair_price_size_sweep.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SIZE_SWEEP = [0.0004, 0.0010, 0.0020]   # current baseline, 2.5x, 5x
RISK_LEVELS = [0.05, 0.08]
COST_MULTIPLIERS = [1.0, 2.0, 3.0]
BLOCK_DAYS = 5
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 2000
MAX_SIM_DAYS = 500

RR = 1.5
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
    'DAX':1.5, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.00015, 'GBPUSD':0.00020, 'USDJPY':0.02, 'GOLD':0.25,
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
            if highs[k] >= tp_price:
                return RR
            if lows[k] <= stop_price:
                return -1.0
        else:
            if lows[k] <= tp_price:
                return RR
            if highs[k] >= stop_price:
                return -1.0
    final_close = closes[-1]
    return ((final_close - entry_price) / stop_distance if direction == 1
            else (entry_price - final_close) / stop_distance)


def find_reversion_trades(symbol, session_name, session_hour, min_displacement_pct):
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
            body_cur = abs(bodies[i])
            body_prev = abs(bodies[i-1])
            if body_cur <= body_prev:
                continue
            px = float(closes[i])
            if px <= 0 or body_cur / px < min_displacement_pct:
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
            raw_cost_r = COST_POINTS[symbol] / stop_dist
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx],
                           'r_gross': r_gross, 'raw_cost_r': raw_cost_r})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)

    return trades


def simulate_one(rng, rpt, cost_mult, block_days, by_day_gross, by_day_cost, n_days):
    equity = START_BAL
    peak = START_BAL
    day_i = 0
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - block_days))
        for b in range(block_days):
            idx = start + b
            if idx >= n_days:
                break
            gross = by_day_gross[idx]
            cost = by_day_cost[idx] * cost_mult
            r_net_day = gross - cost
            day_start_equity = equity
            for r in r_net_day:
                equity += equity * rpt * r
            peak = max(peak, equity)
            daily_loss = (day_start_equity - equity) / START_BAL
            if daily_loss > FTMO_DAILY:
                return 'FAILED_DAILY', day_i + 1, equity
            if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                return 'FAILED_TOTAL', day_i + 1, equity
            if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                return 'PASSED', day_i + 1, equity
            day_i += 1
            if day_i >= MAX_SIM_DAYS:
                break
    return 'TIMEOUT', MAX_SIM_DAYS, equity


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

for min_disp in SIZE_SWEEP:
    print(f'{"#"*100}')
    print(f'  MIN_DISPLACEMENT_PCT = {min_disp*100:.2f}%')
    print(f'{"#"*100}')

    all_trades = []
    for session_name, session_hour in SESSIONS.items():
        for symbol in loaded:
            trades = find_reversion_trades(symbol, session_name, session_hour, min_disp)
            all_trades.extend(trades)

    df = pd.DataFrame(all_trades)
    if len(df) == 0:
        print('  No trades at this threshold.\n')
        continue
    n_days_total = (df['entry_time'].max() - df['entry_time'].min()).days
    avg_per_day = len(df) / max(1, n_days_total) * 7 / 5   # rough weekday-adjusted

    df['r_net_1x'] = df['r_gross'] - df['raw_cost_r']
    wins = df[df['r_net_1x'] > 0]['r_net_1x']
    losses = df[df['r_net_1x'] <= 0]['r_net_1x']
    pf_1x = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    print(f'  Total trades: {len(df)}  |  ~{avg_per_day:.1f}/weekday  |  PF at 1x cost: {pf_1x}')

    df['day'] = df['entry_time'].dt.date
    days_sorted = sorted(df['day'].unique())
    day_index = {d: i for i, d in enumerate(days_sorted)}
    n_days = len(days_sorted)
    by_day_gross = [None] * n_days
    by_day_cost = [None] * n_days
    for d, g in df.groupby('day'):
        by_day_gross[day_index[d]] = g['r_gross'].values
        by_day_cost[day_index[d]] = g['raw_cost_r'].values

    print(f'\n  {"Risk/trade":>10}  {"Cost x":>7}  {"PASSED":>8}  {"FAILED_DAILY":>13}  {"FAILED_TOTAL":>13}  {"Median days":>12}')
    print(f'  {"-"*80}')
    for risk_pct in RISK_LEVELS:
        rpt = risk_pct / 100.0
        for cost_mult in COST_MULTIPLIERS:
            rng = np.random.default_rng(7)
            results = [simulate_one(rng, rpt, cost_mult, BLOCK_DAYS, by_day_gross, by_day_cost, n_days)
                       for _ in range(MC_RUNS)]
            outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'final_equity'])
            n_pass = (outcomes['outcome'] == 'PASSED').sum()
            n_daily = (outcomes['outcome'] == 'FAILED_DAILY').sum()
            n_total = (outcomes['outcome'] == 'FAILED_TOTAL').sum()
            passed = outcomes[outcomes['outcome'] == 'PASSED']
            med = passed['days'].median() if len(passed) else float('nan')
            print(f'  {risk_pct:>9.2f}%  {cost_mult:>6.1f}x  {n_pass:>6}/{MC_RUNS}  {n_daily:>11}/{MC_RUNS}  '
                  f'{n_total:>11}/{MC_RUNS}  {med:>12.0f}')
        print(f'  {"-"*80}')
    print()

print('Done.')
