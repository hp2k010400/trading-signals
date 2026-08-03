"""
vol_contraction_momentum.py

Two genuinely new hypotheses, both on D1, both with a real behavioural
rationale (not indicator-fitting):

HYPOTHESIS 1: Volatility contraction -> expansion
  Rationale: realized volatility is mean-reverting (well-documented GARCH
  effect) -- unusually tight ranges don't persist, and often precede a
  resolution/expansion. This is Turtle's exact entry/exit mechanics
  (10-day breakout, 10-day trailing exit, 2x ATR stop) with ONE addition:
  only take the breakout if today's ATR is in the bottom 25th percentile
  of its own trailing 100-day history first. Turtle alone already failed
  its holdout (PF 0.86) -- this isolates whether the vol-contraction
  pre-condition specifically adds anything on top of that same mechanism,
  a clean A/B test against an already-known result.

HYPOTHESIS 2: Short-horizon momentum persistence
  Rationale: large single-day moves can reflect information or order
  flow that isn't instantly absorbed (slow institutional execution,
  gradual repricing) -- different mechanism from the monthly
  cross-sectional momentum already tested (strategy6), this is
  single-instrument, next-day continuation. Only trades when today's
  move is unusually large (>1x ATR) AND closes near its own extreme
  (a "trend day", not an indecisive one) -- enters next day's open in
  the same direction, fixed stop and target, no discretion.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u vol_contraction_momentum.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')
RISK_PCT  = 0.5
START_BAL = 70000
ATR_LEN = 20

# --- Hypothesis 1 params ---
VC_PCTILE_LOOKBACK = 100
VC_CONTRACTION_PCTILE = 0.25   # ATR must be in bottom 25% of trailing 100 days
VC_ENTRY_N = 10
VC_EXIT_N = 10
VC_ATR_STOP_MULT = 2.0
VC_MAX_HOLD_DAYS = 120

# --- Hypothesis 2 params ---
MOM_ATR_MOVE_MULT = 1.0        # today's move must exceed 1x ATR
MOM_CLOSE_EXTREME_PCT = 0.20   # close must be in the outer 20% of the day's own range
MOM_STOP_ATR_MULT = 1.5
MOM_TP_R = 2.0
MOM_MAX_HOLD_DAYS = 3

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


def build_daily(symbol):
    m1 = _m1[symbol]
    d1 = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    return d1[d1['open'] > 0]


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def simulate_forward_m1(symbol, entry_ts, direction, entry_price, stop_price, tp_price, max_days):
    m1 = _m1[symbol]
    m1_index = m1.index
    entry_idx = m1_index.searchsorted(entry_ts)
    if entry_idx >= len(m1) - 1:
        return None
    window_end = min(entry_idx + 1 + max_days * 24 * 60, len(m1))
    future = m1.iloc[entry_idx + 1: window_end]
    if len(future) == 0:
        return None
    highs = future['high'].values
    lows = future['low'].values
    closes = future['close'].values
    for k in range(len(future)):
        if direction == 1:
            if highs[k] >= tp_price:
                return (tp_price - entry_price) / abs(entry_price - stop_price), 'TP', future.index[k]
            if lows[k] <= stop_price:
                return -1.0, 'SL', future.index[k]
        else:
            if lows[k] <= tp_price:
                return (entry_price - tp_price) / abs(entry_price - stop_price), 'TP', future.index[k]
            if highs[k] >= stop_price:
                return -1.0, 'SL', future.index[k]
    final_close = closes[-1]
    stop_dist = abs(entry_price - stop_price)
    r = ((final_close - entry_price) / stop_dist if direction == 1
         else (entry_price - final_close) / stop_dist)
    return r, 'TIMEOUT', future.index[-1]


# ============================================================
#  HYPOTHESIS 1: volatility contraction -> expansion
# ============================================================
def simulate_vol_contraction(symbol):
    d1 = build_daily(symbol)
    d_atr = atr_daily(d1)
    atr_pctile = d_atr.rolling(VC_PCTILE_LOOKBACK).apply(lambda x: (x <= x.iloc[-1]).mean(), raw=False)
    n = len(d1)
    trades = []
    state = None
    i = max(VC_ENTRY_N, VC_PCTILE_LOOKBACK) + 1

    while i < n - 1:
        if state is None:
            atr_val = d_atr.iloc[i-1]
            pctile = atr_pctile.iloc[i-1]
            if pd.isna(atr_val) or atr_val <= 0 or pd.isna(pctile):
                i += 1; continue
            if pctile > VC_CONTRACTION_PCTILE:
                i += 1; continue   # not contracted -- skip, no trade today

            prior_high = d1['high'].iloc[i-VC_ENTRY_N:i].max()
            prior_low = d1['low'].iloc[i-VC_ENTRY_N:i].min()
            day_start = d1.index[i]
            day_end = day_start + pd.Timedelta(days=1)
            m1 = _m1[symbol]
            window = m1[(m1.index >= day_start) & (m1.index < day_end)]
            if len(window) == 0:
                i += 1; continue

            direction = 0; entry_price = None; entry_ts = None
            for j in range(len(window)):
                bar = window.iloc[j]
                if bar['high'] > prior_high:
                    direction = 1; entry_price = prior_high; entry_ts = window.index[j]; break
                if bar['low'] < prior_low:
                    direction = -1; entry_price = prior_low; entry_ts = window.index[j]; break
            if direction == 0:
                i += 1; continue

            stop_price = (entry_price - VC_ATR_STOP_MULT * atr_val if direction == 1
                          else entry_price + VC_ATR_STOP_MULT * atr_val)
            stop_dist = abs(entry_price - stop_price)
            if stop_dist <= 0:
                i += 1; continue
            state = {'direction': direction, 'entry_price': entry_price, 'stop_price': stop_price,
                     'stop_distance': stop_dist, 'entry_day_idx': i, 'entry_ts': entry_ts}
            i += 1
            continue

        held_days = i - state['entry_day_idx']
        if held_days > VC_MAX_HOLD_DAYS:
            exit_price = float(d1['close'].iloc[i-1])
            trades.append(_close_trade(state, exit_price, state['entry_ts'], 'MAX_HOLD'))
            state = None
            continue

        if i - VC_EXIT_N < 0:
            trail_level = None
        else:
            trail_level = (d1['low'].iloc[i-VC_EXIT_N:i].min() if state['direction'] == 1
                            else d1['high'].iloc[i-VC_EXIT_N:i].max())

        day_start = d1.index[i]; day_end = day_start + pd.Timedelta(days=1)
        m1 = _m1[symbol]
        window = m1[(m1.index >= day_start) & (m1.index < day_end)]
        if len(window) == 0:
            i += 1; continue

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
    return {'direction': direction, 'entry_time': state['entry_ts'], 'exit_time': exit_ts,
            'stop_distance': stop_distance, 'r_gross': r_gross, 'reason': reason}


# ============================================================
#  HYPOTHESIS 2: short-horizon momentum persistence
# ============================================================
def simulate_momentum_persistence(symbol):
    d1 = build_daily(symbol)
    d_atr = atr_daily(d1)
    n = len(d1)
    trades = []

    for i in range(ATR_LEN + 1, n - 1):
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        o, h, l, c = d1['open'].iloc[i], d1['high'].iloc[i], d1['low'].iloc[i], d1['close'].iloc[i]
        day_range = h - l
        if day_range <= 0:
            continue
        move = c - o
        if abs(move) / atr_val < MOM_ATR_MOVE_MULT:
            continue   # today's move wasn't big enough

        direction = 1 if move > 0 else -1
        close_pos = (c - l) / day_range   # 0 = at the low, 1 = at the high
        if direction == 1 and close_pos < (1 - MOM_CLOSE_EXTREME_PCT):
            continue   # didn't close near the high -- not a clean trend day
        if direction == -1 and close_pos > MOM_CLOSE_EXTREME_PCT:
            continue   # didn't close near the low

        next_day = d1.index[i+1]
        m1 = _m1[symbol]
        next_open_window = m1[(m1.index >= next_day) & (m1.index < next_day + pd.Timedelta(hours=1))]
        if len(next_open_window) == 0:
            continue
        entry_price = float(next_open_window['open'].iloc[0])
        entry_ts = next_open_window.index[0]
        stop_price = (entry_price - MOM_STOP_ATR_MULT * atr_val if direction == 1
                      else entry_price + MOM_STOP_ATR_MULT * atr_val)
        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0:
            continue
        tp_price = (entry_price + stop_dist * MOM_TP_R if direction == 1
                    else entry_price - stop_dist * MOM_TP_R)

        result = simulate_forward_m1(symbol, entry_ts, direction, entry_price, stop_price,
                                      tp_price, MOM_MAX_HOLD_DAYS)
        if result is None:
            continue
        r_gross, reason, exit_ts = result
        trades.append({'direction': direction, 'entry_time': entry_ts, 'exit_time': exit_ts,
                       'stop_distance': stop_dist, 'r_gross': r_gross, 'reason': reason})

    return trades


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

for hyp_name, sim_func in [('HYPOTHESIS 1: Vol contraction -> expansion', simulate_vol_contraction),
                            ('HYPOTHESIS 2: Short-horizon momentum persistence', simulate_momentum_persistence)]:
    print(f'{"#"*90}')
    print(f'  {hyp_name}')
    print(f'{"#"*90}')

    all_trades = []
    for symbol in loaded:
        trades = sim_func(symbol)
        for t in trades:
            t['symbol'] = symbol
        print(f'  {symbol}: {len(trades)} trades')
        all_trades.extend(trades)

    print(f'\nTotal trades: {len(all_trades)}')
    if len(all_trades) < 80:
        print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

    if len(all_trades) == 0:
        print('\nNo trades found.\n')
        continue

    df = pd.DataFrame(all_trades)
    df['r_net'] = df.apply(lambda row: row['r_gross'] - COST_POINTS[row['symbol']] / row['stop_distance'], axis=1)
    is_df = df[df['entry_time'] < IS_OOS_SPLIT]
    oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]

    n, wr, pf, tot = compute_stats(is_df['r_net'].values)
    print_row('IN-SAMPLE', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
    print_row('HOLDOUT', n, wr, pf, tot)
    print()
    for sym in sorted(df['symbol'].unique()):
        rv_is = is_df[is_df['symbol'] == sym]['r_net'].values
        rv_oos = oos_df[oos_df['symbol'] == sym]['r_net'].values
        n, wr, pf, tot = compute_stats(rv_is)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row(f'  {sym} IS' + flag, n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(rv_oos)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row(f'  {sym} HOLDOUT' + flag, n, wr, pf, tot)

    print(f'\nExit reason breakdown: {df["reason"].value_counts().to_dict()}\n')

print('Done.')
