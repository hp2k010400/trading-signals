"""
ny_ema_trend_ftmo.py

Test of the TikTok idea: at NY open, compare the first 5-minute
candle's close to a 12-period EMA -- above it, go long; below it, go
short; ride that direction for the next 6 hours.

INTERPRETATION NOTES (the original description left some things
unspecified, documenting the choices made):
  - "NY open" = 13:30 UTC, the real US cash equity market open (the
    most universally-recognized specific "open" moment). If you meant
    the 13:00 UTC forex-session convention instead, easy to change.
  - "12 EMA" computed on the M5 timeframe (matching the M5 candle
    mentioned), using the standard EMA formula on M5 closes.
  - No stop-loss or target was described in the original idea -- it's
    a pure "ride the direction for 6 hours" concept. For FTMO-
    compatible testing, added a safety stop (2x ATR(14) on M5) since
    an uncapped position for 6 hours is not realistically tradeable
    risk management -- flagged clearly as an addition, not part of
    the original description. No profit target; exit is either the
    6-hour timeout or the safety stop, whichever comes first.

Same locked walk-forward discipline, real spread costs, confirmed
UTC+3 broker offset correction from the start.

Run in Codespace: python -u ny_ema_trend_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

NY_OPEN_HOUR_UTC = 13
NY_OPEN_MINUTE_UTC = 30
EMA_PERIOD = 12
HOLD_HOURS = 6
STOP_ATR_MULT = 2.0   # added safety stop, not in the original description -- see docstring
ATR_PERIOD = 14
COST_MULT = 1.5
BROKER_UTC_OFFSET_HOURS = 3
WALK_FORWARD_MONTHS = 6

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'GOLD':  'XAUUSD_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
}

_m1 = {}
_m5 = {}

def load(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    _m1[symbol] = df
    m5 = df.resample('5min').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    m5['ema12'] = m5['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    prev_close = m5['close'].shift(1)
    tr = pd.concat([m5['high']-m5['low'], (m5['high']-prev_close).abs(), (m5['low']-prev_close).abs()], axis=1).max(axis=1)
    m5['atr14'] = tr.rolling(ATR_PERIOD).mean()
    _m5[symbol] = m5
    return True


def find_trades(symbol):
    m1 = _m1[symbol]
    m5 = _m5[symbol]
    m1_index = m1.index
    m5_index = m5.index
    trades = []

    days = pd.date_range(m5_index.min().normalize(), m5_index.max().normalize(), freq='D')
    for day in days:
        if day.dayofweek >= 5:
            continue
        signal_time = day + pd.Timedelta(hours=NY_OPEN_HOUR_UTC, minutes=NY_OPEN_MINUTE_UTC)
        if signal_time not in m5_index:
            continue
        row = m5.loc[signal_time]
        close, ema = row['close'], row['ema12']
        atr = row['atr14']
        if pd.isna(close) or pd.isna(ema) or pd.isna(atr) or atr <= 0 or close <= 0:
            continue

        direction = 1 if close > ema else (-1 if close < ema else 0)
        if direction == 0:
            continue

        entry_time = signal_time + pd.Timedelta(minutes=5)
        entry_m1_idx = m1_index.searchsorted(entry_time)
        if entry_m1_idx >= len(m1) - 1:
            continue
        entry_price = float(m1['open'].iloc[entry_m1_idx])
        stop_dist = STOP_ATR_MULT * atr
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist

        window_end_time = entry_time + pd.Timedelta(hours=HOLD_HOURS)
        window_end_idx = m1_index.searchsorted(window_end_time)
        future = m1.iloc[entry_m1_idx + 1: min(window_end_idx, len(m1))]
        if len(future) == 0:
            continue

        highs = future['high'].values; lows = future['low'].values; closes = future['close'].values
        r_gross = None
        for k in range(len(future)):
            if direction == 1 and lows[k] <= stop_price:
                r_gross = -1.0; break
            if direction == -1 and highs[k] >= stop_price:
                r_gross = -1.0; break
        if r_gross is None:
            final_close = closes[-1]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)

        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        trades.append({'symbol': symbol, 'entry_time': m1_index[entry_m1_idx], 'r_net': r_gross - cost_r})

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


print('Loading FTMO M1 data, building M5 + EMA12 + ATR...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for symbol in loaded:
    trades = find_trades(symbol)
    print(f'  {symbol}: {len(trades)} trades')
    all_trades.extend(trades)

df = pd.DataFrame(all_trades).sort_values('entry_time').reset_index(drop=True)
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
