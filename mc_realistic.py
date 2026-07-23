"""
mc_realistic.py
Realistic FTMO GBP70k pass simulation.

Instead of sampling individual trades with averages, this script:
  1. Rebuilds the actual OOS daily P&L series from all 9 instruments
  2. Bootstrap resamples those real days (including 0-signal days)
  3. Simulates the FTMO challenge using the real distribution

This captures actual signal frequency, clustered losses, flat periods,
and instrument correlation — much more honest than parametric MC.

Run AFTER backtest_goat_suite.py has been run (shares the same data files).
Run: python mc_realistic.py
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
ACCOUNT     = 70_000
RISK_FRAC   = 0.005
FTMO_TARGET = 77_000
FTMO_FLOOR  = 63_000
FTMO_DAILY  = 3_500
N_SIMS      = 100_000
TP_R        = 4.0
SLIPPAGE    = 0.10
MAX_PD      = 3
WIN_HOURS   = 3

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
}
COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,
    'GOLD':0.08,'NATGAS':0.15,
}
H1_HOURS = {
    'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},'NATGAS':{13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset({4}),'EURUSD':frozenset({4}),'GBPUSD':frozenset({4}),
    'USDJPY':frozenset({4}),'GOLD':frozenset({4}),'NATGAS':frozenset({4}),
    'NAS100':frozenset({0,4}),'SP500':frozenset({0,4}),'US30':frozenset({0,4}),
}
WICK_BODY  = 2.0
WICK_RANGE = 0.5

_m1 = {}

def load(k):
    import os
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True

def vsim(k, ep, d, entry, sl, max_bars=480):
    m1 = _m1[k]; sl_d = abs(entry-sl)
    if sl_d <= 0: return -1.0
    end = min(ep+1+max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry+sl_d*TP_R if d==1 else entry-sl_d*TP_R
    if d==1:
        sl_i = int(np.argmax(lo<=sl)) if np.any(lo<=sl) else max_bars
        tp_i = int(np.argmax(hi>=tp)) if np.any(hi>=tp) else max_bars
    else:
        sl_i = int(np.argmax(hi>=sl)) if np.any(hi>=sl) else max_bars
        tp_i = int(np.argmax(lo<=tp)) if np.any(lo<=tp) else max_bars
    if tp_i <= sl_i: return TP_R
    if sl_i < max_bars: return -1.0
    return ((m1['close'].values[end-1]-entry) if d==1 else (entry-m1['close'].values[end-1]))/sl_d

def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body, full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body, full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def collect_oos(key):
    m1 = _m1[key]; mi = m1.index
    skip = H1_SKIP.get(key, frozenset({4}))
    p_hours = H1_HOURS.get(key, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); out = []; day_count = {}
    for i in range(len(hl) if key=='USDJPY' else 1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k,0) >= MAX_PD: continue

        bar = h1.iloc[i]
        if key == 'USDJPY':
            # Pin Bar only
            pb_dir = pin_bar_dir(float(bar['open']),float(bar['high']),
                                  float(bar['low']),float(bar['close']))
            if pb_dir == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            for j in range(len(window)):
                b = window.iloc[j]
                if pb_dir==1 and b['high']>pb_h:   d=1;  ep2=pb_h; sl=pb_l
                elif pb_dir==-1 and b['low']<pb_l: d=-1; ep2=pb_l; sl=pb_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r_gross = vsim(key, ep, d, ep2, sl)
                out.append({'date': date_k, 'r_net': r_gross - COST[key] - SLIPPAGE})
                break
        else:
            # Inside Bar
            prev = h1.iloc[i-1]
            if not (bar['high'] < prev['high'] and bar['low'] > prev['low']): continue
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            if (ib_h-ib_l) <= 0 or (ib_h-ib_l)/ib_h < 0.00015: continue
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            for j in range(len(window)):
                b = window.iloc[j]
                if b['high']>ib_h:   d=1;  ep2=ib_h; sl=ib_l
                elif b['low']<ib_l:  d=-1; ep2=ib_l; sl=ib_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r_gross = vsim(key, ep, d, ep2, sl)
                out.append({'date': date_k, 'r_net': r_gross - COST[key] - SLIPPAGE})
                break
    return out

# ── LOAD & COLLECT ────────────────────────────────────────────────────────────
print('Loading data...')
loaded = []
for k in FILES:
    if load(k):
        loaded.append(k)
        print(f'  {k}: {len(_m1[k]):,} bars')
    else:
        print(f'  {k}: not found')

print('\nCollecting OOS signals (2022-2025)...')
all_trades = []
for k in loaded:
    t = collect_oos(k)
    all_trades.extend(t)
    print(f'  {k}: {len(t)} trades')

# ── BUILD DAILY P&L SERIES ────────────────────────────────────────────────────
# Group by date, sum R across all instruments
from collections import defaultdict
daily_r = defaultdict(float)
for t in all_trades:
    daily_r[t['date']] += t['r_net']

# Build full OOS calendar (all trading days Mon-Fri)
all_dates = pd.date_range(OOS_START, OOS_END - pd.Timedelta(days=1), freq='B')
daily_series = np.array([daily_r.get(d.date(), 0.0) for d in all_dates])

n_days   = len(daily_series)
n_active = np.sum(daily_series != 0)
avg_r    = daily_series.mean()
print(f'\nOOS daily P&L series: {n_days} calendar trading days')
print(f'  Days with signals:  {n_active} ({n_active/n_days*100:.0f}%)')
print(f'  Avg daily R:        {avg_r:+.3f}R')
print(f'  Avg daily GBP:      GBP {avg_r * ACCOUNT * RISK_FRAC:,.0f}')
print(f'  Best day:           {daily_series.max():+.2f}R')
print(f'  Worst day:          {daily_series.min():+.2f}R')

# ── BOOTSTRAP MC ──────────────────────────────────────────────────────────────
print(f'\nRunning {N_SIMS:,} bootstrap simulations...')
RNG = np.random.default_rng(42)

def mc_bootstrap(start_bal):
    balance = start_bal
    days = 0
    while True:
        # Sample a real OOS day (could be 0-signal day)
        day_r = daily_series[RNG.integers(0, n_days)]
        day_pnl = day_r * balance * RISK_FRAC
        days += 1

        # Apply daily loss cap first
        if day_pnl <= -FTMO_DAILY:
            return 'blown', days

        balance += day_pnl

        if balance <= FTMO_FLOOR:
            return 'blown', days
        if balance >= FTMO_TARGET:
            return 'pass', days
        if days > 730:
            return 'timeout', days

results  = [mc_bootstrap(ACCOUNT) for _ in range(N_SIMS)]
outcomes = np.array([r[0] for r in results])
days_arr = np.array([r[1] for r in results], float)

passes   = np.sum(outcomes == 'pass')
blows    = np.sum(outcomes == 'blown')
timeouts = np.sum(outcomes == 'timeout')
pct_pass = passes / N_SIMS * 100
pct_blow = blows  / N_SIMS * 100

pass_days = days_arr[outcomes == 'pass']

print()
print('=' * 65)
print('  REALISTIC MC — FTMO GBP70k  (bootstrap from actual OOS days)')
print('=' * 65)
print(f'  Pass:     {pct_pass:.1f}%')
print(f'  Blow:     {pct_blow:.1f}%')
if timeouts > 0:
    print(f'  Timeout:  {timeouts/N_SIMS*100:.1f}%')
print()
print(f'  Calendar trading days to pass (when passing):')
print(f'    Best case  (p10):  {np.percentile(pass_days,10):.0f} days  (~{np.percentile(pass_days,10)/5:.0f} weeks)')
print(f'    Median     (p50):  {np.median(pass_days):.0f} days  (~{np.median(pass_days)/5:.0f} weeks)')
print(f'    Mean:              {np.mean(pass_days):.0f} days  (~{np.mean(pass_days)/5:.0f} weeks)')
print(f'    Slow run   (p90):  {np.percentile(pass_days,90):.0f} days  (~{np.percentile(pass_days,90)/5:.0f} weeks)')
print(f'    Worst case (p99):  {np.percentile(pass_days,99):.0f} days  (~{np.percentile(pass_days,99)/5:.0f} weeks)')

print()
print(f'  Note: "days" = calendar trading days (Mon-Fri)')
print(f'        {n_days - n_active} of {n_days} OOS days had zero signals ({(n_days-n_active)/n_days*100:.0f}%)')
print()
print(f'  VERDICT')
print(f'  {"-"*55}')
if pct_pass >= 85:
    print(f'  {pct_pass:.0f}% pass rate — extremely strong. System will pass.')
elif pct_pass >= 70:
    print(f'  {pct_pass:.0f}% pass rate — solid. Expected to pass.')
elif pct_pass >= 55:
    print(f'  {pct_pass:.0f}% pass rate — marginal. Manage risk carefully.')
else:
    print(f'  {pct_pass:.0f}% pass rate — review system before continuing.')
print('=' * 65)
print('Done.')
