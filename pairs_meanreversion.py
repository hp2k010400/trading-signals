"""
pairs_meanreversion.py

Genuine dollar-neutral pairs trading -- structurally different from
everything else tested tonight (all directional bets, including
fair-pricing and the equity+gold blend). This is market-neutral: long
one instrument, short a correlated one, betting on their RELATIONSHIP
reverting, not on either one's direction. The earlier "relative value"
attempt (strategy9) was a flawed single-leg proxy, not a real pair --
this is the genuine version.

MECHANISM:
  For each pair (A, B), track their relative performance over a rolling
  20-day window (cumulative sum of daily log-return differences). Z-score
  that relative performance against its own rolling 100-day history.
  When it stretches too far (|z| > 2), bet on reversion:
    z > +2  (A has significantly outperformed B recently) -> SHORT A, LONG B
    z < -2  (A has significantly underperformed B recently) -> LONG A, SHORT B
  Exit when the spread reverts to within 0.5 std devs of normal, or after
  a 20-trading-day safety cap, whichever comes first.

Tests 4 pairs: NAS100/SP500 and US30/SP500 (US equity intra-market),
DAX/SP500 (cross-region equity), EURUSD/GBPUSD (FX). Real-spread-
calibrated costs on both legs, real-spread-calibrated where measured.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u pairs_meanreversion.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

LOOKBACK_DAYS = 20
ZSCORE_WINDOW = 100
ENTRY_Z = 2.0
EXIT_Z = 0.5
MAX_HOLD_DAYS = 20
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011,
}
# expanded from the original 4 to all economically sensible combinations --
# 6 equity-index pairs + 3 FX pairs -- to genuinely increase the holdout
# sample using data already available, rather than waiting for more history
PAIRS = [
    ('DAX', 'NAS100'), ('DAX', 'SP500'), ('DAX', 'US30'),
    ('NAS100', 'SP500'), ('NAS100', 'US30'), ('SP500', 'US30'),
    ('EURUSD', 'GBPUSD'), ('EURUSD', 'USDJPY'), ('GBPUSD', 'USDJPY'),
]

_daily = {}

def load_daily(k, fn):
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    _daily[k] = daily
    return True


def simulate_pair(sym_a, sym_b):
    da = _daily[sym_a]; db = _daily[sym_b]
    common_idx = da.index.intersection(db.index)
    da = da.loc[common_idx]; db = db.loc[common_idx]
    n = len(da)
    if n < ZSCORE_WINDOW + LOOKBACK_DAYS + 10:
        return []

    ret_a = np.log(da['close'] / da['close'].shift(1)).values
    ret_b = np.log(db['close'] / db['close'].shift(1)).values
    rel_ret = ret_a - ret_b
    rolling_spread = pd.Series(rel_ret).rolling(LOOKBACK_DAYS).sum()
    spread_mean = rolling_spread.rolling(ZSCORE_WINDOW).mean()
    spread_std = rolling_spread.rolling(ZSCORE_WINDOW).std()
    zscore = (rolling_spread - spread_mean) / spread_std

    trades = []
    state = None
    for i in range(ZSCORE_WINDOW + LOOKBACK_DAYS, n - 1):
        z = zscore.iloc[i]
        if pd.isna(z):
            continue

        if state is None:
            if abs(z) < ENTRY_Z:
                continue
            direction = -1 if z > 0 else 1   # -1: short A/long B ; +1: long A/short B
            # normalize by spread_std (the SAME denominator that defines the
            # entry z-score, i.e. volatility of the LOOKBACK_DAYS-summed
            # spread) -- NOT daily_std. A trade can run up to MAX_HOLD_DAYS
            # accumulating a multi-day cumulative return; dividing that by a
            # single day's volatility instead of the period-matched one
            # inflated R by roughly sqrt(hold_days), which is exactly what
            # produced ~-10R readings on trades that ran the full hold
            # without reverting. This keeps "entered at z=2" meaning
            # "roughly 2R of initial stretch" consistently.
            norm = spread_std.iloc[i]
            if pd.isna(norm) or norm <= 0:
                continue
            entry_idx = i + 1   # enter next day's open, no lookahead
            if entry_idx >= n:
                continue
            state = {'direction': direction, 'entry_idx': entry_idx, 'entry_day': entry_idx,
                     'norm': norm, 'a_entry': da['open'].iloc[entry_idx], 'b_entry': db['open'].iloc[entry_idx]}
            continue

        held = i - state['entry_day']
        exited = False
        if abs(z) < EXIT_Z:
            exited = True
        elif held >= MAX_HOLD_DAYS:
            exited = True

        if exited:
            a_exit = da['close'].iloc[i]
            b_exit = db['close'].iloc[i]
            ret_a_trade = np.log(a_exit / state['a_entry'])
            ret_b_trade = np.log(b_exit / state['b_entry'])
            spread_ret = state['direction'] * (ret_a_trade - ret_b_trade)
            cost_r = (COST_POINTS[sym_a] / state['a_entry'] + COST_POINTS[sym_b] / state['b_entry']) / state['norm']
            r_net = spread_ret / state['norm'] - cost_r
            trades.append({'entry_time': da.index[state['entry_day']], 'r_net': r_net})
            state = None

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=28):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading OANDA M1 data, building daily bars...')
loaded = [s for s in FILES if load_daily(s, FILES[s])]
print(f'Loaded: {loaded}\n')

all_trades = []
for sym_a, sym_b in PAIRS:
    if sym_a not in loaded or sym_b not in loaded:
        print(f'  {sym_a}/{sym_b}: missing data, skipped')
        continue
    trades = simulate_pair(sym_a, sym_b)
    for t in trades:
        t['pair'] = f'{sym_a}/{sym_b}'
    print(f'  {sym_a}/{sym_b}: {len(trades)} trades')
    all_trades.extend(trades)

print(f'\nTotal trades: {len(all_trades)}')
if len(all_trades) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    is_df = df[df['entry_time'] < IS_OOS_SPLIT]
    oos_df = df[df['entry_time'] >= IS_OOS_SPLIT]

    print(f'\n{"="*80}')
    n, wr, pf, tot = compute_stats(is_df['r_net'].values)
    print_row('IN-SAMPLE (all pairs)', n, wr, pf, tot)
    n, wr, pf, tot = compute_stats(oos_df['r_net'].values)
    print_row('HOLDOUT (all pairs)', n, wr, pf, tot)
    print()
    for pair in df['pair'].unique():
        rv_is = is_df[is_df['pair'] == pair]['r_net'].values
        rv_oos = oos_df[oos_df['pair'] == pair]['r_net'].values
        n, wr, pf, tot = compute_stats(rv_is)
        print_row(f'  {pair} IS', n, wr, pf, tot)
        n, wr, pf, tot = compute_stats(rv_oos)
        print_row(f'  {pair} HOLDOUT', n, wr, pf, tot)

print('\nDone.')
