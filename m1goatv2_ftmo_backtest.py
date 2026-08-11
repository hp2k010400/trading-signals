"""
m1goatv2_ftmo_backtest.py

Faithful Python replica of the OLD M1GOATV2.mq5 strategy (H1 Inside
Bar + Pin Bar, 4R target), backtested on FTMO's own M1 data resampled
to H1 -- not OANDA, and not the displacement-candle strategy tested
all night. This is the bot from BEFORE tonight's session that had the
fake/inflated backtest (crediting timeouts as wins) -- never properly
re-validated since. Includes the same broker-UTC-offset fix already
found tonight (FTMO server runs UTC+3).

Rules replicated exactly from M1GOATV2.mq5:
  - Runs on H1 bars (resampled from M1)
  - Inside Bar: bar[1] high < bar[2] high AND bar[1] low > bar[2] low,
    range >= 0.015% of price -> ARM (either direction breakout)
  - Pin Bar: wick >= 2x body AND wick >= 0.5x full range, min body
    >= 2% of range -> ARM (breakout only in the wick-rejection direction)
  - Armed signal valid for 3 hours; entry on price breaking the armed
    high (long) or low (short)
  - Stop = the opposite armed level, Target = 4R
  - Max 3 trades/day per instrument, time-stop at 480 minutes
  - Power-hour + day-of-week filters per instrument (symbol-specific)
  - News filter NOT replicated (no economic calendar data available --
    real result will include some trades the live EA would have
    skipped, a known simplification, not a bug)

Run in Codespace: python -u m1goatv2_ftmo_backtest.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

TP_R = 4.0
MAX_PER_DAY = 3
ENTRY_WINDOW_H = 3
MIN_IB_RANGE_PCT = 0.015 / 100.0
PB_WICK_RATIO = 2.0
PB_WICK_RANGE_FRACTION = 0.5
MAX_MINS_OPEN = 480
COST_MULT = 1.5
BROKER_UTC_OFFSET_HOURS = 3   # FTMO server runs UTC+3, confirmed earlier tonight

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


def is_power_hour(symbol, hour_utc):
    if symbol == 'US30' or symbol == 'NAS100' or symbol == 'SP500':
        return 13 <= hour_utc <= 16
    if symbol == 'DAX':
        return (8 <= hour_utc <= 10) or hour_utc in (13, 14)
    if symbol == 'USDJPY':
        return hour_utc in (0, 1, 2, 8, 9)
    # EURUSD / GBPUSD / GOLD -- default case
    return (8 <= hour_utc <= 9) or (13 <= hour_utc <= 15)


def is_skip_day(symbol, dow):
    # dow: Monday=0 ... Sunday=6 (pandas convention) -- MQL5 used Sun=0..Sat=6,
    # converted here: skip Sunday(6 in pandas) and Saturday(5 in pandas) always;
    # indices additionally skip Monday(0) for the index group
    if symbol in ('NAS100', 'SP500', 'US30'):
        return dow in (5, 6, 0)   # skip Sat, Sun, Mon
    return dow in (5, 6)          # skip Sat, Sun only


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
            if highs[k] >= tp_price: return TP_R
            if lows[k] <= stop_price: return -1.0
        else:
            if lows[k] <= tp_price: return TP_R
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
    trades_today = {}

    for i in range(2, len(h1)):
        bar_time = h1_index[i]         # this H1 bar's open = "current_h1" in the EA, signal detected on close of bar i-1
        sig_time = h1_index[i-1]       # the just-closed bar (bar[1] in EA terms)
        prev_time = h1_index[i-2]      # bar[2] in EA terms

        day_key = bar_time.date()
        trades_today.setdefault(day_key, 0)
        if trades_today[day_key] >= MAX_PER_DAY:
            continue

        dow = bar_time.dayofweek
        if is_skip_day(symbol, dow):
            continue
        if not is_power_hour(symbol, bar_time.hour):
            continue

        h1_bar = h1.loc[sig_time]
        h2_bar = h1.loc[prev_time]
        hi1, lo1 = h1_bar['high'], h1_bar['low']
        hi2, lo2 = h2_bar['high'], h2_bar['low']
        if hi1 <= 0 or lo1 <= 0 or hi2 <= 0 or lo2 <= 0:
            continue

        armed = False
        armed_h = armed_l = 0
        armed_dir = 0
        pattern = ''

        # Inside bar
        if hi1 < hi2 and lo1 > lo2:
            rng = hi1 - lo1
            if hi1 > 0 and (rng / hi1) >= MIN_IB_RANGE_PCT:
                armed = True
                armed_h, armed_l, armed_dir, pattern = hi1, lo1, 0, 'IB'

        # Pin bar (only if IB didn't already arm -- matches EA's sequential if-blocks,
        # IB checked first, but PB block still runs independently in the EA; since only
        # one can realistically set g_armed last, replicate by letting PB override if both fire)
        o1, c1 = h1_bar['open'], h1_bar['close']
        rng = hi1 - lo1
        if rng > 0 and o1 > 0:
            body = abs(c1 - o1)
            wick_lower = min(o1, c1) - lo1
            wick_upper = hi1 - max(o1, c1)
            valid_body = body >= rng * 0.02
            bull_pin = valid_body and (wick_lower >= PB_WICK_RATIO * body and wick_lower >= PB_WICK_RANGE_FRACTION * rng)
            bear_pin = valid_body and (wick_upper >= PB_WICK_RATIO * body and wick_upper >= PB_WICK_RANGE_FRACTION * rng)
            if bull_pin or bear_pin:
                armed = True
                armed_h, armed_l = hi1, lo1
                armed_dir = 1 if bull_pin else -1
                pattern = 'PB-BULL' if bull_pin else 'PB-BEAR'

        if not armed:
            continue

        # scan forward on M1 data for a breakout within ENTRY_WINDOW_H hours of bar_time
        window_end_time = bar_time + pd.Timedelta(hours=ENTRY_WINDOW_H)
        m1_start_idx = m1_index.searchsorted(bar_time)
        m1_end_idx = m1_index.searchsorted(window_end_time)
        if m1_start_idx >= len(m1):
            continue

        entered = False
        for k in range(m1_start_idx, min(m1_end_idx, len(m1))):
            bid = m1['close'].iloc[k]   # approximate bid with M1 close (no separate bid/ask in this data)
            if bid > armed_h and armed_dir >= 0:
                entry_price = bid
                stop_price = armed_l
                direction = 1
                entered = True
            elif bid < armed_l and armed_dir <= 0:
                entry_price = bid
                stop_price = armed_h
                direction = -1
                entered = True
            if entered:
                stop_dist = abs(entry_price - stop_price)
                if stop_dist <= 0:
                    entered = False
                    break
                tp_price = entry_price + stop_dist * TP_R if direction == 1 else entry_price - stop_dist * TP_R
                r_gross = simulate_forward(m1, m1_index, k, direction, entry_price, stop_price, tp_price, MAX_MINS_OPEN)
                cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
                trades.append({'symbol': symbol, 'entry_time': m1_index[k], 'pattern': pattern,
                               'r_net': r_gross - cost_r})
                trades_today[day_key] += 1
                break

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


print('Loading FTMO M1 data (resampling to H1)...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)}/{len(FILES)} instruments: {loaded}\n')

all_trades = []
for symbol in loaded:
    trades = find_trades(symbol)
    print(f'  {symbol}: {len(trades)} trades')
    all_trades.extend(trades)

df = pd.DataFrame(all_trades)
n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print(f'\n{"="*80}')
print(f'  M1GOATV2 (IB+PB, 4R) ON FTMO DATA -- FULL RESULT')
print(f'{"="*80}')
print(f'  Total trades: {n}   WR: {wr}%   PF: {pf}   Total R: {tot:+.1f}\n')

if len(df) > 0:
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    print(f'{"#"*90}')
    print(f'  MONTHLY BREAKDOWN')
    print(f'{"#"*90}')
    for period in all_periods:
        window_rv = df[df['period'] == period]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        flag = ' <- LOSING' if tot2 < 0 else ''
        print(f'  {period}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}{flag}')

print('\nDone.')
