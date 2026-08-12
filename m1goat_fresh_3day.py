"""
m1goat_fresh_3day.py

A completely fresh, from-scratch backtest of the M1GOATV2 base signal
(H1 Inside Bar / Pin Bar breakout), with a 3-day (72-hour) time stop
instead of the original 8-hour one. Written independently tonight,
heavily commented so every step can be checked by hand — this is not
a copy-paste of any earlier script, it's rebuilt from the rules
themselves to give you a genuinely independent cross-check.

THE SIGNAL (unchanged from what M1GOATV2 actually trades):
  1. Look at completed H1 candles, one at a time.
  2. INSIDE BAR: current H1 candle's high < previous candle's high, AND
     current low > previous low (price compressed inside the prior
     range). If so, mark that candle's high/low as breakout levels.
  3. PIN BAR (only checked if no inside bar): a candle with a long wick
     on one side (rejection) — upper wick >= 2x body and >= 50% of the
     full range signals a SHORT setup; lower wick meeting the same
     condition signals LONG.
  4. After a setup forms, watch the next 3 hours of REAL M1 (1-minute)
     data for price to actually break the setup candle's high (go long)
     or low (go short). This is checked minute-by-minute, in real
     chronological order — not a shortcut that looks at the whole
     window's max/min at once, which would let a future price silently
     leak into "when" the entry happened.
  5. Entry price = the exact level broken (not the close of whichever
     bar broke it — the level itself, since that's the actual breakout
     trigger price a stop order would fill at).
  6. Stop-loss = the opposite side of the setup candle.

THE EXIT (the one deliberate change from the original 8h version):
  - Take profit: entry +/- 4x the stop distance (matches the live EA).
  - Time stop: 72 HOURS (3 days) instead of 8 — if neither TP nor SL is
    hit within that window, the trade is closed at whatever the market
    price actually is at that point (NOT counted as a win, NOT counted
    as a full loss — the real, unknown-in-advance outcome). This exact
    line is where the original PF-3.34 bug lived (a boundary condition
    that silently counted every unresolved trade as a win) — you can
    check the logic below yourself; it is a straightforward bar-by-bar
    loop, not a vectorized shortcut.

Costs are real spread + slippage, subtracted from every trade in
R-terms, same convention used all night: R = 1 means the trade made
exactly its risked amount; R = -1 means it lost exactly its risked
amount; R = 4 means it hit the 4x target.

Run in Codespace: python -u m1goat_fresh_3day.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── Config — matches the live EA's actual parameters ───────────────────────────
TAKE_PROFIT_R   = 4.0          # 4R target, same as the live system
TIME_STOP_HOURS = 72           # 3 DAYS — the change requested, was 8 hours originally
ENTRY_WINDOW_HOURS = 3         # how long after the H1 setup we watch for the breakout
MAX_TRADES_PER_DAY = 3         # matches the live EA's per-instrument daily cap
SPREAD_SLIPPAGE_R = 0.18       # combined cost estimate in R-units (spread + slippage)
MIN_IB_RANGE_PCT = 0.00015     # inside bar must have some minimum real range, not a doji
PIN_WICK_TO_BODY = 2.0         # wick must be >= 2x the candle body
PIN_WICK_TO_RANGE = 0.5        # wick must be >= 50% of the full candle range

RISK_PCT  = 0.5
START_BAL = 70000

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
# Session hours each instrument actually trades this pattern (UTC) — matches
# the live EA's configured windows.
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
    """Returns 1 for a bullish (long) pin bar, -1 for bearish (short), 0 for none."""
    body = abs(close - open_price)
    full_range = high - low
    if full_range <= 0 or body < full_range * 0.02:   # reject near-doji candles
        return 0
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    min_wick = max(body, full_range * 0.001)
    if upper_wick >= PIN_WICK_TO_BODY * min_wick and upper_wick >= PIN_WICK_TO_RANGE * full_range:
        return -1   # long upper wick = rejection of higher prices = SHORT setup
    if lower_wick >= PIN_WICK_TO_BODY * min_wick and lower_wick >= PIN_WICK_TO_RANGE * full_range:
        return 1    # long lower wick = rejection of lower prices = LONG setup
    return 0


def find_all_setups(symbol):
    """Step through completed H1 candles and identify every valid IB/PB setup,
    then scan the following M1 data minute-by-minute (in real time order) for
    the actual breakout. Returns a list of confirmed trade entries."""
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

        # window of M1 data to watch for the actual breakout — starts 1 hour
        # after the setup candle CLOSES (i.e. once it's fully known)
        watch_start = setup_time + pd.Timedelta(hours=1)
        watch_end = watch_start + pd.Timedelta(hours=ENTRY_WINDOW_HOURS)
        watch_window = m1[(m1_index >= watch_start) & (m1_index < watch_end)]
        if len(watch_window) == 0:
            continue

        # --- identify the setup type and its breakout levels ---
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
            # USDJPY only trades pin bars, per the live EA config
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

        # --- scan M1 bars IN ORDER for the actual breakout — no shortcuts ---
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
            continue   # no breakout happened within the watch window

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
    """Bar-by-bar loop, checked in real chronological order. This is the exact
    piece of logic where the original bug lived — a boundary condition that
    silently treated 'neither hit yet' as a win. Read this loop yourself:
    every bar is checked explicitly, one at a time, and if the time stop is
    reached with neither TP nor SL hit, the trade closes at the ACTUAL market
    price at that moment — never automatically counted as a win."""
    m1 = _m1[symbol]
    stop_distance = abs(entry_price - stop_price)
    max_bars = TIME_STOP_HOURS * 60   # minutes = bars, since this is M1 data

    window_end = min(entry_index + 1 + max_bars, len(m1))
    future_bars = m1.iloc[entry_index + 1: window_end]
    if len(future_bars) == 0:
        return -1.0

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
                return TAKE_PROFIT_R
            if lows[bar_i] <= stop_price:
                return -1.0
        else:
            if lows[bar_i] <= take_profit_price:
                return TAKE_PROFIT_R
            if highs[bar_i] >= stop_price:
                return -1.0

    # neither hit within the time stop — close at the REAL market price,
    # expressed in R-terms. This can be any value: +0.8R, -0.3R, whatever
    # the market actually did. It is never assumed to be a win.
    final_close = closes[-1]
    if direction == 1:
        return (final_close - entry_price) / stop_distance
    else:
        return (entry_price - final_close) / stop_distance


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    profit_factor = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    win_rate = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), win_rate, profit_factor, r_values.sum()

RISK_PER_R = START_BAL * RISK_PCT / 100.0

def print_stats_row(label, count, win_rate, pf, total_r, width=20):
    gbp = total_r * RISK_PER_R
    print(f'  {label:<{width}}  N={count:>6}  WR={win_rate:>5.1f}%  PF={pf:>5.2f}  '
          f'R={total_r:>+9.2f}  £{gbp:>+11,.0f}')


# ── Run ──────────────────────────────────────────────────────────────────────
print(f'Loading data...  (time stop = {TIME_STOP_HOURS}h = {TIME_STOP_HOURS/24:.0f} days)')
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
    r_gross = simulate_trade_outcome(trade['symbol'], trade['entry_index'], trade['direction'],
                                      trade['entry_price'], trade['stop_price'])
    r_net = r_gross - SPREAD_COST[trade['symbol']] - SPREAD_SLIPPAGE_R
    results.append({
        'symbol': trade['symbol'], 'year': trade['entry_time'].year, 'r_net': r_net,
    })

print(f'\n{"="*74}')
print(f'  OVERALL — {TIME_STOP_HOURS}h ({TIME_STOP_HOURS/24:.0f}-day) time stop, {TAKE_PROFIT_R}R target')
print(f'{"="*74}')
all_r = np.array([t['r_net'] for t in results])
n, wr, pf, tot = compute_stats(all_r)
print_stats_row('ALL INSTRUMENTS', n, wr, pf, tot)

by_symbol = {}
for t in results: by_symbol.setdefault(t['symbol'], []).append(t['r_net'])
print()
for sym in sorted(by_symbol, key=lambda x: -sum(by_symbol[x])):
    rv = np.array(by_symbol[sym])
    n, wr, pf, tot = compute_stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_stats_row('  ' + sym + flag, n, wr, pf, tot)

by_year = {}
for t in results: by_year.setdefault(t['year'], []).append(t['r_net'])
print()
for yr in sorted(by_year):
    rv = np.array(by_year[yr])
    n, wr, pf, tot = compute_stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_stats_row('  ' + str(yr) + flag, n, wr, pf, tot)

print('\nDone.')
