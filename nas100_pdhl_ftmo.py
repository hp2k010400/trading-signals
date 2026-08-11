"""
nas100_pdhl_ftmo.py

Single-instrument, one-trade-per-day idea: NAS100 only. Each day,
whichever of YESTERDAY's high or low gets broken first, take that
breakout direction -- only the first signal of the day, ignore
anything after (even if price reverses and breaks the other level
later the same day).

MECHANISM:
  1. Reference levels = yesterday's high and low (H1 bars).
  2. Watch today's H1 bars during PDHL_WATCH_HOURS for the first
     close beyond either level.
  3. Entry at the next H1 bar's open. Stop = ATR_STOP_MULT x ATR(14).
     Target = stop distance x RR.
  4. Time-stop at MAX_HOLD_HOURS if neither hit.
  5. Only the FIRST qualifying breakout each day is taken.

Same locked walk-forward discipline, real spread costs, confirmed
UTC+3 broker offset correction from the start.

Run in Codespace: python -u nas100_pdhl_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
RR = 1.5
COST_MULT = 1.5
PDHL_WATCH_START_HOUR = 7    # start watching for a breakout from this UTC hour
PDHL_WATCH_HOURS = 12        # watch this many hours for the first breakout
MAX_HOLD_HOURS = 8
BROKER_UTC_OFFSET_HOURS = 3
WALK_FORWARD_MONTHS = 6

SYMBOL = 'NAS100'
FILE = 'US100_M1_ftmo.csv'
COST_PT = 1.5

_m1 = None
_h1 = None

def load():
    global _m1, _h1
    if not os.path.exists(FILE):
        return False
    df = pd.read_csv(FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    _m1 = df
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    prev_close = h1['close'].shift(1)
    tr = pd.concat([h1['high']-h1['low'], (h1['high']-prev_close).abs(), (h1['low']-prev_close).abs()], axis=1).max(axis=1)
    h1['atr14'] = tr.rolling(ATR_PERIOD).mean()
    _h1 = h1
    return True


def find_trades():
    m1, h1 = _m1, _h1
    m1_index, h1_index = m1.index, h1.index
    trades = []

    days = pd.date_range(h1_index.min().normalize(), h1_index.max().normalize(), freq='D')
    for day in days:
        if day.dayofweek >= 5:
            continue
        yesterday = day - pd.Timedelta(days=1)
        yesterday_bars = h1[(h1_index >= yesterday) & (h1_index < day)]
        if len(yesterday_bars) < 10:
            continue
        pd_high = yesterday_bars['high'].max()
        pd_low = yesterday_bars['low'].min()
        if pd_high <= 0 or pd_low <= 0 or pd_high <= pd_low:
            continue

        watch_start = day + pd.Timedelta(hours=PDHL_WATCH_START_HOUR)
        watch_end = watch_start + pd.Timedelta(hours=PDHL_WATCH_HOURS)
        watch_bars = h1[(h1_index >= watch_start) & (h1_index < watch_end)]
        if len(watch_bars) == 0:
            continue

        direction = 0
        breakout_time = None
        atr_at_signal = None
        for t, row in watch_bars.iterrows():
            if row['close'] > pd_high:
                direction = 1; breakout_time = t; atr_at_signal = row['atr14']; break
            elif row['close'] < pd_low:
                direction = -1; breakout_time = t; atr_at_signal = row['atr14']; break
        if direction == 0 or pd.isna(atr_at_signal) or atr_at_signal <= 0:
            continue

        entry_time = breakout_time + pd.Timedelta(hours=1)
        entry_m1_idx = m1_index.searchsorted(entry_time)
        if entry_m1_idx >= len(m1) - 1:
            continue
        entry_price = float(m1['open'].iloc[entry_m1_idx])
        stop_dist = ATR_STOP_MULT * atr_at_signal
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        window_end_time = entry_time + pd.Timedelta(hours=MAX_HOLD_HOURS)
        window_end_idx = m1_index.searchsorted(window_end_time)
        future = m1.iloc[entry_m1_idx + 1: min(window_end_idx, len(m1))]
        if len(future) == 0:
            continue
        highs = future['high'].values; lows = future['low'].values; closes = future['close'].values
        r_gross = None
        for k in range(len(future)):
            if direction == 1:
                if highs[k] >= tp_price: r_gross = RR; break
                if lows[k] <= stop_price: r_gross = -1.0; break
            else:
                if lows[k] <= tp_price: r_gross = RR; break
                if highs[k] >= stop_price: r_gross = -1.0; break
        if r_gross is None:
            final_close = closes[-1]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)

        cost_r = COST_PT / stop_dist * COST_MULT
        trades.append({'entry_time': m1_index[entry_m1_idx], 'r_net': r_gross - cost_r})

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


print(f'Loading {SYMBOL} FTMO M1 data, building H1 + ATR...')
if not load():
    raise SystemExit(f'{FILE} not found')

trades = find_trades()
df = pd.DataFrame(trades).sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print(f'\nOVERALL: N={n}  WR={wr}%  PF={pf}  R={tot:+.1f}\n')

if len(df) > 0:
    print(f'{"#"*90}')
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

print('\nDone.')
