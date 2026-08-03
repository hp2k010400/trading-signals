"""
htf_structure_break.py

Tests the supply/demand structure-break idea directly: in a trending market,
a swing LOW that gets followed by a swing HIGH ("the low creates a high")
defines a "key low" -- the level a healthy pullback should never trade back
through. If price DOES break that key low, that's read as a reversal signal
-- go SHORT on the break. Mirrored for downtrends: a swing HIGH followed by
a swing LOW defines a "key high"; a break back above it on the relief rally
signals a bullish reversal -- go LONG.

Distinct from everything tested earlier tonight: those all traded H1
continuation breakouts (inside bar / pin bar, same direction as the range).
This is a genuine higher-timeframe (H4/D1/Weekly) REVERSAL system, entering
against the immediately-prior swing, only once structure has actually broken.

Swing points are found with a standard fixed-lag fractal (2 bars either
side) on the HTF series, filtered into a proper alternating zigzag (so two
same-type swings in a row collapse to the more extreme one). A swing is
only usable once BOTH confirming bars have closed -- no lookahead.

Entry/exit simulation still runs on the underlying M1 data bar-by-bar (same
proven method as every script tonight) rather than trusting HTF OHLC to
tell you which of high/low happened first within the bar.

TP is swept across 2R/3R/4R and ALL THREE are reported together (not
cherry-picked) specifically to avoid a fresh multiple-comparisons trap on
a brand new idea.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u htf_structure_break.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')
RISK_PCT  = 0.5
START_BAL = 70000
TP_SWEEP  = [2.0, 3.0, 4.0]
FRACTAL_LAG = 2   # bars either side to confirm a swing point

# timeframe -> (pandas resample rule, entry-watch window in bars, hold time-stop in bars)
TIMEFRAMES = {
    'H4':      ('4h', 40, 40),    # ~1 week to trigger, ~1 week max hold
    'D1':      ('1D', 20, 20),    # ~1 month to trigger, ~1 month max hold
    'WEEKLY':  ('1W', 8,  8),     # ~2 months to trigger, ~2 months max hold
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
# raw price-point cost estimate (spread+slippage), divided by each trade's
# OWN stop distance below -- never reuse an R-unit cost across different
# stop-width conventions, that silently swamped an earlier script tonight.
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


def find_zigzag_swings(htf, lag=FRACTAL_LAG):
    """Fixed-lag fractal swing points, filtered into a strict alternating
    zigzag. Returns a chronological list of dicts:
      {'type': 'HIGH'/'LOW', 'price': float, 'confirm_time': Timestamp}
    A swing at bar i is only confirmed once bar i+lag has closed -- that's
    the confirm_time used, so nothing here looks into the future."""
    highs = htf['high'].values
    lows  = htf['low'].values
    n = len(htf)
    raw = []
    for i in range(lag, n - lag):
        window_h = highs[i-lag:i+lag+1]
        window_l = lows[i-lag:i+lag+1]
        if highs[i] >= window_h.max():
            raw.append({'type':'HIGH', 'price': float(highs[i]), 'confirm_time': htf.index[i+lag]})
        if lows[i] <= window_l.min():
            raw.append({'type':'LOW', 'price': float(lows[i]), 'confirm_time': htf.index[i+lag]})
    raw.sort(key=lambda s: s['confirm_time'])

    zigzag = []
    for s in raw:
        if not zigzag:
            zigzag.append(s)
            continue
        last = zigzag[-1]
        if s['type'] == last['type']:
            # same type back-to-back -- keep only the more extreme one
            if s['type'] == 'HIGH' and s['price'] > last['price']:
                zigzag[-1] = s
            elif s['type'] == 'LOW' and s['price'] < last['price']:
                zigzag[-1] = s
        else:
            zigzag.append(s)
    return zigzag


def find_setups(symbol, tf_name, resample_rule, watch_bars, hold_bars):
    m1 = _m1[symbol]
    m1_index = m1.index
    htf = m1.resample(resample_rule).agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    htf = htf[htf['open'] > 0]
    if len(htf) < FRACTAL_LAG * 4:
        return []

    swings = find_zigzag_swings(htf)
    bar_span = pd.Timedelta(resample_rule) if resample_rule != '1W' else pd.Timedelta(weeks=1)

    setups = []
    for i in range(1, len(swings)):
        p1, p2 = swings[i-1], swings[i]   # p1 -> p2, consecutive alternating swings

        if p1['type'] == 'LOW' and p2['type'] == 'HIGH':
            # "low creates a high" -- key level is the LOW, break below = SHORT
            key_price = p1['price']
            direction = -1
        elif p1['type'] == 'HIGH' and p2['type'] == 'LOW':
            # "high creates a low" -- key level is the HIGH, break above = LONG
            key_price = p1['price']
            direction = 1
        else:
            continue

        watch_start = p2['confirm_time']
        watch_end = watch_start + bar_span * watch_bars
        window = m1[(m1_index >= watch_start) & (m1_index < watch_end)]
        if len(window) == 0:
            continue

        # scan forward bar-by-bar (real chronological order) for the break
        entry_idx_in_window = -1
        for j in range(len(window)):
            bar = window.iloc[j]
            if direction == -1 and bar['low'] < key_price:
                entry_idx_in_window = j
                break
            if direction == 1 and bar['high'] > key_price:
                entry_idx_in_window = j
                break
        if entry_idx_in_window < 0:
            continue

        entry_price = key_price
        stop_price = p2['price']   # the OTHER swing in the pair -- opposite side
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            continue

        entry_timestamp = window.index[entry_idx_in_window]
        entry_index_in_m1 = m1_index.searchsorted(entry_timestamp)
        if entry_index_in_m1 >= len(m1):
            continue

        setups.append({
            'symbol': symbol, 'tf': tf_name, 'direction': direction,
            'entry_price': entry_price, 'stop_price': stop_price,
            'stop_distance': stop_distance,
            'entry_time': entry_timestamp, 'entry_index': entry_index_in_m1,
            'hold_bars': hold_bars, 'bar_span': bar_span,
        })
    return setups


def simulate(symbol, setup, tp_r):
    m1 = _m1[symbol]
    entry_index = setup['entry_index']
    direction = setup['direction']
    entry_price = setup['entry_price']
    stop_price = setup['stop_price']
    stop_distance = setup['stop_distance']

    max_minutes = int(setup['hold_bars'] * setup['bar_span'] / pd.Timedelta(minutes=1))
    window_end = min(entry_index + 1 + max_minutes, len(m1))
    future = m1.iloc[entry_index + 1: window_end]
    if len(future) == 0:
        return -1.0, 'SL'

    if direction == 1:
        tp_price = entry_price + stop_distance * tp_r
    else:
        tp_price = entry_price - stop_distance * tp_r

    highs = future['high'].values
    lows  = future['low'].values
    closes = future['close'].values

    for k in range(len(future)):
        if direction == 1:
            if highs[k] >= tp_price:
                return tp_r, 'TP'
            if lows[k] <= stop_price:
                return -1.0, 'SL'
        else:
            if lows[k] <= tp_price:
                return tp_r, 'TP'
            if highs[k] >= stop_price:
                return -1.0, 'SL'

    final_close = closes[-1]
    if direction == 1:
        r = (final_close - entry_price) / stop_distance
    else:
        r = (entry_price - final_close) / stop_distance
    return r, 'TIMEOUT'


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

all_setups = []
for tf_name, (rule, watch_bars, hold_bars) in TIMEFRAMES.items():
    print(f'--- {tf_name} ---')
    for symbol in loaded:
        setups = find_setups(symbol, tf_name, rule, watch_bars, hold_bars)
        print(f'  {symbol}: {len(setups)} confirmed reversal setups')
        all_setups.extend(setups)
    print()

print(f'Total setups across all timeframes: {len(all_setups)}')
if len(all_setups) < 100:
    print('WARNING: fewer than 100 total setups -- treat every number below as unreliable.')

# sample sanity check -- print first 10 real setups so the logic can be
# eyeballed directly (entry level, stop, direction all make sense)
print('\nFirst 10 confirmed setups (sanity check):')
print(f'  {"TF":<8}{"Symbol":<8}{"Dir":<7}{"Entry(key lvl)":>16}{"Stop(other swing)":>20}')
for s in all_setups[:10]:
    d = 'SHORT' if s['direction'] == -1 else 'LONG'
    print(f'  {s["tf"]:<8}{s["symbol"]:<8}{d:<7}{s["entry_price"]:>16.5f}{s["stop_price"]:>20.5f}')

for tp_r in TP_SWEEP:
    print(f'\n{"="*88}')
    print(f'  TP = {tp_r}R')
    print(f'{"="*88}')

    results = []
    for s in all_setups:
        r_gross, reason = simulate(s['symbol'], s, tp_r)
        cost_r = COST_POINTS[s['symbol']] / s['stop_distance']
        r_net = r_gross - cost_r
        results.append({'tf': s['tf'], 'symbol': s['symbol'], 'entry_time': s['entry_time'],
                         'r_net': r_net, 'reason': reason})
    df = pd.DataFrame(results)
    is_df = df[df['entry_time'] < IS_OOS_SPLIT]
    oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]

    n, wr, pf, tot = compute_stats(is_df['r_net'].values)
    print_row('IN-SAMPLE (all TFs)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
    print_row('HOLDOUT (all TFs)', n, wr, pf, tot)
    print()

    for tf_name in TIMEFRAMES:
        sub_is = is_df[is_df['tf'] == tf_name]['r_net'].values
        sub_oos = oos_df[oos_df['tf'] == tf_name]['r_net'].values
        n, wr, pf, tot = compute_stats(sub_is)
        print_row(f'  {tf_name} IS', n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(sub_oos)
        print_row(f'  {tf_name} HOLDOUT', n, wr, pf, tot)

print('\nDone.')
