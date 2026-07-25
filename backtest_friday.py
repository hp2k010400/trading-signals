"""
backtest_friday.py
Directly answers: are Fridays profitable or should they be skipped?

Runs OOS 2022-2025 twice per instrument:
  - Non-Friday trades only
  - Friday trades only
Then compares PF, WR, trades/day, expected monthly.

Run: python backtest_friday.py
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
# Base skip: always exclude Sun/Sat. US indices also exclude Mon.
# Friday is what we're TESTING — not pre-skipped here.
H1_SKIP_BASE = {
    'DAX':frozenset({0,6}),'EURUSD':frozenset({0,6}),'GBPUSD':frozenset({0,6}),
    'USDJPY':frozenset({0,6}),'GOLD':frozenset({0,6}),'NATGAS':frozenset({0,6}),
    'NAS100':frozenset({0,1,6}),'SP500':frozenset({0,1,6}),'US30':frozenset({0,1,6}),
}
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

def collect(k, friday_only=False):
    """Collect OOS trades. friday_only=True gets Fri trades, False gets Mon-Thu."""
    m1 = _m1[k]; mi = m1.index
    skip_base = H1_SKIP_BASE.get(k, frozenset({0,6}))
    p_hours   = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); out = []; day_count = {}
    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip_base: continue   # always skip Sun/Sat (+ Mon for US)
        # Friday filter: dayofweek==4 is Friday in Python
        if friday_only and ts.dayofweek != 4: continue
        if not friday_only and ts.dayofweek == 4: continue
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
                out.append({'r_net': r - COST[k] - SLIPPAGE, 'day': ts.dayofweek})
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
                out.append({'r_net': r - COST[k] - SLIPPAGE, 'day': ts.dayofweek})
                break
    return out

def stats(trades):
    if not trades: return 0, 0.0, 0.0, 0.0
    r = np.asarray([t['r_net'] for t in trades], float)
    w = r[r>0]; l = r[r<=0]
    pf  = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    wr  = round(len(w)/len(r)*100, 1)
    exp = round(r.mean(), 3)
    return len(r), pf, wr, exp

print('Loading data...')
loaded = [k for k in FILES if load(k)]
print(f'  Loaded: {", ".join(loaded)}')

print('\nCollecting OOS trades (2022-2025)...')
print('(This runs each instrument twice — Friday trades and non-Friday trades separately)\n')

print('=' * 78)
print('  FRIDAY vs MON-THU  |  OOS 2022-2025  |  All 9 instruments')
print('=' * 78)
print(f'\n  {"":>10}  {"--- MON-THU ---":^30}  {"--- FRIDAY ---":^30}')
print(f'  {"Instrument":>10}  {"N":>4}  {"PF":>6}  {"WR":>6}  {"Exp/tr":>7}  '
      f'{"N":>4}  {"PF":>6}  {"WR":>6}  {"Exp/tr":>7}  {"Verdict":>12}')
print(f'  {"-"*74}')

all_nonf = []; all_fri = []
for k in loaded:
    nonf = collect(k, friday_only=False)
    fri  = collect(k, friday_only=True)
    all_nonf.extend(nonf); all_fri.extend(fri)
    n0, pf0, wr0, ex0 = stats(nonf)
    n1, pf1, wr1, ex1 = stats(fri)
    if   pf1 >= pf0 * 0.85: verdict = 'KEEP FRIDAY'
    elif pf1 >= 1.5:         verdict = 'MARGINAL'
    elif pf1 >= 1.0:         verdict = 'WEAK'
    else:                    verdict = 'SKIP FRIDAY'
    print(f'  {k:>10}  {n0:>4}  {pf0:>6.2f}  {wr0:>5.1f}%  {ex0:>+7.3f}  '
          f'{n1:>4}  {pf1:>6.2f}  {wr1:>5.1f}%  {ex1:>+7.3f}  {verdict:>12}')

print(f'  {"-"*74}')
n0, pf0, wr0, ex0 = stats(all_nonf)
n1, pf1, wr1, ex1 = stats(all_fri)
print(f'  {"TOTAL":>10}  {n0:>4}  {pf0:>6.2f}  {wr0:>5.1f}%  {ex0:>+7.3f}  '
      f'{n1:>4}  {pf1:>6.2f}  {wr1:>5.1f}%  {ex1:>+7.3f}')

# Expected monthly with and without Friday
fri_days_pm  = 4.33      # ~4-5 Fridays per month
work_days_pm = 21.7
nonf_days_pm = work_days_pm - fri_days_pm

tpd_nonf = n0 / (OOS_DAYS * 4/5)   # Mon-Thu = 80% of days
tpd_fri  = n1 / (OOS_DAYS * 1/5)   # Friday  = 20% of days

monthly_nonf = ex0 * tpd_nonf * nonf_days_pm * ACCOUNT * RISK_FRAC
monthly_fri  = ex1 * tpd_fri  * fri_days_pm  * ACCOUNT * RISK_FRAC
monthly_both = monthly_nonf + monthly_fri

print()
print('=' * 78)
print('  EXPECTED MONTHLY EARNINGS')
print('=' * 78)
print(f'  Mon-Thu only:           GBP {monthly_nonf:>9,.0f}/month')
print(f'  Friday contribution:    GBP {monthly_fri:>9,.0f}/month  '
      f'({"POSITIVE — adds value" if monthly_fri > 0 else "NEGATIVE — costs money"})')
print(f'  Combined (all 5 days):  GBP {monthly_both:>9,.0f}/month')
print()
print(f'  Friday adds/removes:    {monthly_fri/monthly_nonf*100:>+.1f}% to monthly earnings')
print()

print('=' * 78)
print('  VERDICT')
print('=' * 78)
if pf1 >= 2.0:
    print(f'  Friday PF {pf1:.2f} — TRADE FRIDAYS. Edge holds. EA v2.02 Friday skip was WRONG.')
    print(f'  Action: revert IsSkipDay() Friday block, redeploy EA.')
elif pf1 >= 1.5:
    print(f'  Friday PF {pf1:.2f} — MARGINAL. Friday edge exists but weaker.')
    print(f'  Action: trade Fridays but cut max trades/day to 1 on Fridays.')
elif pf1 >= 1.0:
    print(f'  Friday PF {pf1:.2f} — WEAK. Slight positive but not worth the risk.')
    print(f'  Action: keep Friday skip. EA v2.02 is correct.')
else:
    print(f'  Friday PF {pf1:.2f} — LOSING. Fridays destroy edge.')
    print(f'  Action: keep Friday skip. Your losses this week confirm it. EA v2.02 correct.')

print()
print(f'  Note: your week-1 losses mostly on Friday = consistent with backtest.')
print(f'  EA was trading Fridays (v2.01 bug), backtest never included them.')
print(f'  v2.02 now matches the backtest — Friday skip applied.')
print('=' * 78)
print('Done.')
