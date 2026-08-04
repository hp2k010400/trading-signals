"""
monday_gap_fill.py

Fun, quick, genuinely different idea: does Monday's weekend gap
(Friday close -> Monday open) tend to partially fill (revert toward
Friday's close) once real trading resumes? Different from the overnight
leg tested earlier tonight (which covered ANY weekday close-to-open gap)
-- this isolates specifically the bigger, weekend-driven Monday gap with
a fade/reversion mechanism, not a continuation one.

RATIONALE: weekend gaps often reflect news/sentiment with no real
liquidity to correct it (thin weekend trading, if any). Once Monday's
proper session opens with real volume, the gap can get partially
unwound as normal price discovery resumes.

MECHANISM:
  1. Measure the gap: Friday's close vs Monday's open.
  2. If gap is meaningful (>= MIN_GAP_PCT of price), fade it: if price
     gapped UP, go SHORT expecting reversion toward Friday's close; if
     gapped DOWN, go LONG.
  3. Entry at Monday's open (real M1 data, no lookahead).
  4. Target = halfway back to Friday's close (a partial fill, not a
     full round-trip -- more realistic than expecting a 100% fill).
  5. Stop = the gap size beyond entry (if the gap keeps extending
     instead of filling, cut it).
  6. Time stop: end of Monday's session (no overnight hold into Tuesday).

Tests all 8 instruments.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u monday_gap_fill.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_GAP_PCT = 0.10   # % of price -- gap must be at least this big to bother trading
MAX_HOLD_HOURS = 20   # roughly "end of Monday's session" safety cap
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

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


def find_setups(symbol):
    m1 = _m1[symbol]
    m1_index = m1.index
    days = pd.date_range(m1_index.min().normalize(), m1_index.max().normalize(), freq='D')
    trades = []
    for day in days:
        if day.dayofweek != 0:   # Monday only
            continue
        friday = day - pd.Timedelta(days=3)
        friday_window = m1[(m1_index >= friday) & (m1_index < friday + pd.Timedelta(days=1))]
        if len(friday_window) == 0:
            continue
        friday_close = float(friday_window['close'].iloc[-1])

        monday_window = m1[(m1_index >= day) & (m1_index < day + pd.Timedelta(days=1))]
        if len(monday_window) < 5:
            continue
        monday_open = float(monday_window['open'].iloc[0])
        if friday_close <= 0 or monday_open <= 0:
            continue

        gap = monday_open - friday_close
        gap_pct = abs(gap) / friday_close * 100.0
        if gap_pct < MIN_GAP_PCT:
            continue

        direction = -1 if gap > 0 else 1   # fade the gap
        entry_price = monday_open
        target_price = monday_open - gap / 2.0   # halfway back to Friday's close
        # gap's own sign already encodes the correct side: positive gap pushes the
        # stop further up (correct for a short), negative gap pushes it further
        # down (correct for a long) -- one formula covers both directions
        stop_price = monday_open + gap
        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0:
            continue

        entry_idx = m1_index.searchsorted(day)
        if entry_idx >= len(m1) - 1:
            continue

        window_end_idx = min(entry_idx + 1 + MAX_HOLD_HOURS * 60, len(m1))
        future = m1.iloc[entry_idx + 1: window_end_idx]
        if len(future) == 0:
            continue
        highs = future['high'].values
        lows = future['low'].values
        closes = future['close'].values

        r_gross = None
        for k in range(len(future)):
            if direction == 1:
                if highs[k] >= target_price:
                    r_gross = abs(target_price - entry_price) / stop_dist; break
                if lows[k] <= stop_price:
                    r_gross = -1.0; break
            else:
                if lows[k] <= target_price:
                    r_gross = abs(entry_price - target_price) / stop_dist; break
                if highs[k] >= stop_price:
                    r_gross = -1.0; break
        if r_gross is None:
            final_close = closes[-1]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)

        cost_r = COST_POINTS[symbol] / stop_dist
        trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_gross - cost_r})
    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for symbol in loaded:
    trades = find_setups(symbol)
    print(f'  {symbol}: {len(trades)} trades')
    all_trades.extend(trades)

df = pd.DataFrame(all_trades)
print(f'\nTotal trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

if len(df) > 0:
    is_df = df[df['entry_time'] < IS_OOS_SPLIT]
    oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]
    print()
    n, wr, pf, tot = compute_stats(is_df['r_net'].values)
    print_row('IN-SAMPLE (all)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
    print_row('HOLDOUT (all)', n, wr, pf, tot)
    print()
    for symbol in loaded:
        rv_is = is_df[is_df['symbol'] == symbol]['r_net'].values
        rv_oos = oos_df[oos_df['symbol'] == symbol]['r_net'].values
        n, wr, pf, tot = compute_stats(rv_is)
        print_row(f'  {symbol} IS', n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(rv_oos)
        print_row(f'  {symbol} HOLDOUT', n, wr, pf, tot)

print('\nDone.')
