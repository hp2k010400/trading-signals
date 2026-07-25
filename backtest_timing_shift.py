"""
backtest_timing_shift.py
Tests whether the edge depends on razor-precise M1 entry timing.

Runs OOS 2022-2025 three times:
  - Baseline: enter on first M1 bar that breaks the level
  - +1 min:   skip the first breaking bar, enter on the next one
  - -1 min:   enter 1 bar before the level is officially broken
              (simulates slightly anticipating the breakout)

If PF holds across all three, the edge is structural.
If PF collapses at +1 or -1, the backtest relies on unrealistic
precision and the edge may not transfer to live execution.

Run: python backtest_timing_shift.py
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
H1_SKIP = {
    'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'USDJPY':frozenset(),'GOLD':frozenset(),'NATGAS':frozenset(),
    'NAS100':frozenset({0}),'SP500':frozenset({0}),'US30':frozenset({0}),
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
    return ((m1['close'].values[end-1]-entry) if d==1 else (entry-m1['close'].values[end-1]))/sl_d

def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body, full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body, full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def collect(k, bar_shift=0):
    """
    bar_shift = 0:  baseline — enter on first bar that breaks level
    bar_shift = 1:  +1 min — skip breaking bar, enter on next bar
    bar_shift = -1: -1 min — enter 1 bar BEFORE the break (prev close used as entry)
    """
    m1 = _m1[k]; mi = m1.index
    skip = H1_SKIP.get(key, frozenset()) if False else H1_SKIP.get(k, frozenset())
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
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

        if k == 'USDJPY':
            pb = pin_bar_dir(float(bar['open']),float(bar['high']),
                              float(bar['low']),float(bar['close']))
            if pb == 0: continue
            level_h = float(bar['high']); level_l = float(bar['low'])
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            if bar_shift == -1:
                # Enter 1 bar before level breaks — use open of first window bar
                b0 = window.iloc[0]
                if pb == 1:   d=1;  e=float(b0['open']); sl=level_l
                elif pb == -1: d=-1; e=float(b0['open']); sl=level_h
                else: continue
                ep = mi.searchsorted(window.index[0])
                if ep >= len(m1): continue
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE})
            else:
                break_idx = None
                for j in range(len(window)):
                    b = window.iloc[j]
                    if pb==1 and b['high']>level_h:   break_idx=j; break
                    elif pb==-1 and b['low']<level_l: break_idx=j; break
                if break_idx is None: continue
                actual_idx = break_idx + bar_shift
                if actual_idx < 0 or actual_idx >= len(window): continue
                b = window.iloc[actual_idx]
                if pb==1:   d=1;  e=level_h; sl=level_l
                elif pb==-1: d=-1; e=level_l; sl=level_h
                ep = mi.searchsorted(window.index[actual_idx])
                if ep >= len(m1): continue
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE})
        else:
            prev = h1.iloc[i-1]
            if not (bar['high']<prev['high'] and bar['low']>prev['low']): continue
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            if (ib_h-ib_l) <= 0 or (ib_h-ib_l)/ib_h < MIN_RANGE: continue
            entry_start = ts + pd.Timedelta(hours=1)
            window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
            if len(window) == 0: continue
            if bar_shift == -1:
                b0 = window.iloc[0]
                e = float(b0['open'])
                # Determine which side is more likely — use close of signal bar
                sig_close = float(bar['close'])
                d = 1 if sig_close > (ib_h+ib_l)/2 else -1
                sl = ib_l if d == 1 else ib_h
                ep = mi.searchsorted(window.index[0])
                if ep >= len(m1): continue
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE})
            else:
                break_idx = None; direction = None
                for j in range(len(window)):
                    b = window.iloc[j]
                    if b['high']>ib_h:   break_idx=j; direction=1;  break
                    elif b['low']<ib_l:  break_idx=j; direction=-1; break
                if break_idx is None: continue
                actual_idx = break_idx + bar_shift
                if actual_idx < 0 or actual_idx >= len(window): continue
                b = window.iloc[actual_idx]
                e = ib_h if direction==1 else ib_l
                sl = ib_l if direction==1 else ib_h
                ep = mi.searchsorted(window.index[actual_idx])
                if ep >= len(m1): continue
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, direction, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE})
    return out

def pf(trades):
    r = np.asarray([t['r_net'] for t in trades], float)
    w = r[r>0]; l = r[r<=0]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0

def wr(trades):
    r = np.asarray([t['r_net'] for t in trades], float)
    return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

print('Loading data...')
loaded = [k for k in FILES if load(k)]

print('\nRunning timing shift test OOS 2022-2025...')
print('(Tests whether edge survives entering 1 bar earlier or later)\n')

print('=' * 72)
print('  ENTRY TIMING SHIFT TEST  |  OOS 2022-2025')
print('=' * 72)
print(f'\n  {"":>12}  {"Baseline (0)":>14}  {"+1 min later":>14}  {"-1 min early":>14}')
print(f'  {"Instrument":>12}  {"N":>4} {"PF":>5}  {"N":>4} {"PF":>5}  {"N":>4} {"PF":>5}')
print(f'  {"-"*62}')

all_base=[]; all_plus=[]; all_minus=[]
for k in loaded:
    b  = collect(k,  0)
    p  = collect(k, +1)
    m  = collect(k, -1)
    all_base.extend(b); all_plus.extend(p); all_minus.extend(m)
    print(f'  {k:>12}  {len(b):>4} {pf(b):>5.2f}  {len(p):>4} {pf(p):>5.2f}  {len(m):>4} {pf(m):>5.2f}')

print(f'  {"-"*62}')
print(f'  {"TOTAL":>12}  {len(all_base):>4} {pf(all_base):>5.2f}  {len(all_plus):>4} {pf(all_plus):>5.2f}  {len(all_minus):>4} {pf(all_minus):>5.2f}')

pf0 = pf(all_base); pf_p = pf(all_plus); pf_m = pf(all_minus)
print()
print('=' * 72)
print('  VERDICT')
print('=' * 72)
print(f'  Baseline PF:       {pf0:.2f}')
print(f'  +1 min later PF:   {pf_p:.2f}  ({(pf_p-pf0)/pf0*100:+.1f}% vs baseline)')
print(f'  -1 min early PF:   {pf_m:.2f}  ({(pf_m-pf0)/pf0*100:+.1f}% vs baseline)')
print()
if min(pf_p, pf_m) >= pf0 * 0.75:
    print('  ROBUST — edge survives ±1 minute timing shift.')
    print('  Entry logic is not dependent on razor-precise execution.')
    print('  Live fills 1 bar late will not destroy the system.')
elif min(pf_p, pf_m) >= pf0 * 0.50:
    print('  MODERATE — some timing sensitivity. Edge weakens but survives.')
    print('  Prioritise fast execution on the VPS to minimise bar-late fills.')
else:
    print('  SENSITIVE — PF collapses with 1-bar shift.')
    print('  Edge may depend on precise timing. Investigate execution quality.')
print('=' * 72)
print('Done.')
