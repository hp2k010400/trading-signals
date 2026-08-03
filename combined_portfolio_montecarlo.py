"""
combined_portfolio_montecarlo.py

Tests whether combining the two SEPARATELY-validated real edges from
tonight beats either one alone -- same logic that proved equity-intraday
+ gold-NY-session beat both individual legs earlier (correlation +0.070,
blend Sharpe 0.030 vs 0.026/0.017 alone).

  LEG A: equity-intraday + gold-NY-session (always long, session open to
         close on DAX/NAS100/SP500/US30, NY session on gold, 3x ATR stop,
         0.75% risk/trade -- the first thing validated tonight).
  LEG B: fair-pricing displacement (NY+London reversion, 0.10% min
         displacement, 1:1.5 R:R, 0.08% risk/trade, real-spread-
         calibrated at 1.5x -- tonight's strongest result).

Computes the correlation between the two legs' daily returns first (the
actual test of whether combining them is real diversification or just
two good numbers side by side), then runs THREE Monte Carlos --
Leg A alone, Leg B alone, and BOTH COMBINED on the same day-bundles
(preserving real joint correlation, not assuming independence) -- to see
whether the combined book passes faster / more reliably than either
alone.

Run in Codespace: python -u combined_portfolio_montecarlo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 5000
MAX_SIM_DAYS = 500
BLOCK_DAYS = 5

# --- Leg A: equity-intraday + gold-NY-session ---
ATR_LEN = 20
ATR_MULT = 3.0
LEG_A_RISK_PCT = 0.75
EQUITY_FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
}
EQUITY_COST_POINTS = {'DAX': 1.5, 'NAS100': 1.5, 'SP500': 0.6, 'US30': 2.0}
GOLD_FILE = 'XAUUSD_M1_oanda.csv'
GOLD_COST_POINTS = 0.25
NY_START = 13

# --- Leg B: fair-pricing displacement ---
MIN_DISPLACEMENT_PCT = 0.0010
LEG_B_RISK_PCT = 0.08
LEG_B_COST_MULT = 1.5
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
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
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


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def build_equity_intraday(symbol):
    m1 = _m1[symbol]
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        o, c = daily['open'].iloc[i], daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or o <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = EQUITY_COST_POINTS[symbol] / stop_dist
        r = (c/o - 1) * o / stop_dist - cost_r
        out[daily.index[i].date()] = r
    return out


def build_gold_ny():
    m1 = _m1['GOLD']; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        day = daily.index[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = GOLD_COST_POINTS / stop_dist
        start_ts = day + pd.Timedelta(hours=NY_START)
        end_ts   = day + pd.Timedelta(days=1)
        s_idx = mi.searchsorted(start_ts); e_idx = mi.searchsorted(end_ts) - 1
        if s_idx >= len(m1) or e_idx >= len(m1) or e_idx <= s_idx: continue
        p_start = m1['close'].values[s_idx]; p_end = m1['close'].values[e_idx]
        if p_start <= 0: continue
        r = (p_end/p_start - 1) * p_start / stop_dist - cost_r
        out[day.date()] = r
    return out


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
            cost_r = COST_POINTS[symbol] / stop_dist * LEG_B_COST_MULT
            r_net = r_gross - cost_r
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_net})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)
    return trades


print('Loading OANDA M1 data...')
all_symbols = set(list(EQUITY_FILES.items())) | {('GOLD', GOLD_FILE)} | set(FILES.items())
for sym, fn in all_symbols:
    load(sym, fn)
print('Loaded.\n')

# --- Build Leg A day-bundles ---
print('Building Leg A (equity-intraday + gold-NY)...')
leg_a_per_instrument = {k: build_equity_intraday(k) for k in EQUITY_FILES}
leg_a_per_instrument['GOLD'] = build_gold_ny()
leg_a_days = {}
for k, series in leg_a_per_instrument.items():
    for d, r in series.items():
        leg_a_days.setdefault(d, []).append(r)
print(f'  Leg A trading days: {len(leg_a_days)}\n')

# --- Build Leg B day-bundles ---
print('Building Leg B (fair-pricing displacement)...')
leg_b_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in FILES:
        leg_b_trades.extend(find_reversion_trades(symbol, session_name, session_hour))
leg_b_df = pd.DataFrame(leg_b_trades)
leg_b_df['day'] = leg_b_df['entry_time'].dt.date
leg_b_days = {d: g['r_net'].values for d, g in leg_b_df.groupby('day')}
print(f'  Leg B trading days: {len(leg_b_days)}  ({len(leg_b_df)} trades)\n')

# --- Correlation check: daily aggregate return of each leg on common days ---
common_days = sorted(set(leg_a_days.keys()) & set(leg_b_days.keys()))
a_daily = np.array([np.mean(leg_a_days[d]) for d in common_days])
b_daily = np.array([np.mean(leg_b_days[d]) for d in common_days])
corr = np.corrcoef(a_daily, b_daily)[0, 1]
print(f'Common trading days: {len(common_days)}')
print(f'Correlation (Leg A daily avg R vs Leg B daily avg R): {corr:+.3f}')
if abs(corr) < 0.2:
    print('  -> Low correlation -- genuine diversification potential.\n')
elif abs(corr) < 0.5:
    print('  -> Moderate correlation -- some diversification benefit.\n')
else:
    print('  -> High correlation -- NOT a real diversifier.\n')

# --- Monte Carlo: Leg A alone, Leg B alone, Combined ---
all_days = sorted(set(leg_a_days.keys()) | set(leg_b_days.keys()))
n_days = len(all_days)


def simulate(rng, rpt_a, rpt_b, use_a, use_b, block_days):
    equity = START_BAL
    day_i = 0
    while day_i < MAX_SIM_DAYS:
        start = rng.integers(0, max(1, n_days - block_days))
        for b in range(block_days):
            idx = start + b
            if idx >= n_days:
                break
            d = all_days[idx]
            day_start_equity = equity
            if use_a and d in leg_a_days:
                for r in leg_a_days[d]:
                    equity += equity * rpt_a * r
            if use_b and d in leg_b_days:
                for r in leg_b_days[d]:
                    equity += equity * rpt_b * r
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


rpt_a = LEG_A_RISK_PCT / 100.0
rpt_b = LEG_B_RISK_PCT / 100.0

print(f'{"="*90}')
print(f'  {"Portfolio":>20}  {"PASSED":>8}  {"FAILED_DAILY":>13}  {"FAILED_TOTAL":>13}  {"Median days":>12}')
print(f'  {"-"*88}')

for label, use_a, use_b in [('Leg A alone', True, False), ('Leg B alone', False, True), ('COMBINED', True, True)]:
    rng = np.random.default_rng(7)
    results = [simulate(rng, rpt_a, rpt_b, use_a, use_b, BLOCK_DAYS) for _ in range(MC_RUNS)]
    outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'final_equity'])
    n_pass = (outcomes['outcome'] == 'PASSED').sum()
    n_daily = (outcomes['outcome'] == 'FAILED_DAILY').sum()
    n_total = (outcomes['outcome'] == 'FAILED_TOTAL').sum()
    passed = outcomes[outcomes['outcome'] == 'PASSED']
    med = passed['days'].median() if len(passed) else float('nan')
    print(f'  {label:>20}  {n_pass:>6}/{MC_RUNS}  {n_daily:>11}/{MC_RUNS}  '
          f'{n_total:>11}/{MC_RUNS}  {med:>12.0f}')

print(f'{"="*90}')
print('\nDone.')
