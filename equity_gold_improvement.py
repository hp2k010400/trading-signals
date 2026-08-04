"""
equity_gold_improvement.py

The original ATR-multiplier sweep didn't work -- on this strategy, the
"ATR stop" is only a normalizing denominator (for expressing return in
R-units), not a real executed barrier, since the position just holds
from open to close regardless of what happens in between. Scaling that
denominator rescales every return by the same constant, which can never
change PF -- confirmed directly in a smoke test (identical PF at every
multiplier tested).

This replaces that with a REAL test: adding an actual intraday stop-loss
that can trigger and cut a losing day short, instead of holding to the
close no matter how far it moves against the position. Scans real M1
bars within each day (equity legs) / NY session (gold leg) -- if price
trades through the stop level before the natural close, exit there
instead. Sweeps stop tightness (1.5x/2.0x/2.5x/3.0x ATR, plus "no stop"
i.e. current behaviour as the baseline for comparison) to see whether
cutting losers short intraday genuinely improves PF or just gives up
recovery days that would have closed positive by end of session.

Also keeps the real-spread-calibrated costs (DAX/GOLD use measured
Market Watch spreads, others still estimated) and the rolling 12-month
PF stability check on the best-performing configuration found.

IS/OOS SPLIT -- LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u equity_gold_improvement.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN = 20
BASE_ATR_MULT = 3.0   # sizing/normalization denominator -- unchanged, confirmed not to affect PF
STOP_SWEEP = [None, 3.0, 2.5, 2.0, 1.5]   # None = no intraday stop (current/baseline behaviour)
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


def build_equity_intraday(k, stop_mult):
    """Long from day open to day close, unless stop_mult is set and price
    trades through open - stop_mult*ATR intraday first, in which case exit
    there instead (real M1 scan, no lookahead -- stop check happens bar by
    bar in chronological order)."""
    m1 = _m1[k]; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        day = daily.index[i]
        o = daily['open'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or o <= 0:
            continue
        norm_dist = BASE_ATR_MULT * atr_val
        cost_r = EQUITY_COST_POINTS[k] / norm_dist

        day_start = day
        day_end = day + pd.Timedelta(days=1)
        s_idx = mi.searchsorted(day_start)
        e_idx = mi.searchsorted(day_end) - 1
        if s_idx >= len(m1) or e_idx >= len(m1) or e_idx <= s_idx:
            continue

        exit_price = m1['close'].values[e_idx]   # default: hold to close
        if stop_mult is not None:
            stop_price = o - stop_mult * atr_val
            lows = m1['low'].values[s_idx:e_idx+1]
            hit = np.where(lows <= stop_price)[0]
            if len(hit) > 0:
                exit_price = stop_price   # stopped out intraday

        r = (exit_price / o - 1) * o / norm_dist - cost_r
        out[day] = r
    return out


def build_gold_ny(stop_mult):
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
        norm_dist = BASE_ATR_MULT * atr_val
        cost_r = GOLD_COST_POINTS / norm_dist

        start_ts = day + pd.Timedelta(hours=NY_START)
        end_ts   = day + pd.Timedelta(days=1)
        s_idx = mi.searchsorted(start_ts); e_idx = mi.searchsorted(end_ts) - 1
        if s_idx >= len(m1) or e_idx >= len(m1) or e_idx <= s_idx:
            continue
        p_start = m1['close'].values[s_idx]
        if p_start <= 0:
            continue

        exit_price = m1['close'].values[e_idx]
        if stop_mult is not None:
            stop_price = p_start - stop_mult * atr_val
            lows = m1['low'].values[s_idx:e_idx+1]
            hit = np.where(lows <= stop_price)[0]
            if len(hit) > 0:
                exit_price = stop_price

        r = (exit_price / p_start - 1) * p_start / norm_dist - cost_r
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

print(f'{"#"*90}')
print('  CHECK 1: INTRADAY STOP-LOSS SWEEP (blend of all 5 legs)')
print(f'{"#"*90}')
results_by_stop = {}
for stop_mult in STOP_SWEEP:
    equity_series = {k: build_equity_intraday(k, stop_mult) for k in EQUITY_FILES}
    gold_series = build_gold_ny(stop_mult)

    all_dates = set.union(*[set(v.keys()) for v in equity_series.values()]) | set(gold_series.keys())
    rows = []
    for d in all_dates:
        vals = [equity_series[k][d] for k in EQUITY_FILES if d in equity_series[k]]
        if d in gold_series:
            vals.append(gold_series[d])
        if vals:
            rows.append({'date': d, 'r': np.mean(vals)})
    df = pd.DataFrame(rows)
    is_df = df[df['date'] < IS_OOS_SPLIT]
    oos_df = df[df['date'] >= IS_OOS_SPLIT]
    n_is, wr_is, pf_is, tot_is = compute_stats(is_df['r'].values)
    n_oos, wr_oos, pf_oos, tot_oos = compute_stats(oos_df['r'].values)
    label = 'No stop (baseline)' if stop_mult is None else f'{stop_mult:.1f}x ATR stop'
    print(f'  {label:<20}  IS: N={n_is:>5} WR={wr_is:>5.1f}% PF={pf_is:>5.2f}   '
          f'HOLDOUT: N={n_oos:>5} WR={wr_oos:>5.1f}% PF={pf_oos:>5.2f}')
    results_by_stop[stop_mult] = df

# ============================================================
#  CHECK 2: rolling 12-month PF on whichever config looks best
#  (printed for baseline AND the tightest stop tested -- compare both)
# ============================================================
for label, stop_mult in [('No stop (baseline)', None), ('1.5x ATR stop', 1.5)]:
    print(f'\n{"#"*90}')
    print(f'  CHECK 2: ROLLING 12-MONTH PF -- {label}')
    print(f'{"#"*90}')
    df = results_by_stop[stop_mult].copy()
    df['month'] = df['date'].dt.to_period('M')
    df = df.sort_values('date')
    months_sorted = sorted(df['month'].unique())
    for i in range(11, len(months_sorted)):
        window_months = months_sorted[i-11:i+1]
        window_rv = df[df['month'].isin(window_months)]['r'].values
        n, wr, pf, tot = compute_stats(window_rv)
        flag = ' <- LOSING WINDOW' if tot < 0 else ''
        print(f'  {window_months[0]} -> {window_months[-1]}   N={n:>5}  PF={pf:>5.2f}{flag}')

print('\nDone.')
