"""
lesser_traded_donchian_ftmo.py

Same proven Donchian trend-following mechanism as fx_donchian_trend_ftmo.py
(classic CTA-style breakout, daily timeframe, robust multi-day range
construction), now pointed at lesser-traded instruments instead of the
majors -- less competition from institutional quant activity means a
real edge is more plausible here than in EURUSD/GBPUSD/major indices.

COST ESTIMATES ARE UNCALIBRATED -- these 7 instruments have never had
real spread data pulled from live Market Watch (unlike the majors,
which were calibrated earlier tonight). Treat results as directional
only until real spreads are measured; the 1.5x cost-stress multiplier
already applied provides some buffer against this uncertainty.

MECHANISM (Donchian channel breakout):
  1. If today's close breaks above the highest close of the last
     DONCHIAN_PERIOD days -> long. Below the lowest close -> short.
  2. Entry at next day's open.
  3. Stop = ATR_STOP_MULT x ATR(14).
  4. Target = stop distance x RR.
  5. Time-stop at MAX_HOLD_DAYS if neither hit.

Same locked walk-forward discipline, confirmed UTC+3 broker offset
correction from the start.

Run in Codespace: python -u lesser_traded_donchian_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

DONCHIAN_PERIOD = 20
ATR_PERIOD = 14
ATR_STOP_MULT = 2.0
RR = 2.0
COST_MULT = 1.5
MAX_HOLD_DAYS = 15
BROKER_UTC_OFFSET_HOURS = 3
WALK_FORWARD_MONTHS = 6

FILES = {
    'NATGAS': 'NATGAS_cash_M1_ftmo.csv',
    'UK100':  'UK100_cash_M1_ftmo.csv',
    'AUDNZD': 'AUDNZD_M1_ftmo.csv',
    'AUDCAD': 'AUDCAD_M1_ftmo.csv',
    'AUDCHF': 'AUDCHF_M1_ftmo.csv',
    'USDCHF': 'USDCHF_M1_ftmo.csv',
    'USDCAD': 'USDCAD_M1_ftmo.csv',
}
# UNCALIBRATED ESTIMATES -- see docstring
COST_POINTS = {
    'NATGAS': 0.008, 'UK100': 1.8, 'AUDNZD': 0.0004, 'AUDCAD': 0.0004,
    'AUDCHF': 0.0004, 'USDCHF': 0.00015, 'USDCAD': 0.00015,
}

_daily = {}

def load_daily(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    daily['donchian_high'] = daily['close'].rolling(DONCHIAN_PERIOD).max().shift(1)
    daily['donchian_low']  = daily['close'].rolling(DONCHIAN_PERIOD).min().shift(1)
    prev_close = daily['close'].shift(1)
    tr = pd.concat([daily['high']-daily['low'], (daily['high']-prev_close).abs(), (daily['low']-prev_close).abs()], axis=1).max(axis=1)
    daily['atr14'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    _daily[symbol] = daily
    return True


def find_trades(symbol):
    d = _daily[symbol]
    idx = d.index
    n = len(d)
    trades = []
    in_position_until = -1

    for i in range(DONCHIAN_PERIOD + ATR_PERIOD, n - 1):
        if i <= in_position_until:
            continue
        row = d.iloc[i]
        close = row['close']
        atr = row['atr14']
        if pd.isna(close) or pd.isna(atr) or atr <= 0:
            continue

        direction = 0
        if close > row['donchian_high']:
            direction = 1
        elif close < row['donchian_low']:
            direction = -1
        if direction == 0:
            continue

        entry_idx = i + 1
        if entry_idx >= n:
            continue
        entry_price = float(d['open'].iloc[entry_idx])
        stop_dist = ATR_STOP_MULT * atr
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        window_end = min(entry_idx + 1 + MAX_HOLD_DAYS, n)
        future = d.iloc[entry_idx + 1: window_end]
        r_gross = None
        exit_idx = window_end - 1
        if len(future) > 0:
            highs = future['high'].values; lows = future['low'].values; closes = future['close'].values
            for k in range(len(future)):
                if direction == 1:
                    if highs[k] >= tp_price: r_gross = RR; exit_idx = entry_idx + 1 + k; break
                    if lows[k] <= stop_price: r_gross = -1.0; exit_idx = entry_idx + 1 + k; break
                else:
                    if lows[k] <= tp_price: r_gross = RR; exit_idx = entry_idx + 1 + k; break
                    if highs[k] >= stop_price: r_gross = -1.0; exit_idx = entry_idx + 1 + k; break
            if r_gross is None:
                final_close = closes[-1]
                r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                           else (entry_price - final_close) / stop_dist)
        else:
            r_gross = -1.0

        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        trades.append({'symbol': symbol, 'entry_time': idx[entry_idx], 'r_net': r_gross - cost_r})
        in_position_until = exit_idx

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading FTMO M1 data, building daily bars + Donchian/ATR...')
loaded = [s for s in FILES if load_daily(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for symbol in loaded:
    trades = find_trades(symbol)
    print(f'  {symbol}: {len(trades)} trades')
    all_trades.extend(trades)

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'\nTotal trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print_row('OVERALL', n, wr, pf, tot)

if len(df) > 0:
    print(f'\n{"#"*90}')
    print(f'  WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    print(f'{"#"*90}')
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        window_rv = df[df['period'].isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    print(f'\n  Per-instrument:')
    for symbol in loaded:
        rv = df[df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {symbol}', n2, wr2, pf2, tot2)

print('\nDone.')
