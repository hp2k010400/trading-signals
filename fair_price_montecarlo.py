"""
fair_price_montecarlo.py

The fair-pricing displacement REVERSION signal (NY + London sessions only
-- Asian was negative in-sample, dropped rather than cherry-picked) showed
real numbers: PF 1.09 IS -> 1.24 holdout, both sessions positive and
STRONGER out-of-sample. But the raw £4.3M headline from the trade-level
script is fake -- it assumes every one of ~200k trades could be taken
independently with unlimited capital, when in reality it fires 80-100+
times a day across 8 correlated instruments (equity indices mostly move
together).

This bootstraps by WHOLE TRADING DAY (not by individual trade), same
method as ftmo_montecarlo.py -- every trade that entered on a given day,
across every instrument and both sessions, is bundled together and
resampled as a unit. That's what actually preserves the real correlation
structure instead of overstating how much independent evidence 200k
correlated trades really represents.

Because this signal is MUCH higher-frequency than the equity+gold blend
(dozens of trades/day vs ~1-5), the risk-per-trade sweep is much smaller.

FTMO rules: £70,000 start, +10% target, 5% daily loss limit, 10% max
total drawdown.

Run in Codespace: python -u fair_price_montecarlo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

RISK_SWEEP = [0.02, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30]   # % risk per trade
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 5000
MAX_SIM_DAYS = 500

RR = 1.5
REVERSION_WINDOW_MIN = 90
MIN_DISPLACEMENT_PCT = 0.0004
MAX_HOLD_MIN = 240

SESSIONS = {   # Asian dropped -- negative in-sample, not cherry-picked back in
    'LONDON': 8,
    'NY':     13,
}

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
        return -1.0, 'SL'
    highs = future['high'].values
    lows  = future['low'].values
    closes = future['close'].values
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0.0, 'SL'
    for k in range(len(future)):
        if direction == 1:
            if highs[k] >= tp_price:
                return RR, 'TP'
            if lows[k] <= stop_price:
                return -1.0, 'SL'
        else:
            if lows[k] <= tp_price:
                return RR, 'TP'
            if highs[k] >= stop_price:
                return -1.0, 'SL'
    final_close = closes[-1]
    r = ((final_close - entry_price) / stop_distance if direction == 1
         else (entry_price - final_close) / stop_distance)
    return r, 'TIMEOUT'


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
            body_cur = abs(bodies[i])
            body_prev = abs(bodies[i-1])
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

            r, reason = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                          stop_price, tp_price, MAX_HOLD_MIN)
            cost_r = COST_POINTS[symbol] / stop_dist
            r_net = r - cost_r
            trades.append({'symbol': symbol, 'session': session_name,
                           'entry_time': m1_index[entry_idx], 'r_net': r_net})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)

    return trades


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        trades = find_reversion_trades(symbol, session_name, session_hour)
        print(f'  {session_name} {symbol}: {len(trades)} trades')
        all_trades.extend(trades)

print(f'\nTotal trades: {len(all_trades)}')

df = pd.DataFrame(all_trades)
df['day'] = df['entry_time'].dt.date

day_bundles = [g['r_net'].values for _, g in df.groupby('day')]
day_bundles = [b for b in day_bundles if len(b) > 0]
print(f'Trading days with at least one signal: {len(day_bundles)}')
avg_trades_per_day = np.mean([len(b) for b in day_bundles])
print(f'Average trades/day across all instruments+sessions: {avg_trades_per_day:.1f}\n')


def simulate_one(rng, rpt):
    equity = START_BAL
    peak = START_BAL
    for day_i in range(MAX_SIM_DAYS):
        bundle = day_bundles[rng.integers(0, len(day_bundles))]
        day_start_equity = equity
        for r in bundle:
            equity += equity * rpt * r
        peak = max(peak, equity)
        daily_loss = (day_start_equity - equity) / START_BAL
        if daily_loss > FTMO_DAILY:
            return 'FAILED_DAILY', day_i + 1, equity
        if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
            return 'FAILED_TOTAL', day_i + 1, equity
        if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
            return 'PASSED', day_i + 1, equity
    return 'TIMEOUT', MAX_SIM_DAYS, equity


print(f'Sweeping risk-per-trade: {RISK_SWEEP} (%), {MC_RUNS:,} runs each, bootstrapped by whole trading day')
print(f'{"="*90}')
print(f'  {"Risk/trade":>10}  {"PASSED":>8}  {"FAILED_DAILY":>13}  {"FAILED_TOTAL":>13}  '
      f'{"TIMEOUT":>8}  {"Median days":>12}  {"P10 days":>9}  {"P90 days":>9}')
print(f'  {"-"*88}')

sweep_results = []
for risk_pct in RISK_SWEEP:
    rpt = risk_pct / 100.0
    rng = np.random.default_rng(7)
    results = [simulate_one(rng, rpt) for _ in range(MC_RUNS)]
    outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'final_equity'])

    n_pass = (outcomes['outcome'] == 'PASSED').sum()
    n_daily = (outcomes['outcome'] == 'FAILED_DAILY').sum()
    n_total = (outcomes['outcome'] == 'FAILED_TOTAL').sum()
    n_timeout = (outcomes['outcome'] == 'TIMEOUT').sum()
    passed = outcomes[outcomes['outcome'] == 'PASSED']
    med = passed['days'].median() if len(passed) else float('nan')
    p10 = passed['days'].quantile(0.10) if len(passed) else float('nan')
    p90 = passed['days'].quantile(0.90) if len(passed) else float('nan')

    sweep_results.append({'risk_pct': risk_pct, 'pass_rate': n_pass/MC_RUNS*100, 'median_days': med})

    print(f'  {risk_pct:>9.2f}%  {n_pass:>6}/{MC_RUNS}  {n_daily:>11}/{MC_RUNS}  '
          f'{n_total:>11}/{MC_RUNS}  {n_timeout:>6}/{MC_RUNS}  {med:>12.0f}  {p10:>9.0f}  {p90:>9.0f}')

print(f'{"="*90}')
sr = pd.DataFrame(sweep_results)
best_pass = sr.loc[sr['pass_rate'].idxmax()]
print(f'\n  Best pass rate: {best_pass["risk_pct"]:.2f}% risk/trade '
      f'-> {best_pass["pass_rate"]:.1f}% pass rate, median {best_pass["median_days"]:.0f} days')
print('\nDone.')
