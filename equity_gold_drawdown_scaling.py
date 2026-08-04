"""
equity_gold_drawdown_scaling.py

Third attempt at the 2021-2023 losing stretch, genuinely different from
the two that failed (intraday stop-loss: no effect; volatility-scaling:
made things slightly worse). Both of those reacted to MARKET conditions
(price volatility). This reacts to the STRATEGY'S OWN recent
performance instead -- a standard risk-management technique: trade
smaller after the strategy itself has been losing, trade full size once
it's recovered. Different mechanism: this isn't trying to predict when
a bad regime is coming, it's responding to evidence that one is already
underway.

Mechanism: track a trailing 60-trading-day sum of the blend's own R
values. When that trailing sum is negative (the strategy has been net
losing recently), scale today's position to 0.5x. When positive, trade
full size. Sequential, no lookahead -- today's scaling only depends on
R values from strictly earlier days.

Compares baseline (no scaling) vs drawdown-scaled, overall and
specifically during the known bad stretch (Feb 2021 -> Apr 2023).

Run in Codespace: python -u equity_gold_drawdown_scaling.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN = 20
ATR_MULT = 3.0
TRAILING_WINDOW = 60
SCALE_FACTOR = 0.5
BAD_PERIOD_START = pd.Timestamp('2021-02-01', tz='UTC')
BAD_PERIOD_END   = pd.Timestamp('2023-04-30', tz='UTC')
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

EQUITY_FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
}
EQUITY_COST_POINTS = {'DAX': 1.33, 'NAS100': 1.5, 'SP500': 0.6, 'US30': 2.0}
GOLD_FILE = 'XAUUSD_M1_oanda.csv'
GOLD_COST_POINTS = 0.40
NY_START = 13

_m1 = {}

def load(k, fn):
    if not os.path.exists(fn):
        return False
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


def build_equity_intraday(k):
    m1 = _m1[k]
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        o, c = daily['open'].iloc[i], daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or o <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = EQUITY_COST_POINTS[k] / stop_dist
        r = (c/o - 1) * o / stop_dist - cost_r
        out[daily.index[i]] = r
    return out


def build_gold_ny():
    m1 = _m1['GOLD']; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        day = daily.index[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = GOLD_COST_POINTS / stop_dist
        start_ts = day + pd.Timedelta(hours=NY_START)
        end_ts   = day + pd.Timedelta(days=1)
        s_idx = mi.searchsorted(start_ts); e_idx = mi.searchsorted(end_ts) - 1
        if s_idx >= len(m1) or e_idx >= len(m1) or e_idx <= s_idx: continue
        p_start = m1['close'].values[s_idx]; p_end = m1['close'].values[e_idx]
        if p_start <= 0: continue
        r = (p_end/p_start - 1) * p_start / stop_dist - cost_r
        out[day] = r
    return out


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()


print('Loading OANDA M1 data...')
for k, fn in EQUITY_FILES.items(): load(k, fn)
load('GOLD', GOLD_FILE)
print('Loaded.\n')

leg_series = {k: build_equity_intraday(k) for k in EQUITY_FILES}
leg_series['GOLD'] = build_gold_ny()

all_dates = sorted(set.union(*[set(v.keys()) for v in leg_series.values()]))
rows = []
for d in all_dates:
    vals = [leg_series[k][d] for k in leg_series if d in leg_series[k]]
    if vals:
        rows.append({'date': d, 'r': np.mean(vals)})
df = pd.DataFrame(rows).sort_values('date').reset_index(drop=True)

# baseline (unscaled)
df['r_baseline'] = df['r']

# drawdown-scaled: trailing TRAILING_WINDOW-day sum of the BASELINE R,
# known only from strictly earlier days (shift(1) before the rolling sum)
trailing_r = df['r_baseline'].shift(1).rolling(TRAILING_WINDOW).sum()
df['scale'] = np.where(trailing_r < 0, SCALE_FACTOR, 1.0)
df['r_scaled'] = df['r_baseline'] * df['scale']

for label, col in [('No scaling (baseline)', 'r_baseline'), ('Drawdown-scaled', 'r_scaled')]:
    is_df = df[df['date'] < IS_OOS_SPLIT]
    oos_df = df[df['date'] >= IS_OOS_SPLIT]
    bad_df = df[(df['date'] >= BAD_PERIOD_START) & (df['date'] <= BAD_PERIOD_END)]
    n_is, wr_is, pf_is, tot_is = compute_stats(is_df[col].values)
    n_oos, wr_oos, pf_oos, tot_oos = compute_stats(oos_df[col].values)
    n_bad, wr_bad, pf_bad, tot_bad = compute_stats(bad_df[col].values)
    print(f'  {label:<24}  IS PF={pf_is:>5.2f} R={tot_is:>+7.2f}   '
          f'HOLDOUT PF={pf_oos:>5.2f} R={tot_oos:>+7.2f}   '
          f'BAD-STRETCH PF={pf_bad:>5.2f} R={tot_bad:>+7.2f}')

pct_scaled = (df['scale'] < 1.0).mean() * 100
print(f'\n  % of days trading at reduced size: {pct_scaled:.1f}%')

print('\nDone.')
