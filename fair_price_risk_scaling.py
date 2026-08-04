"""
fair_price_risk_scaling.py

Goal: get median monthly income from ~£3,131 (at 0.08% risk) up toward
£5-6k -- WITHOUT hunting for a new signal. This turns up the risk dial
on the already-validated fair-pricing displacement strategy instead,
which is a fundamentally safer test than another hypothesis: no new
false-positive risk, just checking how far a PROVEN edge can scale
before it starts hitting real safety limits (specifically FTMO's 5%
daily loss limit).

Sweeps risk/trade: 0.08% (current), 0.12%, 0.16%, 0.20%, 0.24%.
At each level, reports BOTH:
  1. Monte Carlo safety check (pass rate, FAILED_DAILY rate specifically
     -- this is the real ceiling, not an assumption) at realistic 1.5x
     cost stress.
  2. Real median/mean monthly £ income, walked through the actual
     ~8.5yr calendar history (same method as fair_price_monthly_pnl.py),
     at each risk level -- not a linear-scaling guess.

Locked configuration otherwise unchanged: 0.10% displacement threshold,
NY+London, RR=1.2, real-spread-calibrated costs.

Run in Codespace: python -u fair_price_risk_scaling.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RR = 1.2
COST_MULT = 1.5   # realistic middle stress scenario, fixed throughout this sweep
RISK_SWEEP = [0.08, 0.12, 0.16, 0.20, 0.24]
BLOCK_DAYS = 5
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 3000
MAX_SIM_DAYS = 500
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
            raw_cost_r = COST_POINTS[symbol] / stop_dist
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx],
                           'r_gross': r_gross, 'raw_cost_r': raw_cost_r})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)
    return trades


def simulate_one(rng, rpt, by_day_gross, by_day_cost, n_days, block_days):
    equity = START_BAL
    day_i = 0
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - block_days))
        for b in range(block_days):
            idx = start + b
            if idx >= n_days:
                break
            r_net_day = by_day_gross[idx] - by_day_cost[idx] * COST_MULT
            day_start_equity = equity
            for r in r_net_day:
                equity += equity * rpt * r
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

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades(symbol, session_name, session_hour))

df = pd.DataFrame(all_trades)
print(f'Total trades: {len(df)}\n')

df['day'] = df['entry_time'].dt.date
days_sorted = sorted(df['day'].unique())
day_index = {d: i for i, d in enumerate(days_sorted)}
n_days = len(days_sorted)
by_day_gross = [None] * n_days
by_day_cost = [None] * n_days
for d, g in df.groupby('day'):
    by_day_gross[day_index[d]] = g['r_gross'].values
    by_day_cost[day_index[d]] = g['raw_cost_r'].values

df['month'] = df['entry_time'].dt.to_period('M')

print(f'{"="*100}')
print(f'  RISK SCALING SWEEP (all at {COST_MULT}x realistic cost stress)')
print(f'{"="*100}')
print(f'  {"Risk/trade":>10}  {"£/R":>8}  {"PASSED":>8}  {"FAILED_DAILY":>13}  {"Median days":>12}  '
      f'{"Median £/month":>15}  {"Mean £/month":>14}')
print(f'  {"-"*98}')

for risk_pct in RISK_SWEEP:
    rpt = risk_pct / 100.0
    risk_per_r = START_BAL * rpt

    # Monte Carlo safety check
    rng = np.random.default_rng(7)
    results = [simulate_one(rng, rpt, by_day_gross, by_day_cost, n_days, BLOCK_DAYS) for _ in range(MC_RUNS)]
    outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'final_equity'])
    n_pass = (outcomes['outcome'] == 'PASSED').sum()
    n_daily = (outcomes['outcome'] == 'FAILED_DAILY').sum()
    passed = outcomes[outcomes['outcome'] == 'PASSED']
    med_days = passed['days'].median() if len(passed) else float('nan')

    # real monthly walkthrough at this risk level
    monthly_pnls = []
    for month, g in df.groupby('month'):
        equity = START_BAL
        for _, row in g.sort_values('entry_time').iterrows():
            r_net = row['r_gross'] - row['raw_cost_r'] * COST_MULT
            equity += equity * rpt * r_net
        monthly_pnls.append(equity - START_BAL)
    monthly_pnls = np.array(monthly_pnls)
    med_month = np.median(monthly_pnls)
    mean_month = np.mean(monthly_pnls)

    print(f'  {risk_pct:>9.2f}%  £{risk_per_r:>6.0f}  {n_pass:>6}/{MC_RUNS}  {n_daily:>11}/{MC_RUNS}  '
          f'{med_days:>12.0f}  £{med_month:>+13,.0f}  £{mean_month:>+12,.0f}')

print(f'{"="*100}')
print('\nDone.')
