"""
correlation_check.py

Does gold's NY-session return actually move independently of the
equity-intraday result, or does it move with the same days? Real
diversification requires low/negative correlation, not just "a second
positive number."

Builds both daily return series on the SAME calendar days, computes
the correlation, and shows what a simple blended 50/50 book of both
would have looked like — if correlation is genuinely low, the blend
should show a smoother equity curve / better risk-adjusted number than
either alone, not just an average of the two.

Run in Codespace: python -u correlation_check.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN   = 20
ATR_MULT  = 3.0
RISK_PCT  = 0.5
START_BAL = 70000

EQUITY_FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
}
EQUITY_COST_POINTS = {'DAX': 1.5, 'NAS100': 1.5, 'SP500': 0.6, 'US30': 2.0}

GOLD_FILE = 'XAUUSD_M1_oanda.csv'
GOLD_COST_POINTS = 0.25
NY_START, NY_END = 13, 24

_m1 = {}

def load(k, fn):
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


def build_equity_intraday(k):
    m1 = _m1[k]
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)
    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        o = daily['open'].iloc[i]; c = daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or o <= 0: continue
        stop_dist = ATR_MULT * atr_val
        cost_r = EQUITY_COST_POINTS[k] / stop_dist
        r = (c/o - 1) * o / stop_dist - cost_r
        out[daily.index[i].date()] = r
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
        if pd.isna(atr_val) or atr_val <= 0: continue
        stop_dist = ATR_MULT * atr_val
        cost_r = GOLD_COST_POINTS / stop_dist
        start_ts = day + pd.Timedelta(hours=NY_START)
        end_ts   = day + pd.Timedelta(days=1)
        s_idx = mi.searchsorted(start_ts); e_idx = mi.searchsorted(end_ts) - 1
        if s_idx >= len(m1) or e_idx >= len(m1) or e_idx <= s_idx: continue
        p_start = m1['close'].values[s_idx]; p_end = m1['close'].values[e_idx]
        if p_start <= 0: continue
        r = (p_end/p_start - 1) * p_start / stop_dist - cost_r
        out[day.date()] = r
    return out


print('Loading data...')
for k, fn in EQUITY_FILES.items(): load(k, fn)
load('GOLD', GOLD_FILE)

print('Building equity-intraday series per instrument...')
equity_series = {k: build_equity_intraday(k) for k in EQUITY_FILES}

print('Building gold NY-session series...')
gold_series = build_gold_ny()

# equity BASKET daily return: average across whichever of the 4 have data that day
all_equity_dates = set.union(*[set(v.keys()) for v in equity_series.values()])
equity_basket = {}
for d in all_equity_dates:
    vals = [equity_series[k][d] for k in EQUITY_FILES if d in equity_series[k]]
    if vals:
        equity_basket[d] = np.mean(vals)

# only days where BOTH series exist
common_dates = sorted(set(equity_basket.keys()) & set(gold_series.keys()))
print(f'\nCommon trading days: {len(common_dates)}')

eq = np.array([equity_basket[d] for d in common_dates])
au = np.array([gold_series[d] for d in common_dates])

corr = np.corrcoef(eq, au)[0, 1]
print(f'\nCorrelation (equity-intraday basket vs gold-NY-session): {corr:+.3f}')
if abs(corr) < 0.2:
    print('  -> Low correlation — genuine diversification potential.')
elif abs(corr) < 0.5:
    print('  -> Moderate correlation — some diversification benefit, not huge.')
else:
    print('  -> High correlation — NOT a real diversifier, largely the same bet.')

def pf_of(r):
    w = r[r>0].sum(); l = abs(r[r<0].sum())
    return w/l if l>0 else np.nan

print(f'\nEquity-intraday basket alone: N={len(eq)}  PF={pf_of(eq):.2f}  mean={eq.mean():+.4f}  std={eq.std():.4f}')
print(f'Gold-NY-session alone:        N={len(au)}  PF={pf_of(au):.2f}  mean={au.mean():+.4f}  std={au.std():.4f}')

blend = (eq + au) / 2
print(f'50/50 blend:                  N={len(blend)}  PF={pf_of(blend):.2f}  mean={blend.mean():+.4f}  std={blend.std():.4f}')

sharpe_eq = eq.mean()/eq.std() if eq.std()>0 else np.nan
sharpe_au = au.mean()/au.std() if au.std()>0 else np.nan
sharpe_bl = blend.mean()/blend.std() if blend.std()>0 else np.nan
print(f'\nDaily Sharpe-equivalent (mean/std, higher = smoother):')
print(f'  Equity alone: {sharpe_eq:.3f}')
print(f'  Gold alone:   {sharpe_au:.3f}')
print(f'  50/50 blend:  {sharpe_bl:.3f}')
if sharpe_bl > max(sharpe_eq, sharpe_au):
    print('  -> Blend beats BOTH individual legs — real diversification benefit confirmed.')
else:
    print('  -> Blend does not beat the better individual leg — limited diversification benefit.')

print('\nDone.')
