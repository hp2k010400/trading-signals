"""
backtest_rolling_pf.py
Rolling 200-trade profit factor across OOS 2022-2025.

Shows whether the edge is stable, improving, or decaying over time.
A PF that holds consistently above 2.0 on a rolling basis is strong
evidence the edge is structural and not a one-time artefact.

Run: python backtest_rolling_pf.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

BASE_TP   = 4.0
SLIPPAGE  = 0.10
WIN_HOURS = 3
WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015

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
    return ((m1['close'].values[end-1]-entry) if d==1 else (entry-m1['close'].values[end-1]))/sl_d

def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body, full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body, full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def collect_all():
    trades = []
    for key in loaded:
        m1 = _m1[key]; mi = m1.index
        skip = H1_SKIP.get(key, frozenset())
        p_hours = H1_HOURS.get(key, {8,9,13,14})
        m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
        if len(m1w) < 100: continue
        h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
        h1 = h1[h1['open'] > 0]
        hl = list(h1.index); day_count = {}
        for i in range(1, len(hl)):
            ts = hl[i]
            if ts.dayofweek in skip or ts.dayofweek >= 5: continue
            if ts.hour not in p_hours: continue
            date_k = ts.date()
            if day_count.get(date_k, 0) >= 3: continue
            bar = h1.iloc[i]
            if key == 'USDJPY':
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
                    r = vsim(key, ep, d, e, sl)
                    trades.append({'date': date_k, 'r_net': r - COST[key] - SLIPPAGE})
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
                    r = vsim(key, ep, d, e, sl)
                    trades.append({'date': date_k, 'r_net': r - COST[key] - SLIPPAGE})
                    break
    trades.sort(key=lambda x: x['date'])
    return trades

print('Loading data...')
loaded = [k for k in FILES if load(k)]

print('Collecting all OOS trades in chronological order...')
all_trades = collect_all()
r_all = np.asarray([t['r_net'] for t in all_trades], float)
print(f'  {len(r_all)} trades collected\n')

WINDOW = 200
print('=' * 65)
print(f'  ROLLING {WINDOW}-TRADE PROFIT FACTOR  |  OOS 2022-2025')
print('=' * 65)
print(f'  Shows whether the edge is stable, growing, or decaying.\n')
print(f'  {"Window":>18}  {"Trades":>8}  {"PF":>8}  {"WR":>7}  {"Status":>12}')
print(f'  {"-"*58}')

min_pf = 999; max_pf = 0; below_2 = 0; total_windows = 0
step = 50  # print every 50 trades

for start in range(0, len(r_all) - WINDOW + 1, step):
    window_r = r_all[start:start + WINDOW]
    w = window_r[window_r > 0]; l = window_r[window_r <= 0]
    if len(l) == 0 or l.sum() == 0: continue
    w_pf = round(w.sum() / abs(l.sum()), 2)
    w_wr = round(len(w) / len(window_r) * 100, 1)
    total_windows += 1
    if w_pf < min_pf: min_pf = w_pf
    if w_pf > max_pf: max_pf = w_pf
    if w_pf < 2.0: below_2 += 1
    trade_range = f'#{start+1}–#{start+WINDOW}'
    d_start = str(all_trades[start]['date'])
    d_end   = str(all_trades[min(start+WINDOW-1, len(all_trades)-1)]['date'])
    date_range = f'{d_start[:7]} → {d_end[:7]}'
    status = 'STRONG' if w_pf >= 2.5 else ('OK' if w_pf >= 2.0 else 'WEAK')
    print(f'  {date_range:>18}  {len(window_r):>8}  {w_pf:>8.2f}  {w_wr:>6.1f}%  {status:>12}')

print(f'  {"-"*58}')
print(f'\n  Rolling PF summary across {total_windows} windows:')
print(f'    Minimum rolling PF:   {min_pf:.2f}')
print(f'    Maximum rolling PF:   {max_pf:.2f}')
print(f'    Windows below 2.0:    {below_2}/{total_windows}')
print(f'    Windows above 2.5:    {total_windows-below_2}/{total_windows}')

# Also show quarterly breakdown
print(f'\n  Quarterly breakdown:')
print(f'  {"Quarter":>10}  {"Trades":>7}  {"PF":>8}  {"WR":>7}')
print(f'  {"-"*38}')
quarters = pd.period_range('2022Q1', '2025Q4', freq='Q')
for q in quarters:
    q_start = q.start_time.tz_localize('UTC').date()
    q_end   = q.end_time.tz_localize('UTC').date()
    q_trades = [t for t in all_trades if q_start <= t['date'] <= q_end]
    if len(q_trades) < 20: continue
    r = np.asarray([t['r_net'] for t in q_trades], float)
    w = r[r>0]; l = r[r<=0]
    q_pf = round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
    q_wr = round(len(w)/len(r)*100,1)
    flag = '  LOW' if q_pf < 2.0 else ''
    print(f'  {str(q):>10}  {len(r):>7}  {q_pf:>8.2f}  {q_wr:>6.1f}%{flag}')

print()
print('=' * 65)
print('  VERDICT')
print('=' * 65)
if min_pf >= 2.0:
    print(f'  Min rolling PF {min_pf:.2f} — edge held above 2.0 in ALL windows.')
    print(f'  No evidence of decay. System is structurally consistent.')
elif min_pf >= 1.5:
    print(f'  Min rolling PF {min_pf:.2f} — edge dipped but stayed profitable.')
    print(f'  {below_2} of {total_windows} windows below 2.0. Monitor live rolling PF.')
else:
    print(f'  Min rolling PF {min_pf:.2f} — edge disappeared in some periods.')
    print(f'  Investigate which dates/instruments drove the weak windows.')
print('=' * 65)
print('Done.')
