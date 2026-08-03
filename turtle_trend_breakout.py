"""
turtle_trend_breakout.py

Classic Donchian/Turtle-style trend-following, tested on real M1 data at
daily resolution. Two canonical parameter sets (not free-tuned -- these
are the actual historical Turtle rules, chosen specifically to avoid
adding a fresh multiple-comparisons dimension on top of everything else
tested tonight):

  System 1: enter on a 20-day high/low breakout, exit on a 10-day
            breakout in the opposite direction (trailing channel).
  System 2: enter on a 55-day high/low breakout, exit on a 20-day
            breakout in the opposite direction.

Genuinely different mechanism from anything tested tonight: no fixed R
target. This is authentic trend-following -- cut losses short (2x ATR
hard stop) and let winners run until the trailing channel says the trend
is over, however long that takes. That asymmetry is the entire thesis.

Unlike the earlier scripts, a position can stay open across many days, so
this walks forward day-by-day as a proper sequential simulation (not
independent per-signal trades) -- while flat, watch for a breakout; once
in a trade, each subsequent day checks the hard stop and the trailing
exit channel using that day's real M1 path, in chronological order.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u turtle_trend_breakout.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')
RISK_PCT  = 0.5
START_BAL = 70000
ATR_LEN   = 20
ATR_STOP_MULT = 2.0
MAX_HOLD_DAYS = 250   # outer safety cap only, not expected to bind often

SYSTEMS = {
    'SYS1_20_10': (20, 10),
    'SYS2_55_20': (55, 20),
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


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate_symbol(symbol, entry_n, exit_n):
    m1 = _m1[symbol]
    m1_index = m1.index
    d1 = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    d1 = d1[d1['open'] > 0]
    d_atr = atr_daily(d1)
    n = len(d1)
    if n < entry_n + 5:
        return []

    trades = []
    state = None   # None = flat, else dict with trade info
    i = entry_n

    while i < n - 1:
        if state is None:
            prior_high = d1['high'].iloc[i-entry_n:i].max()
            prior_low  = d1['low'].iloc[i-entry_n:i].min()
            atr_val = d_atr.iloc[i-1]
            if pd.isna(atr_val) or atr_val <= 0:
                i += 1
                continue

            day_start = d1.index[i]
            day_end = day_start + pd.Timedelta(days=1)
            window = m1[(m1_index >= day_start) & (m1_index < day_end)]
            if len(window) == 0:
                i += 1
                continue

            direction = 0
            entry_price = None
            entry_ts = None
            for j in range(len(window)):
                bar = window.iloc[j]
                if bar['high'] > prior_high:
                    direction = 1; entry_price = prior_high; entry_ts = window.index[j]; break
                if bar['low'] < prior_low:
                    direction = -1; entry_price = prior_low; entry_ts = window.index[j]; break

            if direction == 0:
                i += 1
                continue

            stop_price = (entry_price - ATR_STOP_MULT * atr_val if direction == 1
                          else entry_price + ATR_STOP_MULT * atr_val)
            stop_distance = abs(entry_price - stop_price)
            if stop_distance <= 0:
                i += 1
                continue

            state = {'direction': direction, 'entry_price': entry_price, 'stop_price': stop_price,
                      'stop_distance': stop_distance, 'entry_day_idx': i, 'entry_ts': entry_ts}
            i += 1
            continue

        # --- in a trade: check hard stop + trailing exit channel each day ---
        held_days = i - state['entry_day_idx']
        if held_days > MAX_HOLD_DAYS:
            exit_price = float(d1['close'].iloc[i-1])
            trades.append(_close_trade(state, exit_price, state['entry_ts'], 'MAX_HOLD'))
            state = None
            continue

        if i - exit_n < 0:
            trail_level = None
        else:
            trail_level = (d1['low'].iloc[i-exit_n:i].min() if state['direction'] == 1
                            else d1['high'].iloc[i-exit_n:i].max())

        day_start = d1.index[i]
        day_end = day_start + pd.Timedelta(days=1)
        window = m1[(m1_index >= day_start) & (m1_index < day_end)]
        if len(window) == 0:
            i += 1
            continue

        exited = False
        for j in range(len(window)):
            bar = window.iloc[j]
            if state['direction'] == 1:
                if bar['low'] <= state['stop_price']:
                    trades.append(_close_trade(state, state['stop_price'], window.index[j], 'STOP'))
                    exited = True; break
                if trail_level is not None and bar['low'] <= trail_level:
                    trades.append(_close_trade(state, trail_level, window.index[j], 'TRAIL'))
                    exited = True; break
            else:
                if bar['high'] >= state['stop_price']:
                    trades.append(_close_trade(state, state['stop_price'], window.index[j], 'STOP'))
                    exited = True; break
                if trail_level is not None and bar['high'] >= trail_level:
                    trades.append(_close_trade(state, trail_level, window.index[j], 'TRAIL'))
                    exited = True; break

        if exited:
            state = None
        i += 1

    return trades


def _close_trade(state, exit_price, exit_ts, reason):
    direction = state['direction']
    stop_distance = state['stop_distance']
    entry_price = state['entry_price']
    r_gross = ((exit_price - entry_price) / stop_distance if direction == 1
               else (entry_price - exit_price) / stop_distance)
    return {
        'direction': direction, 'entry_price': entry_price, 'exit_price': exit_price,
        'stop_distance': stop_distance, 'entry_time': state['entry_ts'], 'exit_time': exit_ts,
        'r_gross': r_gross, 'reason': reason,
    }


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()

RISK_PER_R = START_BAL * RISK_PCT / 100.0

def print_row(label, n, wr, pf, tot, width=28):
    gbp = tot * RISK_PER_R
    print(f'  {label:<{width}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  '
          f'R={tot:>+9.2f}  £{gbp:>+11,.0f}')


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for sys_name, (entry_n, exit_n) in SYSTEMS.items():
    print(f'--- {sys_name} (entry={entry_n}d, exit={exit_n}d) ---')
    for symbol in loaded:
        trades = simulate_symbol(symbol, entry_n, exit_n)
        for t in trades:
            t['system'] = sys_name
            t['symbol'] = symbol
        print(f'  {symbol}: {len(trades)} trades')
        all_trades.extend(trades)
    print()

print(f'Total trades across both systems: {len(all_trades)}')
if len(all_trades) < 80:
    print('WARNING: fewer than 80 total trades -- treat every number below as unreliable.')

print('\nFirst 10 trades (sanity check -- hold times should vary, not be fixed):')
print(f'  {"Sys":<12}{"Symbol":<8}{"Dir":<7}{"Entry time":<22}{"Exit time":<22}{"Hold(d)":>8}{"Reason":<8}{"R":>8}')
for t in all_trades[:10]:
    d = 'LONG' if t['direction'] == 1 else 'SHORT'
    hold_d = (t['exit_time'] - t['entry_time']).total_seconds() / 86400
    print(f'  {t["system"]:<12}{t["symbol"]:<8}{d:<7}{str(t["entry_time"]):<22}{str(t["exit_time"]):<22}'
          f'{hold_d:>8.1f}{t["reason"]:<8}{t["r_gross"]:>+8.2f}')

df = pd.DataFrame(all_trades)
df['r_net'] = df.apply(lambda row: row['r_gross'] - COST_POINTS[row['symbol']] / row['stop_distance'], axis=1)

is_df = df[df['entry_time'] < IS_OOS_SPLIT]
oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]

print(f'\n{"="*88}')
print(f'  OVERALL (both systems combined)')
print(f'{"="*88}')
n, wr, pf, tot = compute_stats(is_df['r_net'].values)
print_row('IN-SAMPLE', n, wr, pf, tot)
n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
print_row('HOLDOUT', n, wr, pf, tot)

for sys_name in SYSTEMS:
    print(f'\n{"="*88}')
    print(f'  {sys_name}')
    print(f'{"="*88}')
    sub_is = is_df[is_df['system'] == sys_name]
    sub_oos = oos_df[oos_df['system'] == sys_name]
    n, wr, pf, tot = compute_stats(sub_is['r_net'].values)
    print_row('IS (all instruments)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(sub_oos['r_net'].values)
    print_row('HOLDOUT (all instruments)', n, wr, pf, tot)
    print()
    for sym in sorted(df['symbol'].unique()):
        rv = sub_is[sub_is['symbol'] == sym]['r_net'].values
        n, wr, pf, tot = compute_stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('  ' + sym + flag, n, wr, pf, tot)

# reason breakdown -- confirms the trailing exit is actually doing something,
# not every trade just hitting the hard stop
print(f'\nExit reason breakdown: {df["reason"].value_counts().to_dict()}')

print('\nDone.')
