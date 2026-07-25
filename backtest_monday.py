"""
backtest_monday.py
Monday vs Tue-Fri performance comparison OOS 2022-2025.
Should we skip Mondays like the US indices already do?

Run: python backtest_monday.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

ACCOUNT   = 70_000
RISK_FRAC = 0.005
BASE_TP   = 4.0
MAX_PD    = 3
WIN_HOURS = 3
SLIPPAGE  = 0.10

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')
OOS_DAYS  = (OOS_END - OOS_START).days / 7 * 5

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
# No day skips here — Monday is what we're testing
WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015

_m1 = {}

def load(k):
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
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep+1+max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry+sl_d*BASE_TP if d==1 else entry-sl_d*BASE_TP
    if d==1:
        sl_i = int(np.argmax(lo<=sl)) if np.any(lo<=sl) else max_bars
        tp_i = int(np.argmax(hi>=tp)) if np.any(hi>=tp) else max_bars
    else:
        sl_i = int(np.argmax(hi>=sl)) if np.any(hi>=sl) else max_bars
        tp_i = int(np.argmax(lo<=tp)) if np.any(lo<=tp) else max_bars
    if tp_i <= sl_i: return BASE_TP
    if sl_i < max_bars: return -1.0
    lp = m1['close'].values[end-1]
    return ((lp-entry) if d==1 else (entry-lp)) / sl_d

def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body, full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body, full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def collect(k, monday_only=False):
    m1 = _m1[k]; mi = m1.index
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); out = []; day_count = {}
    for i in range(1, len(hl)):
        ts = hl[i]
        dow = ts.dayofweek
        if dow >= 5: continue   # skip Sat/Sun always
        if monday_only and dow != 0: continue
        if not monday_only and dow == 0: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue
        bar = h1.iloc[i]
        if k == 'USDJPY':
            pb = pin_bar_dir(float(bar['open']),float(bar['high']),
                              float(bar['low']),float(bar['close']))
            if pb == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            for j in range(len(window)):
                b = window.iloc[j]
                if pb==1 and b['high']>pb_h:    d=1;  e=pb_h; sl=pb_l
                elif pb==-1 and b['low']<pb_l:  d=-1; e=pb_l; sl=pb_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE})
                break
        else:
            prev = h1.iloc[i-1]
            if not (bar['high']<prev['high'] and bar['low']>prev['low']): continue
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            if (ib_h-ib_l) <= 0 or (ib_h-ib_l)/ib_h < MIN_RANGE: continue
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            for j in range(len(window)):
                b = window.iloc[j]
                if b['high']>ib_h:    d=1;  e=ib_h; sl=ib_l
                elif b['low']<ib_l:   d=-1; e=ib_l; sl=ib_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE})
                break
    return out

def stats(trades):
    if not trades: return 0, 0.0, 0.0, 0.0
    r = np.asarray([t['r_net'] for t in trades], float)
    w = r[r>0]; l = r[r<=0]
    pf  = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    wr_ = round(len(w)/len(r)*100, 1)
    exp = round(r.mean(), 3)
    return len(r), pf, wr_, exp

print('Loading data...')
loaded = [k for k in FILES if load(k)]

print('\nCollecting OOS trades (2022-2025)...\n')

print('=' * 78)
print('  MONDAY vs TUE-FRI  |  OOS 2022-2025  |  All 9 instruments')
print('=' * 78)
print(f'\n  {"":>10}  {"--- TUE-FRI ---":^30}  {"--- MONDAY ---":^30}')
print(f'  {"Instrument":>10}  {"N":>4}  {"PF":>6}  {"WR":>6}  {"Exp/tr":>7}  '
      f'{"N":>4}  {"PF":>6}  {"WR":>6}  {"Exp/tr":>7}  {"Verdict":>12}')
print(f'  {"-"*74}')

all_tuefri = []; all_mon = []
for k in loaded:
    tuefri = collect(k, monday_only=False)
    mon    = collect(k, monday_only=True)
    all_tuefri.extend(tuefri); all_mon.extend(mon)
    n0, pf0, wr0, ex0 = stats(tuefri)
    n1, pf1, wr1, ex1 = stats(mon)
    if   pf1 >= pf0 * 0.85: verdict = 'KEEP MONDAY'
    elif pf1 >= 1.5:         verdict = 'MARGINAL'
    elif pf1 >= 1.0:         verdict = 'WEAK'
    else:                    verdict = 'SKIP MONDAY'
    print(f'  {k:>10}  {n0:>4}  {pf0:>6.2f}  {wr0:>5.1f}%  {ex0:>+7.3f}  '
          f'{n1:>4}  {pf1:>6.2f}  {wr1:>5.1f}%  {ex1:>+7.3f}  {verdict:>12}')

print(f'  {"-"*74}')
n0, pf0, wr0, ex0 = stats(all_tuefri)
n1, pf1, wr1, ex1 = stats(all_mon)
print(f'  {"TOTAL":>10}  {n0:>4}  {pf0:>6.2f}  {wr0:>5.1f}%  {ex0:>+7.3f}  '
      f'{n1:>4}  {pf1:>6.2f}  {wr1:>5.1f}%  {ex1:>+7.3f}')

mon_days_pm  = 4.33
work_days_pm = 21.7
tuefri_days_pm = work_days_pm - mon_days_pm

tpd_tuefri = n0 / (OOS_DAYS * 4/5)
tpd_mon    = n1 / (OOS_DAYS * 1/5)

monthly_tuefri = ex0 * tpd_tuefri * tuefri_days_pm * ACCOUNT * RISK_FRAC
monthly_mon    = ex1 * tpd_mon    * mon_days_pm    * ACCOUNT * RISK_FRAC
monthly_both   = monthly_tuefri + monthly_mon

print()
print('=' * 78)
print('  EXPECTED MONTHLY EARNINGS')
print('=' * 78)
print(f'  Tue-Fri only:           GBP {monthly_tuefri:>9,.0f}/month')
print(f'  Monday contribution:    GBP {monthly_mon:>9,.0f}/month  '
      f'({"POSITIVE — adds value" if monthly_mon > 0 else "NEGATIVE — costs money"})')
print(f'  Combined (all 5 days):  GBP {monthly_both:>9,.0f}/month')
print(f'\n  Monday adds/removes:    {monthly_mon/monthly_tuefri*100:>+.1f}% to monthly earnings')

print()
print('=' * 78)
print('  DAY-BY-DAY BREAKDOWN  (all instruments combined)')
print('=' * 78)
print(f'  {"Day":>10}  {"Trades":>7}  {"WR":>7}  {"PF":>8}  {"Exp/tr":>8}')
print(f'  {"-"*48}')
DAY_NAMES = {0:'Monday', 1:'Tuesday', 2:'Wednesday', 3:'Thursday', 4:'Friday'}

all_by_day = {d: [] for d in range(5)}
for k in loaded:
    m1 = _m1[k]; mi = m1.index
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: continue
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); day_count = {}
    for i in range(1, len(hl)):
        ts = hl[i]; dow = ts.dayofweek
        if dow >= 5: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue
        bar = h1.iloc[i]
        if k == 'USDJPY':
            pb = pin_bar_dir(float(bar['open']),float(bar['high']),
                              float(bar['low']),float(bar['close']))
            if pb == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            for j in range(len(window)):
                b = window.iloc[j]
                if pb==1 and b['high']>pb_h:    d=1;  e=pb_h; sl=pb_l
                elif pb==-1 and b['low']<pb_l:  d=-1; e=pb_l; sl=pb_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                all_by_day[dow].append(r - COST[k] - SLIPPAGE)
                break
        else:
            prev = h1.iloc[i-1]
            if not (bar['high']<prev['high'] and bar['low']>prev['low']): continue
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            if (ib_h-ib_l) <= 0 or (ib_h-ib_l)/ib_h < MIN_RANGE: continue
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            for j in range(len(window)):
                b = window.iloc[j]
                if b['high']>ib_h:    d=1;  e=ib_h; sl=ib_l
                elif b['low']<ib_l:   d=-1; e=ib_l; sl=ib_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                all_by_day[dow].append(r - COST[k] - SLIPPAGE)
                break

for d in range(5):
    r = np.asarray(all_by_day[d], float)
    if len(r) == 0: continue
    w = r[r>0]; l = r[r<=0]
    pf_d  = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    wr_d  = round(len(w)/len(r)*100, 1)
    exp_d = round(r.mean(), 3)
    flag = '  << WEAKEST' if pf_d == min(
        (np.asarray(all_by_day[x], float) for x in range(5) if all_by_day[x]),
        key=lambda x: (x[x>0].sum()/abs(x[x<=0].sum()) if len(x[x<=0]) else 0)
    ).mean() else ''
    print(f'  {DAY_NAMES[d]:>10}  {len(r):>7}  {wr_d:>6.1f}%  {pf_d:>8.2f}  {exp_d:>+8.3f}')

print()
print('=' * 78)
print('  VERDICT')
print('=' * 78)
if pf1 >= 2.0:
    print(f'  Monday PF {pf1:.2f} — TRADE MONDAYS. Edge holds Mon-Fri.')
    if monthly_mon > 0:
        print(f'  Cutting Monday would cost GBP {abs(monthly_mon):,.0f}/month.')
elif pf1 >= 1.5:
    print(f'  Monday PF {pf1:.2f} — MARGINAL. Slight edge, not worth cutting.')
elif pf1 >= 1.0:
    print(f'  Monday PF {pf1:.2f} — WEAK. Consider skipping Mondays.')
    print(f'  You would lose GBP {abs(monthly_mon):,.0f}/month but reduce variance.')
else:
    print(f'  Monday PF {pf1:.2f} — LOSING. Skip Mondays.')
    print(f'  Removing Mondays would SAVE GBP {abs(monthly_mon):,.0f}/month.')
print('=' * 78)
print('Done.')
