"""
news_breakout_challenge_montecarlo_ftmo.py

Tests the reframed challenge-passing question: pairs_challenge_montecarlo
_ftmo.py showed the pairs strategy trades too rarely (~1/month) to
reliably pass a time-limited FTMO challenge, no matter the risk level --
most attempts TIMEOUT, not fail on risk. News-breakout has a much
weaker/roughly-breakeven long-run edge (blind holdout PF 1.01) but
trades far more often (124,000+ trades across the full universe vs 191
for the pairs). For PASSING A CHALLENGE specifically -- a one-shot,
short-horizon objective, not a "build a sustainable business" one --
raw trade frequency combined with even a marginal edge might give a
meaningfully better shot than a strategy with a real edge but almost no
trades. This checks that directly instead of assuming either answer.

Same trade-generation pipeline as news_breakout_indices_ftmo.py
(identical mechanism, instruments, cluster risk-sizing), swapped onto
the same real-historical-window bootstrap Monte Carlo used for the
pairs strategy: each simulation picks a random real 30/60-day window
from actual history and checks FTMO-style daily/max-loss/profit-target
rules against the REAL trades that occurred in it.

Run in Codespace: python -u news_breakout_challenge_montecarlo_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
CALENDAR_UTC_OFFSET_HOURS = 3

BREAKOUT_ATR_MULT = 0.5
ATR_STOP_MULT = 1.0
RR = 1.5
COST_MULT = 1.5
WATCH_MINUTES = 30
MAX_HOLD_HOURS = 4
ATR_PERIOD = 14
MIN_STOP_DIST_PCT = 0.0005

CALENDAR_FILE = 'HighImpactCalendar.csv'

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'NATGAS':'NATGAS_cash_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'WTIOIL':  'WTIOIL_M1_ftmo.csv',
    'BRENTOIL':'BRENTOIL_M1_ftmo.csv',
    'SILVER':  'SILVER_M1_ftmo.csv',
    'COPPER':  'COPPER_M1_ftmo.csv',
    'PLATINUM':'PLATINUM_M1_ftmo.csv',
    'PALLADIUM':'PALLADIUM_M1_ftmo.csv',
    'USDINDEX':'USDINDEX_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0, 'UK100':1.8, 'NATGAS':0.008,
    'FRA40':1.5, 'JP225':8.0, 'AUS200':2.0, 'EU50':1.2, 'US2000':0.4, 'HK50':10.0,
    'WTIOIL':0.04, 'BRENTOIL':0.04, 'SILVER':0.025, 'COPPER':0.008,
    'PLATINUM':0.5, 'PALLADIUM':2.0, 'USDINDEX':0.02,
}
CURRENCY_MAP = {
    'USD': ['NAS100','SP500','US30','US2000','DAX','UK100','FRA40','EU50','JP225','AUS200','HK50',
             'WTIOIL','BRENTOIL','SILVER','COPPER','PLATINUM','PALLADIUM','USDINDEX'],
    'EUR': ['DAX','FRA40','EU50'],
    'GBP': ['UK100'],
    'JPY': ['JP225'],
    'AUD': ['AUS200'],
}


def load_price(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None, None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    prev_close = h1['close'].shift(1)
    tr = pd.concat([h1['high']-h1['low'], (h1['high']-prev_close).abs(), (h1['low']-prev_close).abs()], axis=1).max(axis=1)
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    h1 = h1.dropna()
    return df, h1


def is_gas_storage(name):
    n = str(name).upper()
    return ('NATURAL GAS' in n) or ('GAS STORAGE' in n)


def is_crude_oil(name):
    n = str(name).upper()
    return ('CRUDE OIL' in n) or ('CRUDE INVENTORIES' in n) or ('OIL INVENTORIES' in n)


def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        return None
    df = pd.read_csv(CALENDAR_FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=CALENDAR_UTC_OFFSET_HOURS)
    df = df.drop_duplicates(subset=['currency', 'event_name', 'time'])
    return df.sort_values('time').reset_index(drop=True)


def find_trade_for_event(symbol, m1, h1, event_time):
    m1_index = m1.index
    h1_index = h1.index
    h1_pos = h1_index.searchsorted(event_time) - 1
    if h1_pos < 0 or h1_pos >= len(h1):
        return None
    atr = h1.iloc[h1_pos]['atr']
    if pd.isna(atr) or atr <= 0:
        return None
    m1_pos = m1_index.searchsorted(event_time)
    if m1_pos <= 0 or m1_pos >= len(m1):
        return None
    ref_price = float(m1['close'].iloc[m1_pos - 1])
    trigger_up = ref_price + BREAKOUT_ATR_MULT * atr
    trigger_down = ref_price - BREAKOUT_ATR_MULT * atr
    watch_end = min(m1_pos + WATCH_MINUTES, len(m1))
    watch = m1.iloc[m1_pos:watch_end]
    if len(watch) == 0:
        return None
    direction = 0; entry_price = None; entry_pos = None
    highs = watch['high'].values; lows = watch['low'].values
    for k in range(len(watch)):
        hit_up = highs[k] >= trigger_up
        hit_down = lows[k] <= trigger_down
        if hit_up and hit_down:
            return None
        if hit_up:
            direction = 1; entry_price = trigger_up; entry_pos = m1_pos + k; break
        if hit_down:
            direction = -1; entry_price = trigger_down; entry_pos = m1_pos + k; break
    if direction == 0:
        return None
    stop_dist = ATR_STOP_MULT * atr
    if stop_dist < ref_price * MIN_STOP_DIST_PCT:
        return None
    stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
    tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR
    window_end = min(entry_pos + 1 + MAX_HOLD_HOURS * 60, len(m1))
    future = m1.iloc[entry_pos + 1: window_end]
    r_gross = None
    if len(future) > 0:
        fh = future['high'].values; fl = future['low'].values; fc = future['close'].values
        for k in range(len(future)):
            if direction == 1:
                if fh[k] >= tp_price: r_gross = RR; break
                if fl[k] <= stop_price: r_gross = -1.0; break
            else:
                if fl[k] <= tp_price: r_gross = RR; break
                if fh[k] >= stop_price: r_gross = -1.0; break
        if r_gross is None:
            final_close = fc[-1]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)
            r_gross = max(-2.0, min(RR + 0.5, r_gross))
    else:
        r_gross = -1.0
    cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
    return {'symbol': symbol, 'entry_time': m1_index[entry_pos], 'r_net': r_gross - cost_r}


print('Loading calendar + generating real trade history (same pipeline as news_breakout_indices_ftmo.py)...')
cal = load_calendar()
if cal is None:
    raise SystemExit(f'{CALENDAR_FILE} not found -- upload it first.')

cal_gas = cal[cal['event_name'].apply(is_gas_storage)]
cal_oil = cal[cal['event_name'].apply(is_crude_oil)]
cal_macro = cal[~cal['event_name'].apply(is_gas_storage) & ~cal['event_name'].apply(is_crude_oil)]

events_for_symbol = {s: [] for s in FILES}
events_for_symbol['NATGAS'] = list(cal_gas['time'])
events_for_symbol['WTIOIL'] = list(cal_oil['time'])
events_for_symbol['BRENTOIL'] = list(cal_oil['time'])
for currency, symbols in CURRENCY_MAP.items():
    times = list(cal_macro[cal_macro['currency'] == currency]['time'])
    for s in symbols:
        events_for_symbol[s].extend(times)

all_trades = []
loaded = []
for symbol in FILES:
    ev_times = events_for_symbol.get(symbol, [])
    if not ev_times or not os.path.exists(FILES[symbol]):
        continue
    m1, h1 = load_price(symbol)
    if m1 is None:
        continue
    loaded.append(symbol)
    for t in ev_times:
        trade = find_trade_for_event(symbol, m1, h1, t)
        if trade is not None:
            trade['event_time'] = t
            all_trades.append(trade)
    del m1, h1
    gc.collect()
    print(f'  {symbol}: done')

trades_df = pd.DataFrame(all_trades)
if len(trades_df) == 0:
    raise SystemExit('No trades generated -- check CSVs and calendar file are present.')
trades_df = trades_df.sort_values('entry_time').reset_index(drop=True)
trades_df['date'] = trades_df['entry_time'].dt.normalize()

# Same cluster risk-sizing as news_breakout_indices_ftmo.py: total risk for
# an event is split across however many correlated instruments react to it,
# parameterized here by the swept risk level instead of a fixed 0.30%.
cluster_size = trades_df.groupby('event_time')['symbol'].transform('count')
trades_df['cluster_size'] = cluster_size

print(f'\nTotal real trades: {len(trades_df)}')
print(f'Date range: {trades_df["entry_time"].min().date()} -> {trades_df["entry_time"].max().date()}')
print(f'Loaded {len(loaded)} instruments: {loaded}')

START_BAL = 70000.0
MAX_DAILY_LOSS_PCT = 0.05
MAX_TOTAL_LOSS_PCT = 0.10
CHALLENGE_CONFIGS = [
    (30, 0.10),   # approximates FTMO Phase 1 -- verify against your real account rules
    (60, 0.05),   # approximates FTMO Phase 2
]
RISK_LEVELS_PCT = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0]
N_SIMULATIONS = 2000

data_start = trades_df['entry_time'].min()
data_end = trades_df['entry_time'].max()
rng = np.random.default_rng(42)


def simulate_window(window_days, profit_target_pct, risk_pct):
    max_start = data_end - pd.Timedelta(days=window_days)
    if max_start <= data_start:
        return None
    total_span_days = (max_start - data_start).days
    start_offset = rng.integers(0, total_span_days + 1)
    start_date = data_start + pd.Timedelta(days=int(start_offset))
    end_date = start_date + pd.Timedelta(days=window_days)

    window_trades = trades_df[(trades_df['entry_time'] >= start_date) & (trades_df['entry_time'] < end_date)]
    n_trades = len(window_trades)

    equity = START_BAL
    daily_start_balance = START_BAL
    current_day = None

    for _, row in window_trades.iterrows():
        if row['date'] != current_day:
            daily_start_balance = equity
            current_day = row['date']

        trade_risk_pct = (risk_pct / row['cluster_size']) / 100.0
        equity += equity * trade_risk_pct * row['r_net']

        if (daily_start_balance - equity) / daily_start_balance >= MAX_DAILY_LOSS_PCT:
            return 'FAIL_DAILY', n_trades
        if (START_BAL - equity) / START_BAL >= MAX_TOTAL_LOSS_PCT:
            return 'FAIL_MAXLOSS', n_trades
        if (equity - START_BAL) / START_BAL >= profit_target_pct:
            return 'PASS', n_trades

    return 'TIMEOUT', n_trades


print(f'\n{"#"*100}')
print(f'  MONTE CARLO: {N_SIMULATIONS} simulated challenge windows per (window length, risk level)')
print(f'  Rules: {MAX_DAILY_LOSS_PCT*100:.0f}% max daily loss, {MAX_TOTAL_LOSS_PCT*100:.0f}% max total loss (static)')
print(f'{"#"*100}')

for window_days, profit_target_pct in CHALLENGE_CONFIGS:
    print(f'\n--- {window_days}-day window, {profit_target_pct*100:.0f}% profit target '
          f'(approximates FTMO {"Phase 1" if window_days == 30 else "Phase 2"} -- verify against your real account rules) ---')
    print(f'  {"Risk%":>6}  {"PASS":>7}  {"FAIL_DAILY":>10}  {"FAIL_MAXLOSS":>12}  {"TIMEOUT":>8}  {"AvgTrades":>9}')
    for risk_pct in RISK_LEVELS_PCT:
        outcomes = {'PASS': 0, 'FAIL_DAILY': 0, 'FAIL_MAXLOSS': 0, 'TIMEOUT': 0}
        trade_counts = []
        for _ in range(N_SIMULATIONS):
            result = simulate_window(window_days, profit_target_pct, risk_pct)
            if result is None:
                continue
            outcome, n_trades = result
            outcomes[outcome] += 1
            trade_counts.append(n_trades)
        total = sum(outcomes.values())
        if total == 0:
            print(f'  {risk_pct:>6.2f}  (no valid simulations)')
            continue
        avg_trades = np.mean(trade_counts) if trade_counts else 0.0
        print(f'  {risk_pct:>6.2f}  {outcomes["PASS"]/total*100:>6.1f}%  {outcomes["FAIL_DAILY"]/total*100:>9.1f}%  '
              f'{outcomes["FAIL_MAXLOSS"]/total*100:>11.1f}%  {outcomes["TIMEOUT"]/total*100:>7.1f}%  {avg_trades:>9.2f}')

print('\nDone.')
