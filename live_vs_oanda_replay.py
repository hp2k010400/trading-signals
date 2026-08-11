"""
live_vs_oanda_replay.py

Real NEWGOATv1 win rate over ~96 real trades (Aug 4-10) came out to
~42.7% -- far below the validated ~57-63% backtest rate, and a large
enough sample that this isn't easily dismissed as noise. This tests
the leading hypothesis directly: is this a FEED discrepancy (FTMO's
broker feed showing different price action than OANDA's, which the
whole backtest is built on) rather than a strategy problem?

Method: for each real trade, take its actual entry price and SL/TP
distances (as %, to normalize for any absolute price-level offset
between FTMO and OANDA -- different CFD providers can show slightly
different absolute levels for the same underlying instrument). Find
OANDA's own price at that same UTC moment, apply the SAME relative
stop/target distances to OANDA's price, then replay forward on
OANDA's REAL M1 data to see whether OANDA's price action would have
hit target or stop first. Compare that against what actually happened
on the live account.

If OANDA and FTMO mostly agree -> the feed isn't the problem, something
else explains the gap (small-sample bad luck despite the size, or a
real live-execution issue). If they meaningfully disagree -> the feed
discrepancy is real and explains a chunk of the gap.

Run in Codespace: python -u live_vs_oanda_replay.py
(needs real_trades_aug4_10.csv in the same folder)
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MAX_HOLD_MIN = 240

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
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


def replay_on_oanda(symbol, direction, entry_time, stop_pct, target_pct):
    """Returns 'WIN', 'LOSS', 'NO_DATA', or 'UNRESOLVED'."""
    if symbol not in _m1:
        return 'NO_DATA'
    m1 = _m1[symbol]
    m1_index = m1.index
    # find the OANDA bar at/just after entry_time
    idx = m1_index.searchsorted(entry_time)
    if idx >= len(m1):
        return 'NO_DATA'
    # allow a few minutes tolerance in case of small alignment gaps
    if abs((m1_index[idx] - entry_time).total_seconds()) > 300:
        # try nearest within +/- 5 min
        window = m1[(m1_index >= entry_time - pd.Timedelta(minutes=5)) & (m1_index <= entry_time + pd.Timedelta(minutes=5))]
        if len(window) == 0:
            return 'NO_DATA'
        idx = m1_index.get_loc(window.index[0])
    oanda_entry = float(m1['open'].iloc[idx])
    if oanda_entry <= 0:
        return 'NO_DATA'

    if direction == 'buy':
        oanda_sl = oanda_entry * (1 - stop_pct)
        oanda_tp = oanda_entry * (1 + target_pct)
    else:
        oanda_sl = oanda_entry * (1 + stop_pct)
        oanda_tp = oanda_entry * (1 - target_pct)

    window_end = min(idx + 1 + MAX_HOLD_MIN, len(m1))
    future = m1.iloc[idx + 1: window_end]
    if len(future) == 0:
        return 'NO_DATA'
    highs = future['high'].values
    lows = future['low'].values
    for k in range(len(future)):
        if direction == 'buy':
            if highs[k] >= oanda_tp: return 'WIN'
            if lows[k] <= oanda_sl: return 'LOSS'
        else:
            if lows[k] <= oanda_tp: return 'WIN'
            if highs[k] >= oanda_sl: return 'LOSS'
    return 'UNRESOLVED'


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

df = pd.read_csv('real_trades_aug4_10.csv')
df['entry_time_utc'] = pd.to_datetime(df['entry_time_utc'], utc=True)
df['real_result'] = df['real_profit'].apply(lambda x: 'WIN' if x > 0 else 'LOSS')

results = []
for _, row in df.iterrows():
    stop_pct = abs(row['entry_price'] - row['sl']) / row['entry_price']
    target_pct = abs(row['tp'] - row['entry_price']) / row['entry_price']
    oanda_result = replay_on_oanda(row['symbol'], row['direction'], row['entry_time_utc'], stop_pct, target_pct)
    results.append(oanda_result)

df['oanda_result'] = results

print(f'{"="*90}')
print(f'  REAL LIVE RESULT vs OANDA-IMPLIED RESULT (same entry/SL/TP, replayed on OANDA data)')
print(f'{"="*90}')
n_total = len(df)
n_win_real = (df['real_result'] == 'WIN').sum()
print(f'  Total trades: {n_total}   Real WR: {n_win_real}/{n_total} ({n_win_real/n_total*100:.1f}%)\n')

resolved = df[df['oanda_result'].isin(['WIN','LOSS'])]
n_resolved = len(resolved)
print(f'  OANDA-resolvable trades: {n_resolved}/{n_total}')
if n_resolved > 0:
    n_win_oanda = (resolved['oanda_result'] == 'WIN').sum()
    print(f'  OANDA-implied WR (same trades): {n_win_oanda}/{n_resolved} ({n_win_oanda/n_resolved*100:.1f}%)\n')

    n_agree = (resolved['real_result'] == resolved['oanda_result']).sum()
    print(f'  Agreement between FTMO real result and OANDA-implied result: {n_agree}/{n_resolved} ({n_agree/n_resolved*100:.1f}%)')

    mismatches = resolved[resolved['real_result'] != resolved['oanda_result']]
    print(f'\n  Mismatches ({len(mismatches)}):')
    for _, r in mismatches.iterrows():
        print(f'    {r["entry_time_utc"]}  {r["symbol"]:8s} {r["direction"]:5s}  '
              f'REAL={r["real_result"]:5s} (£{r["real_profit"]:+.2f})   OANDA-implied={r["oanda_result"]}')

n_no_data = (df['oanda_result'] == 'NO_DATA').sum()
n_unresolved = (df['oanda_result'] == 'UNRESOLVED').sum()
print(f'\n  NO_DATA (no matching OANDA bar): {n_no_data}')
print(f'  UNRESOLVED (neither hit within {MAX_HOLD_MIN}min on OANDA): {n_unresolved}')

print('\nDone.')
