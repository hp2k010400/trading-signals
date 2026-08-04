"""
equity_gold_diagnose_2021.py

The rolling-PF check found a real ~2-year losing stretch (Feb 2021 ->
Apr 2023). Before trying another fix blindly -- we already know a simple
D1 EMA trend filter on the equity leg failed earlier tonight, so
repeating that without new information would waste time -- this
diagnoses two things:

  1. WHICH legs actually drove the losing stretch. Broad-based across
     all 5, or concentrated in 1-2? This determines whether any fix
     should be leg-specific or blend-wide.
  2. Whether a VOLATILITY-SCALING overlay helps -- reduce (not remove)
     position size when recent realized volatility is elevated, a
     genuinely different lever from a directional trend filter. Tests
     whether cutting size during volatile/uncertain regimes reduces the
     severity of bad stretches without needing to predict direction.

Run in Codespace: python -u equity_gold_diagnose_2021.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN = 20
ATR_MULT = 3.0
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
VOL_LOOKBACK = 20   # days, for realized-vol percentile
VOL_SCALE_PCTILE = 0.75   # above this percentile of its own history, scale down
VOL_SCALE_FACTOR = 0.5    # position size multiplier when in the high-vol regime

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
    d_vol_pctile = d_atr.rolling(252).apply(lambda x: (x <= x.iloc[-1]).mean(), raw=False)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        o, c = daily['open'].iloc[i], daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        vol_pctile = d_vol_pctile.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or o <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = EQUITY_COST_POINTS[k] / stop_dist
        r_gross = (c/o - 1) * o / stop_dist
        out[daily.index[i]] = {'r': r_gross - cost_r, 'vol_pctile': vol_pctile}
    return out


def build_gold_ny():
    m1 = _m1['GOLD']; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    d_vol_pctile = d_atr.rolling(252).apply(lambda x: (x <= x.iloc[-1]).mean(), raw=False)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        day = daily.index[i]
        atr_val = d_atr.iloc[i-1]
        vol_pctile = d_vol_pctile.iloc[i-1]
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
        r_gross = (p_end/p_start - 1) * p_start / stop_dist
        out[day] = {'r': r_gross - cost_r, 'vol_pctile': vol_pctile}
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

print(f'{"#"*90}')
print(f'  CHECK 1: PER-LEG PF DURING THE LOSING STRETCH ({BAD_PERIOD_START.date()} -> {BAD_PERIOD_END.date()})')
print(f'  (compared against each leg\'s full-history PF for context)')
print(f'{"#"*90}')
for k, series in leg_series.items():
    df = pd.DataFrame([{'date': d, 'r': v['r']} for d, v in series.items()])
    full_n, full_wr, full_pf, full_tot = compute_stats(df['r'].values)
    bad_df = df[(df['date'] >= BAD_PERIOD_START) & (df['date'] <= BAD_PERIOD_END)]
    bad_n, bad_wr, bad_pf, bad_tot = compute_stats(bad_df['r'].values)
    flag = ' <- WAS LOSING HERE' if bad_tot < 0 else ''
    print(f'  {k:<8}  Full-history PF={full_pf:>5.2f}  |  During bad stretch: N={bad_n:>4} PF={bad_pf:>5.2f}{flag}')

print(f'\n{"#"*90}')
print(f'  CHECK 2: VOLATILITY-SCALING OVERLAY (reduce size when recent vol is elevated)')
print(f'  Scale to {VOL_SCALE_FACTOR}x size when ATR is above the {VOL_SCALE_PCTILE:.0%} percentile of its own trailing year')
print(f'{"#"*90}')

for label, use_scaling in [('No scaling (baseline)', False), ('With vol-scaling', True)]:
    all_dates = set.union(*[set(v.keys()) for v in leg_series.values()])
    rows = []
    for d in all_dates:
        vals = []
        for k in leg_series:
            if d in leg_series[k]:
                entry = leg_series[k][d]
                r = entry['r']
                if use_scaling and not pd.isna(entry['vol_pctile']) and entry['vol_pctile'] >= VOL_SCALE_PCTILE:
                    r = r * VOL_SCALE_FACTOR
                vals.append(r)
        if vals:
            rows.append({'date': d, 'r': np.mean(vals)})
    df = pd.DataFrame(rows)
    is_df = df[df['date'] < IS_OOS_SPLIT]
    oos_df = df[df['date'] >= IS_OOS_SPLIT]
    bad_df = df[(df['date'] >= BAD_PERIOD_START) & (df['date'] <= BAD_PERIOD_END)]
    n_is, wr_is, pf_is, tot_is = compute_stats(is_df['r'].values)
    n_oos, wr_oos, pf_oos, tot_oos = compute_stats(oos_df['r'].values)
    n_bad, wr_bad, pf_bad, tot_bad = compute_stats(bad_df['r'].values)
    print(f'  {label:<22}  IS PF={pf_is:>5.2f}   HOLDOUT PF={pf_oos:>5.2f}   BAD-STRETCH PF={pf_bad:>5.2f}')

print('\nDone.')
