"""
fair_price_displacement.py

Tests the ONE falsifiable, mechanical piece buried in the "fair pricing
theory" video, stripped of every bit of undefined discretion (no
redrawing "fair price" mid-session, no skipping signals "for whatever
reason", no judgment calls -- a computer applies the same rule to every
bar, every day):

  Session open = "fair price", fixed for the whole session (no redefining
  it mid-day, unlike the video).

  SUB-STRATEGY A (continuation, first 5 minutes):
    Direction = colour of the opening 5-min candle. Enter on a breakout of
    that candle's extreme in that direction. Stop = other side of the
    candle. Target = 1.5x the stop (his stated 1:1.5 R:R).

  SUB-STRATEGY B (reversion, minutes 5-90):
    A "displacement candle" = its body is bigger than the previous bar's
    body (his literal, stated definition -- no exceptions, no "combine
    two candles", no skipping ones that "don't close below the wick").
    Trade in that candle's own direction (continuation of the
    displacement itself, per his examples), stop beyond its extreme,
    target 1.5x the stop.

Tested across NY, London, and Asian session opens separately, since he
specifically claims "works with any session open, but New York is best"
-- that's a checkable claim.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u fair_price_displacement.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')
RISK_PCT  = 0.5
START_BAL = 70000
RR = 1.5                    # his stated 1:1.5 risk:reward, applied to every trade
REVERSION_WINDOW_MIN = 90   # minutes 5-90 after session open
CONT_WATCH_MIN = 30         # how long to watch for the opening breakout to trigger
MAX_HOLD_MIN = 240          # outer safety cap so no trade waits forever to resolve
MIN_DISPLACEMENT_PCT = 0.0004   # body must be >= 0.04% of price -- filters out sub-noise
                                  # "displacement" candles that a human would never actually
                                  # mark on a chart; without this, tiny-range candles get tiny
                                  # stops and fixed point-costs swamp the R calculation

SESSIONS = {
    'ASIAN':  0,
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


def find_trades(symbol, session_name, session_hour):
    m1 = _m1[symbol]
    m1_index = m1.index
    days = pd.date_range(m1_index.min().normalize(), m1_index.max().normalize(), freq='D')
    trades = []

    for day in days:
        if day.dayofweek >= 5:
            continue
        session_start = day + pd.Timedelta(hours=session_hour)

        # --- opening 5-minute candle ---
        open_window = m1[(m1_index >= session_start) & (m1_index < session_start + pd.Timedelta(minutes=5))]
        if len(open_window) == 0:
            continue
        o_open = float(open_window['open'].iloc[0])
        o_close = float(open_window['close'].iloc[-1])
        o_high = float(open_window['high'].max())
        o_low = float(open_window['low'].min())
        if o_open <= 0 or o_close == o_open:
            cont_direction = 0
        else:
            cont_direction = 1 if o_close > o_open else -1

        # --- SUB-STRATEGY A: continuation breakout of the opening candle ---
        if cont_direction != 0 and o_open > 0 and (o_high - o_low) / o_open >= MIN_DISPLACEMENT_PCT:
            watch_start = session_start + pd.Timedelta(minutes=5)
            watch_end = watch_start + pd.Timedelta(minutes=CONT_WATCH_MIN)
            watch = m1[(m1_index >= watch_start) & (m1_index < watch_end)]
            level = o_high if cont_direction == 1 else o_low
            stop_level = o_low if cont_direction == 1 else o_high
            stop_dist = abs(level - stop_level)
            for j in range(len(watch)):
                bar = watch.iloc[j]
                triggered = (bar['high'] > level) if cont_direction == 1 else (bar['low'] < level)
                if triggered and stop_dist > 0:
                    entry_ts = watch.index[j]
                    entry_idx = m1_index.searchsorted(entry_ts)
                    if entry_idx < len(m1):
                        tp_level = level + stop_dist * RR if cont_direction == 1 else level - stop_dist * RR
                        r, reason = simulate_forward(m1, m1_index, entry_idx, cont_direction, level,
                                                      stop_level, tp_level, MAX_HOLD_MIN)
                        trades.append({'symbol': symbol, 'session': session_name, 'substrat': 'CONT',
                                       'direction': cont_direction, 'entry_time': entry_ts,
                                       'stop_distance': stop_dist, 'r_gross': r, 'reason': reason})
                    break

        # --- SUB-STRATEGY B: reversion displacement candles, minutes 5-90 ---
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
                continue   # not a displacement candle -- his literal rule, no exceptions
            px = float(closes[i])
            if px <= 0 or body_cur / px < MIN_DISPLACEMENT_PCT:
                continue   # too small to be a real displacement, just noise

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
            entry_idx += 1   # enter at the NEXT bar's open -- no same-bar lookahead
            entry_price = float(m1['open'].iloc[entry_idx])
            tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

            r, reason = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                          stop_price, tp_price, MAX_HOLD_MIN)
            trades.append({'symbol': symbol, 'session': session_name, 'substrat': 'REVERSION',
                           'direction': direction, 'entry_time': m1_index[entry_idx],
                           'stop_distance': stop_dist, 'r_gross': r, 'reason': reason})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)   # resume scanning after this trade starts

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

all_trades = []
for session_name, session_hour in SESSIONS.items():
    print(f'--- {session_name} session (open = {session_hour:02d}:00 UTC) ---')
    for symbol in loaded:
        trades = find_trades(symbol, session_name, session_hour)
        print(f'  {symbol}: {len(trades)} trades')
        all_trades.extend(trades)
    print()

print(f'Total trades: {len(all_trades)}')
if len(all_trades) < 200:
    print('WARNING: fewer than 200 trades -- treat every number below as unreliable.')

df = pd.DataFrame(all_trades)
df['r_net'] = df.apply(lambda row: row['r_gross'] - COST_POINTS[row['symbol']] / row['stop_distance'], axis=1)
is_df = df[df['entry_time'] < IS_OOS_SPLIT]
oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]

print(f'\n{"="*88}')
print(f'  OVERALL (both sub-strategies, all sessions)')
print(f'{"="*88}')
n, wr, pf, tot = compute_stats(is_df['r_net'].values)
print_row('IN-SAMPLE', n, wr, pf, tot)
n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
print_row('HOLDOUT', n, wr, pf, tot)

for substrat in ['CONT', 'REVERSION']:
    print(f'\n{"="*88}')
    print(f'  {substrat}')
    print(f'{"="*88}')
    sub_is = is_df[is_df['substrat'] == substrat]
    sub_oos = oos_df[oos_df['substrat'] == substrat]
    n, wr, pf, tot = compute_stats(sub_is['r_net'].values)
    print_row('IS (all sessions)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(sub_oos['r_net'].values)
    print_row('HOLDOUT (all sessions)', n, wr, pf, tot)
    print()
    for session_name in SESSIONS:
        rv_is = sub_is[sub_is['session'] == session_name]['r_net'].values
        rv_oos = sub_oos[sub_oos['session'] == session_name]['r_net'].values
        n, wr, pf, tot = compute_stats(rv_is)
        print_row(f'  {session_name} IS', n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(rv_oos)
        print_row(f'  {session_name} HOLDOUT', n, wr, pf, tot)

print(f'\nExit reason breakdown: {df["reason"].value_counts().to_dict()}')
print('\nDone.')
