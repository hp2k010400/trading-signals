"""
ftmo_montecarlo.py

UPDATED: now includes gold's NY-session leg alongside the 4 equity
indices — the confirmed second, low-correlation edge (+0.070
correlation with the equity basket, blend beats both legs on Sharpe).
This is the actual open question that hadn't been checked yet: does
the confirmed diversification benefit translate into a better pass
rate / faster timeline, or does it wash out once run through the real
FTMO constraint structure? Finding out directly instead of assuming.

Bootstraps by ENTIRE TRADING DAY across all 5 legs together (4 equity
+ gold-NY), not by individual leg — preserves the real correlation
structure between them rather than overstating diversification.

FTMO rules (same account parameters used all night):
  Start: £70,000. Target: +10% (£77,000). Daily loss limit: 5% (£3,500).
  Max total drawdown: 10% (£7,000) from peak.

Run in Codespace: python -u ftmo_montecarlo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN   = 20
ATR_MULT  = 3.0
RISK_SWEEP = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]   # % risk per instrument per trade
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 5000
MAX_SIM_DAYS = 500   # give up simulating a single run after this many days either way

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
EQUITY_LEGS = ['DAX', 'NAS100', 'SP500', 'US30']
COST_POINTS = {'DAX': 1.5, 'NAS100': 1.5, 'SP500': 0.6, 'US30': 2.0}
GOLD_COST_POINTS = 0.25
NY_START = 13   # gold NY session: 13:00 -> 24:00 UTC, the confirmed leg

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


def build_intraday_r(k):
    m1 = _m1[k]
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    out = {}
    for i in range(ATR_LEN + 1, len(daily)):
        today_open = daily['open'].iloc[i]
        today_close = daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0 or today_open <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = COST_POINTS[k] / stop_dist
        intraday_r = (today_close / today_open - 1) * today_open / stop_dist
        out[daily.index[i].date()] = intraday_r - cost_r
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
        out[day.date()] = r
    return out


print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

per_instrument = {}
for k in EQUITY_LEGS:
    if k not in loaded: continue
    print(f'  Building intraday R-series for {k}...', end=' ', flush=True)
    r = build_intraday_r(k)
    print(f'{len(r)} days')
    per_instrument[k] = r

all_legs = [k for k in EQUITY_LEGS if k in per_instrument]
if 'GOLD' in loaded:
    print(f'  Building gold NY-session R-series...', end=' ', flush=True)
    gold_r = build_gold_ny()
    print(f'{len(gold_r)} days')
    per_instrument['GOLD'] = gold_r
    all_legs = all_legs + ['GOLD']
else:
    print('  GOLD data not found — running equity-only book')

# build the JOINT day bundles — only days where ALL legs have data
all_dates = set.intersection(*[set(v.keys()) for v in per_instrument.values()])
all_dates = sorted(all_dates)
day_bundles = []
for d in all_dates:
    day_bundles.append([per_instrument[k][d] for k in all_legs])
day_bundles = np.array(day_bundles)   # shape (n_days, n_legs)
print(f'\nJoint trading days (all {len(all_legs)} legs present: {all_legs}): {len(day_bundles)}')

def simulate_one(rng, rpt):
    equity = START_BAL
    peak = START_BAL
    day_start_equity = START_BAL
    for day_i in range(MAX_SIM_DAYS):
        bundle = day_bundles[rng.integers(0, len(day_bundles))]
        day_start_equity = equity
        for r in bundle:
            equity += equity * rpt * r
        peak = max(peak, equity)
        daily_loss = (day_start_equity - equity) / START_BAL
        if daily_loss > FTMO_DAILY:
            return 'FAILED_DAILY', day_i + 1, equity
        if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
            return 'FAILED_TOTAL', day_i + 1, equity
        if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
            return 'PASSED', day_i + 1, equity
    return 'TIMEOUT', MAX_SIM_DAYS, equity


print(f'\nSweeping risk-per-trade: {RISK_SWEEP} (%), {MC_RUNS:,} runs each, '
      f'bootstrapped by whole trading day')
print(f'{"="*90}')
print(f'  {"Risk/trade":>10}  {"PASSED":>8}  {"FAILED_DAILY":>13}  {"FAILED_TOTAL":>13}  '
      f'{"TIMEOUT":>8}  {"Median days":>12}  {"P10 days":>9}  {"P90 days":>9}')
print(f'  {"-"*88}')

sweep_results = []
for risk_pct in RISK_SWEEP:
    rpt = risk_pct / 100.0
    rng = np.random.default_rng(7)   # SAME seed each time — isolates the effect of risk_pct alone
    results = [simulate_one(rng, rpt) for _ in range(MC_RUNS)]
    outcomes = pd.DataFrame(results, columns=['outcome', 'days', 'final_equity'])

    n_pass = (outcomes['outcome'] == 'PASSED').sum()
    n_daily = (outcomes['outcome'] == 'FAILED_DAILY').sum()
    n_total = (outcomes['outcome'] == 'FAILED_TOTAL').sum()
    n_timeout = (outcomes['outcome'] == 'TIMEOUT').sum()
    passed = outcomes[outcomes['outcome'] == 'PASSED']
    med = passed['days'].median() if len(passed) else float('nan')
    p10 = passed['days'].quantile(0.10) if len(passed) else float('nan')
    p90 = passed['days'].quantile(0.90) if len(passed) else float('nan')

    sweep_results.append({'risk_pct': risk_pct, 'pass_rate': n_pass/MC_RUNS*100,
                           'fail_total_rate': n_total/MC_RUNS*100, 'median_days': med})

    print(f'  {risk_pct:>9.2f}%  {n_pass:>6}/{MC_RUNS}  {n_daily:>11}/{MC_RUNS}  '
          f'{n_total:>11}/{MC_RUNS}  {n_timeout:>6}/{MC_RUNS}  {med:>12.0f}  {p10:>9.0f}  {p90:>9.0f}')

print(f'{"="*90}')
sr = pd.DataFrame(sweep_results)
best_pass = sr.loc[sr['pass_rate'].idxmax()]
print(f'\n  Best pass rate: {best_pass["risk_pct"]:.2f}% risk/trade '
      f'-> {best_pass["pass_rate"]:.1f}% pass rate, median {best_pass["median_days"]:.0f} days')
print('\nDone.')
