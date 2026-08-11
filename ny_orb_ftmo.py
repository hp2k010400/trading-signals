"""
ny_orb_ftmo.py

Genuinely different mechanism from both failed strategies tonight --
not a candle-to-candle comparison (killed the original), not an ATR-
expansion continuation (just failed too). This is a classic opening-
range breakout: define the NY session's first hour (13:00-14:00 UTC,
right as the US cash equity market opens) as a reference range, then
watch the following hours for price breaking beyond that range and
trade the breakout direction.

Robust by construction: the reference level is a FULL H1 bar's high/
low, not a single candle's wick, so a broker's minor tick-level
differences are far less likely to change which side gets breached.

MECHANISM:
  1. NY opening range = the H1 bar starting 13:00 UTC (high/low).
  2. Watch the next ORB_WATCH_HOURS hours for price to close beyond
     that range (break above high = long, break below low = short).
  3. Entry at the next H1 bar's open after the breakout bar closes.
  4. Stop = opposite side of the opening range.
  5. Target = stop distance x RR.
  6. Only one attempt per day per instrument (first breakout only).

Same locked walk-forward discipline, real spread costs, confirmed
UTC+3 broker offset correction from the start.

Run in Codespace: python -u ny_orb_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

RR = 1.5
COST_MULT = 1.5
ORB_HOUR_UTC = 13          # NY opening range = the 13:00-14:00 UTC H1 bar
ORB_WATCH_HOURS = 4        # watch up to 4 hours after the opening range for a breakout
MAX_HOLD_HOURS = 8
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
_h1 = {}

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
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    _h1[symbol] = h1
    return True


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


def find_trades(symbol):
    m1 = _m1[symbol]
    h1 = _h1[symbol]
    m1_index = m1.index
    h1_index = h1.index
    trades = []

    days = pd.date_range(h1_index.min().normalize(), h1_index.max().normalize(), freq='D')
    for day in days:
        if day.dayofweek >= 5:
            continue
        orb_time = day + pd.Timedelta(hours=ORB_HOUR_UTC)
        if orb_time not in h1_index:
            continue
        orb_bar = h1.loc[orb_time]
        orb_high, orb_low = orb_bar['high'], orb_bar['low']
        if orb_high <= 0 or orb_low <= 0 or orb_high <= orb_low:
            continue

        watch_start = orb_time + pd.Timedelta(hours=1)
        watch_end = orb_time + pd.Timedelta(hours=1 + ORB_WATCH_HOURS)
        watch_bars = h1[(h1_index >= watch_start) & (h1_index < watch_end)]
        if len(watch_bars) == 0:
            continue

        direction = 0
        breakout_bar_time = None
        for t, row in watch_bars.iterrows():
            if row['close'] > orb_high:
                direction = 1
                breakout_bar_time = t
                break
            elif row['close'] < orb_low:
                direction = -1
                breakout_bar_time = t
                break
        if direction == 0:
            continue

        entry_time = breakout_bar_time + pd.Timedelta(hours=1)
        entry_m1_idx = m1_index.searchsorted(entry_time)
        if entry_m1_idx >= len(m1) - 1:
            continue
        entry_price = float(m1['open'].iloc[entry_m1_idx])
        stop_price = orb_low if direction == 1 else orb_high
        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0:
            continue
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        r_gross = simulate_forward(m1, m1_index, entry_m1_idx, direction, entry_price,
                                    stop_price, tp_price, MAX_HOLD_HOURS * 60)
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


print('Loading FTMO M1 data, building H1...')
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
