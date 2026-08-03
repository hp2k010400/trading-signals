"""
m1goat_live_replica_audit.py

Same signal as m1goat_fresh_3day.py (H1 IB/PB breakout, 4R TP) but:
  1. TIME_STOP_HOURS = 8, matching the LIVE EA exactly (InpMaxMinsOpen=480),
     not the 72h variant tested before.
  2. Every trade's exit reason (TP / SL / TIMEOUT) is recorded, not just its
     R value.
  3. AUDIT SECTION: prints the R-value distribution for TIMEOUT trades only
     -- count, mean, min, max, how many landed near 4R vs not -- plus 25
     individual timeout trades (entry price, exit price, R). This directly
     checks the claim "trades that close after 8 hours don't go down as 4R
     they should" by showing the actual numbers, not just asserting it.

Run in Codespace: python -u m1goat_live_replica_audit.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

TAKE_PROFIT_R      = 4.0
TIME_STOP_HOURS     = 8          # matches live EA InpMaxMinsOpen=480 exactly
ENTRY_WINDOW_HOURS  = 3
MAX_TRADES_PER_DAY  = 3
SPREAD_SLIPPAGE_R   = 0.18
MIN_IB_RANGE_PCT    = 0.00015
PIN_WICK_TO_BODY    = 2.0
PIN_WICK_TO_RANGE   = 0.5

RISK_PCT  = 0.5
START_BAL = 70000
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
SESSION_HOURS = {
    'DAX':{8,9,10,13,14}, 'NAS100':{13,14,15,16}, 'SP500':{13,14,15,16},
    'US30':{13,14,15,16}, 'EURUSD':{8,9,13,14,15}, 'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9}, 'GOLD':{8,9,13,14,15},
}
SKIP_WEEKDAYS = {
    'DAX':frozenset(), 'EURUSD':frozenset(), 'GBPUSD':frozenset(),
    'USDJPY':frozenset(), 'GOLD':frozenset(),
    'NAS100':frozenset({0}), 'SP500':frozenset({0}), 'US30':frozenset({0}),
}
SPREAD_COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,'GOLD':0.08,
}

_m1 = {}

def load(symbol):
    filename = FILES[symbol]
    if not os.path.exists(filename):
        return False
    df = pd.read_csv(filename, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for col in ['open', 'high', 'low', 'close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    _m1[symbol] = df.dropna()
    return True


def is_pin_bar(open_price, high, low, close):
    body = abs(close - open_price)
    full_range = high - low
    if full_range <= 0 or body < full_range * 0.02:
        return 0
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    min_wick = max(body, full_range * 0.001)
    if upper_wick >= PIN_WICK_TO_BODY * min_wick and upper_wick >= PIN_WICK_TO_RANGE * full_range:
        return -1
    if lower_wick >= PIN_WICK_TO_BODY * min_wick and lower_wick >= PIN_WICK_TO_RANGE * full_range:
        return 1
    return 0


def find_all_setups(symbol):
    m1 = _m1[symbol]
    m1_index = m1.index
    allowed_hours = SESSION_HOURS.get(symbol, {8, 9, 13, 14})
    skip_days = SKIP_WEEKDAYS.get(symbol, frozenset())

    h1 = m1.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    h1_timestamps = list(h1.index)

    confirmed_trades = []
    trades_today = {}

    for i in range(1, len(h1_timestamps)):
        setup_time = h1_timestamps[i]

        if setup_time.dayofweek in skip_days or setup_time.dayofweek >= 5:
            continue
        if setup_time.hour not in allowed_hours:
            continue

        calendar_day = setup_time.date()
        if trades_today.get(calendar_day, 0) >= MAX_TRADES_PER_DAY:
            continue

        setup_candle = h1.iloc[i]
        previous_candle = h1.iloc[i - 1]

        watch_start = setup_time + pd.Timedelta(hours=1)
        watch_end = watch_start + pd.Timedelta(hours=ENTRY_WINDOW_HOURS)
        watch_window = m1[(m1_index >= watch_start) & (m1_index < watch_end)]
        if len(watch_window) == 0:
            continue

        setup_high = float(setup_candle['high'])
        setup_low = float(setup_candle['low'])

        is_inside_bar = (setup_candle['high'] < previous_candle['high'] and
                          setup_candle['low'] > previous_candle['low'])
        inside_bar_valid = (is_inside_bar and (setup_high - setup_low) > 0 and
                             (setup_high - setup_low) / setup_high >= MIN_IB_RANGE_PCT)

        breakout_high = setup_high
        breakout_low = setup_low
        pattern_found = False

        if symbol == 'USDJPY':
            pb_dir = is_pin_bar(float(setup_candle['open']), setup_high, setup_low, float(setup_candle['close']))
            if pb_dir != 0:
                pattern_found = True
        else:
            if inside_bar_valid:
                pattern_found = True
            else:
                pb_dir = is_pin_bar(float(setup_candle['open']), setup_high, setup_low, float(setup_candle['close']))
                if pb_dir != 0:
                    pattern_found = True

        if not pattern_found:
            continue

        direction = 0
        entry_price = 0.0
        stop_price = 0.0
        breakout_bar_index = -1

        for j in range(len(watch_window)):
            bar = watch_window.iloc[j]
            if bar['high'] > breakout_high:
                direction = 1
                entry_price = breakout_high
                stop_price = breakout_low
                breakout_bar_index = j
                break
            elif bar['low'] < breakout_low:
                direction = -1
                entry_price = breakout_low
                stop_price = breakout_high
                breakout_bar_index = j
                break

        if direction == 0:
            continue

        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            continue

        entry_timestamp = watch_window.index[breakout_bar_index]
        entry_index_in_m1 = m1_index.searchsorted(entry_timestamp)
        if entry_index_in_m1 >= len(m1):
            continue

        trades_today[calendar_day] = trades_today.get(calendar_day, 0) + 1
        confirmed_trades.append({
            'symbol': symbol, 'direction': direction,
            'entry_price': entry_price, 'stop_price': stop_price,
            'entry_time': entry_timestamp, 'entry_index': entry_index_in_m1,
            'stop_distance': stop_distance,
        })

    return confirmed_trades


def simulate_trade_outcome(symbol, entry_index, direction, entry_price, stop_price):
    """Returns (r_value, exit_reason). exit_reason is 'TP', 'SL', or 'TIMEOUT'.
    On TIMEOUT, r_value is computed from the ACTUAL close price at that bar --
    never assumed to be 4R. This is the exact mechanism being audited below."""
    m1 = _m1[symbol]
    stop_distance = abs(entry_price - stop_price)
    max_bars = TIME_STOP_HOURS * 60

    window_end = min(entry_index + 1 + max_bars, len(m1))
    future_bars = m1.iloc[entry_index + 1: window_end]
    if len(future_bars) == 0:
        return -1.0, 'SL', None

    if direction == 1:
        take_profit_price = entry_price + stop_distance * TAKE_PROFIT_R
    else:
        take_profit_price = entry_price - stop_distance * TAKE_PROFIT_R

    highs = future_bars['high'].values
    lows = future_bars['low'].values
    closes = future_bars['close'].values

    for bar_i in range(len(future_bars)):
        if direction == 1:
            if highs[bar_i] >= take_profit_price:
                return TAKE_PROFIT_R, 'TP', None
            if lows[bar_i] <= stop_price:
                return -1.0, 'SL', None
        else:
            if lows[bar_i] <= take_profit_price:
                return TAKE_PROFIT_R, 'TP', None
            if highs[bar_i] >= stop_price:
                return -1.0, 'SL', None

    final_close = closes[-1]
    final_time = future_bars.index[-1]
    if direction == 1:
        r = (final_close - entry_price) / stop_distance
    else:
        r = (entry_price - final_close) / stop_distance
    return r, 'TIMEOUT', (final_close, final_time)


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    profit_factor = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    win_rate = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), win_rate, profit_factor, r_values.sum()

RISK_PER_R = START_BAL * RISK_PCT / 100.0

def print_stats_row(label, count, win_rate, pf, total_r, width=22):
    gbp = total_r * RISK_PER_R
    print(f'  {label:<{width}}  N={count:>6}  WR={win_rate:>5.1f}%  PF={pf:>5.2f}  '
          f'R={total_r:>+9.2f}  £{gbp:>+11,.0f}')


print(f'Loading data...  (time stop = {TIME_STOP_HOURS}h, matches live EA exactly)')
loaded_symbols = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded_symbols)} instruments: {loaded_symbols}')

all_trades = []
for symbol in loaded_symbols:
    print(f'  Finding setups for {symbol}...', end=' ', flush=True)
    setups = find_all_setups(symbol)
    print(f'{len(setups)} confirmed entries')
    all_trades.extend(setups)

print(f'\nTotal trades: {len(all_trades)}')
if len(all_trades) < 100:
    print('WARNING: fewer than 100 trades — treat results as unreliable.')

results = []
for trade in all_trades:
    r_gross, reason, timeout_detail = simulate_trade_outcome(
        trade['symbol'], trade['entry_index'], trade['direction'],
        trade['entry_price'], trade['stop_price'])
    r_net = r_gross - SPREAD_COST[trade['symbol']] - SPREAD_SLIPPAGE_R
    results.append({
        'symbol': trade['symbol'], 'year': trade['entry_time'].year,
        'entry_time': trade['entry_time'], 'entry_price': trade['entry_price'],
        'direction': trade['direction'], 'r_gross': r_gross, 'r_net': r_net,
        'exit_reason': reason, 'timeout_detail': timeout_detail,
    })

# ============================================================
#  AUDIT: what actually happens to TIMEOUT trades
# ============================================================
print(f'\n{"="*78}')
print(f'  AUDIT — proving TIMEOUT exits are NOT auto-scored as 4R')
print(f'{"="*78}')
n_tp = sum(1 for t in results if t['exit_reason'] == 'TP')
n_sl = sum(1 for t in results if t['exit_reason'] == 'SL')
n_to = sum(1 for t in results if t['exit_reason'] == 'TIMEOUT')
print(f'  Exit reason breakdown: TP={n_tp}  SL={n_sl}  TIMEOUT={n_to}  (of {len(results)} total)')

timeout_trades = [t for t in results if t['exit_reason'] == 'TIMEOUT']
if timeout_trades:
    to_r = np.array([t['r_gross'] for t in timeout_trades])
    print(f'\n  TIMEOUT trades gross-R stats (before costs):')
    print(f'    count={len(to_r)}  mean={to_r.mean():+.3f}R  min={to_r.min():+.3f}R  max={to_r.max():+.3f}R')
    print(f'    % of timeout trades >= 3.9R (i.e. basically hit TP anyway): '
          f'{(to_r >= 3.9).sum() / len(to_r) * 100:.1f}%')
    print(f'    % of timeout trades that are net LOSSES (<0R): '
          f'{(to_r < 0).sum() / len(to_r) * 100:.1f}%')
    print(f'    % of timeout trades that are net WINS (>0R but <3.9R, i.e. genuinely partial): '
          f'{((to_r > 0) & (to_r < 3.9)).sum() / len(to_r) * 100:.1f}%')

    print(f'\n  First 25 individual TIMEOUT trades (entry -> actual close price used, real R):')
    print(f'  {"Symbol":<8}{"Entry time":<22}{"Dir":<6}{"Entry px":>12}{"Close px":>12}{"R (gross)":>12}')
    for t in timeout_trades[:25]:
        close_px, close_time = t['timeout_detail']
        d = 'LONG' if t['direction'] == 1 else 'SHORT'
        print(f'  {t["symbol"]:<8}{str(t["entry_time"]):<22}{d:<6}{t["entry_price"]:>12.5f}'
              f'{close_px:>12.5f}{t["r_gross"]:>+12.3f}')
else:
    print('  No timeout trades found (unexpected — check ENTRY_WINDOW/TIME_STOP logic).')

# ============================================================
#  Standard PF/WR breakdown, with locked IS/OOS holdout
# ============================================================
df = pd.DataFrame(results)
is_df = df[df['entry_time'] < IS_OOS_SPLIT]
oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]

print(f'\n{"="*78}')
print(f'  OVERALL — {TIME_STOP_HOURS}h time stop, {TAKE_PROFIT_R}R target (live EA replica)')
print(f'{"="*78}')
n, wr, pf, tot = compute_stats(df['r_net'].values)
print_stats_row('ALL (full history)', n, wr, pf, tot)

n, wr, pf, tot = compute_stats(is_df['r_net'].values)
print_stats_row('IN-SAMPLE (< 2025-02-01)', n, wr, pf, tot)
n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
print_stats_row('HOLDOUT (>= 2025-02-01)', n, wr, pf, tot)

print()
for sym in sorted(df['symbol'].unique(), key=lambda s: -df[df['symbol']==s]['r_net'].sum()):
    rv = df[df['symbol']==sym]['r_net'].values
    n, wr, pf, tot = compute_stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_stats_row('  ' + sym + flag, n, wr, pf, tot)

print()
for yr in sorted(df['year'].unique()):
    rv = df[df['year']==yr]['r_net'].values
    n, wr, pf, tot = compute_stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_stats_row('  ' + str(yr) + flag, n, wr, pf, tot)

print('\nDone.')
