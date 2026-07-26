"""
backtest_is_oos.py

Compares In-Sample (2018-2021) vs Out-of-Sample (2022-2025) performance.
Uses STRATEGY_BOTH (IB + Pin Bar) to match the live EA.

Answers ChatGPT's question: "Does the edge look equally good in quieter regimes?"
If IS and OOS show similar WR, avg R and trade frequency, the edge is structural.

Run: python -u backtest_is_oos.py
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

IS_START  = pd.Timestamp(2018, 1, 1, tz='UTC')
IS_END    = pd.Timestamp(2022, 1, 1, tz='UTC')
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

def vsim(k, ep, d, entry, sl, max_bars=MAX_BARS):
    m1 = _m1[k]; sl_d = abs(entry-sl)
    if sl_d <= 0: return -1.0, max_bars
    end = min(ep+1+max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0, max_bars
    tp = entry+sl_d*BASE_TP if d==1 else entry-sl_d*BASE_TP
    if d==1:
        sl_i = int(np.argmax(lo<=sl)) if np.any(lo<=sl) else len(hi)
        tp_i = int(np.argmax(hi>=tp)) if np.any(hi>=tp) else len(hi)
    else:
        sl_i = int(np.argmax(hi>=sl)) if np.any(hi>=sl) else len(hi)
        tp_i = int(np.argmax(lo<=tp)) if np.any(lo<=tp) else len(hi)
    if tp_i <= sl_i: return BASE_TP, tp_i
    if sl_i < len(hi): return -1.0, sl_i
    close_r = ((m1['close'].values[min(ep+len(hi),len(m1)-1)]-entry)/sl_d if d==1
               else (entry-m1['close'].values[min(ep+len(hi),len(m1)-1)])/sl_d)
    return close_r, len(hi)

def collect(k, start, end):
    m1 = _m1[k]; mi = m1.index
    skip = H1_SKIP.get(k, frozenset())
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= start) & (m1.index < end)]
    if len(m1w) < 100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); out = []; day_count = {}

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
        r_gross, hold_bars = vsim(k, ep, d, e, sl)
        day_count[date_k] = day_count.get(date_k,0)+1
        out.append({'r_net': r_gross - COST[k] - SLIPPAGE, 'hold_bars': hold_bars})
    return out

def report(label, trades, months):
    if not trades: return
    r = np.array([t['r_net'] for t in trades])
    h = np.array([t['hold_bars'] for t in trades])
    w = r[r>0]; l = r[r<=0]
    pf = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    wr = round(len(w)/len(r)*100,1)
    avg_r = round(r.mean(),3)
    avg_hold = round(h.mean(),0)
    trades_pm = round(len(r)/months,1)
    print(f'  {label:<22}  {len(r):>6}  {trades_pm:>8.1f}  {pf:>6.2f}  {wr:>7.1f}%  {avg_r:>7.3f}  {avg_hold:>9.0f}')

print('Loading data...')
loaded = [k for k in FILES if load(k)]

IS_MONTHS  = (IS_END  - IS_START).days  / 30.44
OOS_MONTHS = (OOS_END - OOS_START).days / 30.44

print('\n' + '='*80)
print('  IN-SAMPLE vs OUT-OF-SAMPLE COMPARISON  |  STRATEGY_BOTH')
print('='*80)
print(f'\n  {"Period":>22}  {"Trades":>6}  {"Trades/mo":>9}  {"PF":>6}  {"WR":>8}  {"AvgR":>7}  {"Hold(bars)":>10}')
print(f'  {"-"*72}')

all_is=[]; all_oos=[]
for k in loaded:
    t_is  = collect(k, IS_START,  IS_END)
    t_oos = collect(k, OOS_START, OOS_END)
    all_is.extend(t_is); all_oos.extend(t_oos)

report('IS  2018-2021', all_is,  IS_MONTHS)
report('OOS 2022-2025', all_oos, OOS_MONTHS)

print(f'  {"-"*72}')

# Per-instrument breakdown
print(f'\n  Per-instrument breakdown:\n')
print(f'  {"Instrument":>12}  {"IS PF":>7}  {"IS N":>6}  {"OOS PF":>8}  {"OOS N":>7}  {"WFE":>6}')
print(f'  {"-"*55}')
for k in loaded:
    t_is  = collect(k, IS_START,  IS_END)
    t_oos = collect(k, OOS_START, OOS_END)
    def pf(t):
        if not t: return 0.0
        r=np.array([x['r_net'] for x in t]); w=r[r>0]; l=r[r<=0]
        return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    is_pf=pf(t_is); oos_pf=pf(t_oos)
    wfe = round(oos_pf/is_pf,2) if is_pf>0 else 0.0
    flag = '' if wfe >= 0.7 else '  ! low WFE'
    print(f'  {k:>12}  {is_pf:>7.2f}  {len(t_is):>6}  {oos_pf:>8.2f}  {len(t_oos):>7}  {wfe:>6.2f}{flag}')

print('\n' + '='*80)
print('  VERDICT')
print('='*80)
r_is  = np.array([t['r_net'] for t in all_is])
r_oos = np.array([t['r_net'] for t in all_oos])
pf_is  = round(r_is[r_is>0].sum()/abs(r_is[r_is<=0].sum()),2)
pf_oos = round(r_oos[r_oos>0].sum()/abs(r_oos[r_oos<=0].sum()),2)
wfe_overall = round(pf_oos/pf_is,2)

print(f'\n  Overall WFE (OOS PF / IS PF): {pf_oos:.2f} / {pf_is:.2f} = {wfe_overall:.2f}')
if wfe_overall >= 0.80:
    print(f'  STRONG — OOS retained >{wfe_overall*100:.0f}% of IS edge. No significant regime sensitivity.')
elif wfe_overall >= 0.65:
    print(f'  ACCEPTABLE — some IS->OOS degradation but edge persists.')
else:
    print(f'  WEAK — significant IS->OOS degradation. Review overfitting risk.')
print('='*80)
print('Done.')
