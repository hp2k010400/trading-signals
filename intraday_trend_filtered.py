"""
intraday_trend_filtered.py

Direct extension of the one confirmed-real result tonight (overnight/
intraday decomposition: IS PF 1.06, holdout PF 1.13). That test was
"always long intraday" with no direction — and it lost specifically in
2018 and 2022, the two genuine bear-market years. This tests the
obvious, well-motivated fix: trade WITH the daily trend direction
instead of always assuming up.

  D1 trend bullish (close > 50-day EMA, as of YESTERDAY's close — no
  lookahead) -> go LONG at today's open, exit at today's close.
  D1 trend bearish -> go SHORT at today's open, exit at today's close.

Same 4 equity indices (DAX, NAS100, SP500, US30), same session-open-to-
close mechanic, same ATR-based R-normalization and price-point costs as
overnight_intraday_test.py — only the direction is now trend-aware
instead of always long.

Same discipline: locked IS/OOS holdout (2025-02-01, same date used all
night), checked once.

Run in Codespace: python -u intraday_trend_filtered.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN    = 20
ATR_MULT   = 3.0
EMA_LEN    = 50
RISK_PCT   = 0.5
START_BAL  = 70000
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
}
COST_POINTS = {'DAX': 1.5, 'NAS100': 1.5, 'SP500': 0.6, 'US30': 2.0}

_m1 = {}

def load(k):
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def build_trades(k):
    m1 = _m1[k]
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    d_ema = daily['close'].ewm(span=EMA_LEN, adjust=False).mean()

    rows = []
    for i in range(max(ATR_LEN, EMA_LEN) + 1, len(daily)):
        today_open = daily['open'].iloc[i]
        today_close = daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        # trend direction as of YESTERDAY's close — no lookahead
        prev_close = daily['close'].iloc[i-1]
        prev_ema = d_ema.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or today_open <= 0 or pd.isna(prev_ema):
            continue

        direction = 1 if prev_close > prev_ema else -1
        stop_dist = ATR_MULT * atr_val
        cost_r = COST_POINTS[k] / stop_dist

        raw_ret = today_close / today_open - 1
        r = direction * raw_ret * today_open / stop_dist - cost_r

        rows.append({
            'instrument': k, 'date': daily.index[i], 'year': daily.index[i].year,
            'dir': direction, 'r_net': r,
        })
    return rows


def stats(r_arr):
    if len(r_arr) == 0: return 0, 0.0, 0.0, 0.0
    w = r_arr[r_arr > 0]; l = r_arr[r_arr <= 0]
    pf = round(w.sum()/abs(l.sum()), 2) if len(l) and l.sum() != 0 else 0.0
    wr = round(len(w)/len(r_arr)*100, 1)
    return len(r_arr), wr, pf, r_arr.sum()

RPR = START_BAL * RISK_PCT / 100.0

def print_row(label, n, wr, pf, total_r, width=20):
    gbp = total_r * RPR
    print(f'  {label:<{width}}  N={n:>5}  WR={wr:>5.1f}%  PF={pf:>5.2f}  '
          f'R={total_r:>+9.2f}  £{gbp:>+10,.0f}')


print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

all_rows = []
for k in loaded:
    print(f'  Building trend-filtered intraday trades for {k}...', end=' ', flush=True)
    rows = build_trades(k)
    print(f'{len(rows)} trading days')
    all_rows.extend(rows)

df = pd.DataFrame(all_rows)
pct_long = (df['dir'] == 1).mean() * 100
print(f'\nTotal trading days: {len(df)}  ({pct_long:.0f}% long, {100-pct_long:.0f}% short)')

print(f'\n{"="*74}')
print('  IN-SAMPLE  (data start -> 2025-02-01)')
print(f'{"="*74}')
is_df = df[df['date'] < IS_OOS_SPLIT]
n, wr, pf, tot = stats(is_df['r_net'].values)
print_row('ALL INSTRUMENTS', n, wr, pf, tot)

by_inst = {}
for _, row in is_df.iterrows(): by_inst.setdefault(row['instrument'], []).append(row['r_net'])
for inst in sorted(by_inst, key=lambda x: -sum(by_inst[x])):
    rv = np.array(by_inst[inst]); n, wr, pf, tot = stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('  ' + inst + flag, n, wr, pf, tot)

by_year = {}
for _, row in is_df.iterrows(): by_year.setdefault(row['year'], []).append(row['r_net'])
print()
for yr in sorted(by_year):
    rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('    ' + str(yr) + flag, n, wr, pf, tot)

print(f'\n{"="*74}')
print('  HOLDOUT — 2025-02-01 -> present (touched ONCE — this is the real answer)')
print(f'{"="*74}')
oos_df = df[df['date'] >= IS_OOS_SPLIT]
n, wr, pf, tot = stats(oos_df['r_net'].values)
print_row('ALL INSTRUMENTS', n, wr, pf, tot)
for inst, grp in oos_df.groupby('instrument'):
    n, wr, pf, tot = stats(grp['r_net'].values)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('  ' + inst + flag, n, wr, pf, tot)

print('\nDone.')
