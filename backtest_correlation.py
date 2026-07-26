"""
backtest_correlation.py

Computes daily P&L correlation between all 9 instruments OOS 2022-2025.
Uses STRATEGY_BOTH to match the live EA.

Answers ChatGPT's question: "Is the 9-instrument diversification real?"
High correlation between indices (DAX/NAS100/SP500/US30) = clustered losses.
Low or negative correlation across asset classes = genuine diversification.

Run: python -u backtest_correlation.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

BASE_TP   = 4.0
SLIPPAGE  = 0.10
WIN_HOURS = 3
MAX_BARS  = 480
MAX_PD    = 3
WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',   'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',   'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',  'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',  'GOLD':  'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
}
COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,'GOLD':0.08,'NATGAS':0.15,
}
H1_HOURS = {
    'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},'NATGAS':{13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'USDJPY':frozenset(),'GOLD':frozenset(),'NATGAS':frozenset(),
    'NAS100':frozenset({0}),'SP500':frozenset({0}),'US30':frozenset({0}),
}

_m1 = {}
def load(k):
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna(); return True

def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0 or body < full*0.02: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body,full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body,full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def vsim(k, ep, d, entry, sl):
    m1 = _m1[k]; sl_d = abs(entry-sl)
    if sl_d <= 0: return -1.0
    end = min(ep+1+MAX_BARS, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry+sl_d*BASE_TP if d==1 else entry-sl_d*BASE_TP
    if d==1:
        sl_i = int(np.argmax(lo<=sl)) if np.any(lo<=sl) else MAX_BARS
        tp_i = int(np.argmax(hi>=tp)) if np.any(hi>=tp) else MAX_BARS
    else:
        sl_i = int(np.argmax(hi>=sl)) if np.any(hi>=sl) else MAX_BARS
        tp_i = int(np.argmax(lo<=tp)) if np.any(lo<=tp) else MAX_BARS
    if tp_i <= sl_i: return BASE_TP
    if sl_i < MAX_BARS: return -1.0
    return ((m1['close'].values[end-1]-entry)/sl_d if d==1
            else (entry-m1['close'].values[end-1])/sl_d)

def collect_daily(k):
    m1 = _m1[k]; mi = m1.index
    skip = H1_SKIP.get(k, frozenset())
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: return {}
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); daily = {}; day_count = {}

    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip or ts.dayofweek >= 5: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue
        bar = h1.iloc[i]
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0: continue

        taken = False; d = 0; e = 0.0; sl = 0.0

        if k == 'USDJPY':
            pb = pin_bar_dir(float(bar['open']),float(bar['high']),float(bar['low']),float(bar['close']))
            if pb == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            for j in range(len(window)):
                b = window.iloc[j]
                if pb==1 and b['high']>pb_h:   d=1;  e=pb_h; sl=pb_l; taken=True; break
                elif pb==-1 and b['low']<pb_l: d=-1; e=pb_l; sl=pb_h; taken=True; break
        else:
            prev = h1.iloc[i-1]
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            is_ib = bar['high'] < prev['high'] and bar['low'] > prev['low']
            ib_ok = is_ib and (ib_h-ib_l) > 0 and (ib_h-ib_l)/ib_h >= MIN_RANGE
            if ib_ok:
                for j in range(len(window)):
                    b = window.iloc[j]
                    if b['high']>ib_h:  d=1;  e=ib_h; sl=ib_l; taken=True; break
                    elif b['low']<ib_l: d=-1; e=ib_l; sl=ib_h; taken=True; break
            if not taken:
                pb = pin_bar_dir(float(bar['open']),ib_h,ib_l,float(bar['close']))
                if pb != 0:
                    for j in range(len(window)):
                        b = window.iloc[j]
                        if pb==1 and b['high']>ib_h:   d=1;  e=ib_h; sl=ib_l; taken=True; break
                        elif pb==-1 and b['low']<ib_l: d=-1; e=ib_l; sl=ib_h; taken=True; break

        if not taken: continue
        sl_dist = abs(e-sl)
        if sl_dist <= 0: continue
        ep = mi.searchsorted(window.index[j])
        if ep >= len(m1): continue
        r_gross = vsim(k, ep, d, e, sl)
        r_net = r_gross - COST[k] - SLIPPAGE
        day_count[date_k] = day_count.get(date_k,0)+1
        daily[date_k] = daily.get(date_k, 0.0) + r_net
    return daily

print('Loading data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded: {loaded}')

print('\nCollecting daily P&L per instrument (~3-5 min)...')
daily_data = {}
for k in loaded:
    print(f'  {k}...', flush=True)
    daily_data[k] = collect_daily(k)

all_dates = sorted(set(d for v in daily_data.values() for d in v.keys()))
df = pd.DataFrame(index=all_dates)
for k in loaded:
    df[k] = pd.Series(daily_data[k])
df = df.fillna(0.0)
df = df[df.astype(bool).sum(axis=1) >= 2]

corr = df.corr()

print('\n' + '='*80)
print('  DAILY P&L CORRELATION MATRIX  |  STRATEGY_BOTH  |  OOS 2022-2025')
print('='*80)
print(f'  Days with >=2 instruments active: {len(df)}\n')
print(f'  Key: * = high (>0.5)  ~ = moderate (0.3-0.5)  - = negative (<-0.1)\n')

names = loaded
hdr = f'  {"":>7}' + ''.join(f'  {n:>7}' for n in names)
print(hdr)
sep = '  ' + '-'*6 + ('  -------'*len(names))
print(sep)
for ri in names:
    row = f'  {ri:>7}'
    for ci in names:
        v = corr.loc[ri,ci] if ri in corr.index and ci in corr.columns else 0.0
        if ri == ci:
            row += f'     1.00'
        else:
            tag = '*' if v>0.5 else ('~' if v>0.3 else ('-' if v<-0.1 else ' '))
            row += f'  {v:>+6.2f}{tag}'
    print(row)

indices     = [k for k in ['DAX','NAS100','SP500','US30'] if k in loaded]
fx          = [k for k in ['EURUSD','GBPUSD','USDJPY'] if k in loaded]
commodities = [k for k in ['GOLD','NATGAS'] if k in loaded]

def avg_corr(ga, gb, same=False):
    vals = []
    for a in ga:
        for b in gb:
            if a == b: continue
            if same and a >= b: continue
            if a in corr.index and b in corr.columns:
                vals.append(corr.loc[a,b])
    return round(np.mean(vals),3) if vals else 0.0

within_idx = avg_corr(indices, indices, same=True)

print('\n' + '='*80)
print('  CLUSTER SUMMARY')
print('='*80)
print(f'\n  Within-group:')
print(f'    Equity indices (DAX/NAS/SP5/US30):  avg corr = {within_idx:+.3f}')
print(f'    FX  (EUR/GBP/JPY):                  avg corr = {avg_corr(fx, fx, same=True):+.3f}')
print(f'\n  Cross-group:')
print(f'    Indices vs FX:     {avg_corr(indices, fx):+.3f}')
g = [k for k in commodities if k=="GOLD"]
n = [k for k in commodities if k=="NATGAS"]
if g: print(f'    Indices vs GOLD:   {avg_corr(indices, g):+.3f}')
if n: print(f'    Indices vs NATGAS: {avg_corr(indices, n):+.3f}')
if g: print(f'    FX vs GOLD:        {avg_corr(fx, g):+.3f}')
if n: print(f'    FX vs NATGAS:      {avg_corr(fx, n):+.3f}')

print(f'\n  10 worst portfolio days:')
df['portfolio'] = df[loaded].sum(axis=1)
worst = df.nsmallest(10, 'portfolio')
print(f'  {"Date":>12}  {"TotalR":>7}  {"Losers":>7}  Instruments losing')
print(f'  {"-"*55}')
for dt, row in worst.iterrows():
    n_losers = int((row[loaded] < -0.3).sum())
    total = round(row['portfolio'], 2)
    losers = ' '.join(k for k in loaded if row[k] < -0.3)
    print(f'  {str(dt):>12}  {total:>7.2f}  {n_losers:>7}  {losers}')

print('\n' + '='*80)
print('  VERDICT')
print('='*80)
if within_idx > 0.5:
    print(f'\n  US indices strongly correlated ({within_idx:+.2f}).')
    print(f'  NAS100+SP500+US30 effectively move as one on bad days.')
    print(f'  True effective instruments ~6 (not 9). Portfolio cap accounts for this.')
elif within_idx > 0.3:
    print(f'\n  US indices moderately correlated ({within_idx:+.2f}).')
    print(f'  Some clustering on major risk-off days. FX + GOLD + NATGAS offset this.')
else:
    print(f'\n  Low correlation across all instruments ({within_idx:+.2f}).')
    print(f'  Genuine diversification — losses do not cluster.')
print('='*80)
print('Done.')
