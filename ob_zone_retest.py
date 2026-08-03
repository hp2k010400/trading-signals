"""
ob_zone_retest.py

Tests the EXACT rule from the video, not a generic approximation:

  1. Find a swing LOW, then find the candle where price CLOSES back above
     the swing HIGH that came before it -- that's "the candle that created
     the break of structure" (BOS).
  2. Go ONE candle before the BOS candle. That candle should be the
     opposite colour (red, for a bullish BOS). Mark the zone "from the
     close backwards" -- top = that candle's CLOSE, bottom = its LOW.
     That's the demand zone.
  3. Wait for price to retrace back INTO that exact zone (touch the top),
     enter LONG there expecting a bounce/continuation of the original move
     -- NOT a break. Stop below the zone.

Mirrored exactly for bearish: swing HIGH -> BOS candle closes below the
prior swing LOW -> one candle before = green candle -> supply zone from
its CLOSE (bottom) to its HIGH (top) -> SHORT on retest.

This is the opposite trade direction from htf_structure_break.py (which
tested trading the BREAK itself as a reversal). This one trades the
BOUNCE off a precisely-defined order block, which is what the video
actually describes.

Entry/exit simulated on real M1 bars, bar-by-bar, same proven method used
all night. TP swept 2R/3R/4R, all three reported (not cherry-picked).

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u ob_zone_retest.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')
RISK_PCT  = 0.5
START_BAL = 70000
TP_SWEEP  = [2.0, 3.0, 4.0]
FRACTAL_LAG = 2

# timeframe -> (resample rule, how many bars to search forward for the BOS
# after the swing confirms, how many bars to watch for the retest, hold bars)
TIMEFRAMES = {
    'H4': ('4h', 30, 30, 40),
    'D1': ('1D', 20, 20, 20),
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


def find_zigzag_swings(htf, lag=FRACTAL_LAG):
    highs = htf['high'].values
    lows  = htf['low'].values
    n = len(htf)
    raw = []
    for i in range(lag, n - lag):
        window_h = highs[i-lag:i+lag+1]
        window_l = lows[i-lag:i+lag+1]
        if highs[i] >= window_h.max():
            raw.append({'type':'HIGH', 'price': float(highs[i]), 'idx': i})
        if lows[i] <= window_l.min():
            raw.append({'type':'LOW', 'price': float(lows[i]), 'idx': i})
    raw.sort(key=lambda s: s['idx'])

    zigzag = []
    for s in raw:
        if not zigzag:
            zigzag.append(s)
            continue
        last = zigzag[-1]
        if s['type'] == last['type']:
            if s['type'] == 'HIGH' and s['price'] > last['price']:
                zigzag[-1] = s
            elif s['type'] == 'LOW' and s['price'] < last['price']:
                zigzag[-1] = s
        else:
            zigzag.append(s)
    return zigzag


def find_ob_setups(symbol, tf_name, resample_rule, bos_search_bars, retest_watch_bars, hold_bars):
    m1 = _m1[symbol]
    m1_index = m1.index
    htf = m1.resample(resample_rule).agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    htf = htf[htf['open'] > 0]
    if len(htf) < FRACTAL_LAG * 6:
        return []

    swings = find_zigzag_swings(htf)
    bar_span = pd.Timedelta(resample_rule)
    n = len(htf)
    setups = []

    for i in range(1, len(swings)):
        cur, prev = swings[i], swings[i-1]

        # --- BULLISH: swing LOW confirmed, prior swing was a HIGH (resistance) ---
        if cur['type'] == 'LOW' and prev['type'] == 'HIGH':
            resistance = prev['price']
            confirm_idx = cur['idx'] + FRACTAL_LAG   # bar index where this LOW is actually confirmed
            search_end = min(confirm_idx + bos_search_bars, n)
            bos_idx = -1
            for k in range(confirm_idx + 1, search_end):
                if htf['close'].iloc[k] > resistance:
                    bos_idx = k
                    break
            if bos_idx <= 0:
                continue
            origin = htf.iloc[bos_idx - 1]
            if not (origin['close'] < origin['open']):   # must be opposite colour (red)
                continue
            zone_top = float(origin['close'])
            zone_bottom = float(origin['low'])
            if zone_top <= zone_bottom:
                continue
            direction = 1

        # --- BEARISH: swing HIGH confirmed, prior swing was a LOW (support) ---
        elif cur['type'] == 'HIGH' and prev['type'] == 'LOW':
            support = prev['price']
            confirm_idx = cur['idx'] + FRACTAL_LAG
            search_end = min(confirm_idx + bos_search_bars, n)
            bos_idx = -1
            for k in range(confirm_idx + 1, search_end):
                if htf['close'].iloc[k] < support:
                    bos_idx = k
                    break
            if bos_idx <= 0:
                continue
            origin = htf.iloc[bos_idx - 1]
            if not (origin['close'] > origin['open']):   # must be opposite colour (green)
                continue
            zone_bottom = float(origin['close'])
            zone_top = float(origin['high'])
            if zone_top <= zone_bottom:
                continue
            direction = -1
        else:
            continue

        # watch for the retest starting once the BOS candle itself has closed
        watch_start = htf.index[bos_idx] + bar_span
        watch_end = watch_start + bar_span * retest_watch_bars
        window = m1[(m1_index >= watch_start) & (m1_index < watch_end)]
        if len(window) == 0:
            continue

        entry_j = -1
        for j in range(len(window)):
            bar = window.iloc[j]
            if direction == 1 and bar['low'] <= zone_top:
                if bar['low'] <= zone_bottom:
                    entry_j = -2   # gapped/blew straight through the zone same bar -- ambiguous, skip
                else:
                    entry_j = j
                break
            if direction == -1 and bar['high'] >= zone_bottom:
                if bar['high'] >= zone_top:
                    entry_j = -2
                else:
                    entry_j = j
                break
        if entry_j < 0:
            continue

        entry_price = zone_top if direction == 1 else zone_bottom
        stop_price = zone_bottom if direction == 1 else zone_top
        stop_distance = abs(entry_price - stop_price)
        if stop_distance <= 0:
            continue

        entry_timestamp = window.index[entry_j]
        entry_index_in_m1 = m1_index.searchsorted(entry_timestamp)
        if entry_index_in_m1 >= len(m1):
            continue

        setups.append({
            'symbol': symbol, 'tf': tf_name, 'direction': direction,
            'entry_price': entry_price, 'stop_price': stop_price,
            'stop_distance': stop_distance,
            'entry_time': entry_timestamp, 'entry_index': entry_index_in_m1,
            'hold_bars': hold_bars, 'bar_span': bar_span,
            'zone_top': zone_top, 'zone_bottom': zone_bottom,
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
for tf_name, (rule, bos_bars, retest_bars, hold_bars) in TIMEFRAMES.items():
    print(f'--- {tf_name} ---')
    for symbol in loaded:
        setups = find_ob_setups(symbol, tf_name, rule, bos_bars, retest_bars, hold_bars)
        print(f'  {symbol}: {len(setups)} confirmed OB retest setups')
        all_setups.extend(setups)
    print()

print(f'Total setups across all timeframes: {len(all_setups)}')
if len(all_setups) < 100:
    print('WARNING: fewer than 100 total setups -- treat every number below as unreliable.')

print('\nFirst 10 confirmed setups (sanity check -- eyeball these):')
print(f'  {"TF":<6}{"Symbol":<8}{"Dir":<7}{"ZoneTop":>14}{"ZoneBot":>14}{"Entry":>14}{"Stop":>14}')
for s in all_setups[:10]:
    d = 'LONG' if s['direction'] == 1 else 'SHORT'
    print(f'  {s["tf"]:<6}{s["symbol"]:<8}{d:<7}{s["zone_top"]:>14.5f}{s["zone_bottom"]:>14.5f}'
          f'{s["entry_price"]:>14.5f}{s["stop_price"]:>14.5f}')

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

    for sym in sorted(df['symbol'].unique()):
        rv = df[df['symbol'] == sym]['r_net'].values
        n, wr, pf, tot = compute_stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('  ' + sym + flag, n, wr, pf, tot)

print('\nDone.')
