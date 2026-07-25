"""
backtest_pinbar.py

Tests pin bar signals on the 8 non-USDJPY instruments over OOS 2022-2025.

STRATEGY_BOTH (live EA) = inside bars, then pin bars on any non-IB session bar.
STRATEGY_IB   (backtest) = inside bars only.

Shows exactly what the pin bar component adds or costs vs the validated backtest.

Run: python -u backtest_pinbar.py
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
MAX_PD     = 3

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
}
COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'GOLD':0.08,'NATGAS':0.15,
}
H1_HOURS = {
    'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'GOLD':{8,9,13,14,15},'NATGAS':{13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'GOLD':frozenset(),'NATGAS':frozenset(),
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

def collect(k, mode='IB'):
    """
    mode='IB'   — inside bars only (matches validated backtest)
    mode='PB'   — pin bars on non-IB session bars only (extra trades STRATEGY_BOTH adds)
    mode='BOTH' — IB first, then PB on non-IB bars (matches live EA STRATEGY_BOTH)
    """
    m1 = _m1[k]; mi = m1.index
    skip = H1_SKIP.get(k, frozenset())
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
        bar = h1.iloc[i]; prev = h1.iloc[i-1]
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0: continue

        ib_h = float(bar['high']); ib_l = float(bar['low'])
        is_ib = (bar['high'] < prev['high'] and bar['low'] > prev['low'])
        ib_ok = is_ib and (ib_h-ib_l) > 0 and (ib_h-ib_l)/ib_h >= MIN_RANGE
        pb_dir = pin_bar_dir(float(bar['open']), ib_h, ib_l, float(bar['close']))

        taken = False

        # IB trade (EA checks IB first)
        if not taken and mode in ('IB', 'BOTH') and ib_ok:
            for j in range(len(window)):
                b = window.iloc[j]
                if b['high'] > ib_h:   d=1;  e=ib_h; sl=ib_l
                elif b['low'] < ib_l:  d=-1; e=ib_l; sl=ib_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE, 'type': 'IB'})
                taken = True
                break

        # PB trade — only fires when EA found no IB on this bar
        if not taken and mode in ('PB', 'BOTH') and pb_dir != 0:
            for j in range(len(window)):
                b = window.iloc[j]
                if pb_dir==1 and b['high']>ib_h:   d=1;  e=ib_h; sl=ib_l
                elif pb_dir==-1 and b['low']<ib_l: d=-1; e=ib_l; sl=ib_h
                else: continue
                ep = mi.searchsorted(window.index[j])
                if ep >= len(m1): break
                day_count[date_k] = day_count.get(date_k,0)+1
                r = vsim(k, ep, d, e, sl)
                out.append({'r_net': r - COST[k] - SLIPPAGE, 'type': 'PB'})
                taken = True
                break

    return out

def stats(trades):
    if not trades: return 0.0, 0.0, 0
    r = np.array([t['r_net'] for t in trades])
    w = r[r>0]; l = r[r<=0]
    pf = round(w.sum()/abs(l.sum()), 2) if len(l) and l.sum()!=0 else 0.0
    wr = round(len(w)/len(r)*100, 1)
    return pf, wr, len(r)

print('Loading data...')
loaded = [k for k in FILES if load(k)]

print('\nRunning OOS 2022-2025...\n')
print('='*75)
print('  PIN BAR TEST — NON-USDJPY  |  OOS 2022-2025')
print('='*75)
print(f'\n  {"":>10}  {"--- IB only (validated) ---":>26}  {"--- PB only (extra) ---":>23}')
print(f'  {"Instrument":>10}  {"N":>5} {"PF":>6} {"WR":>7}  {"N":>5} {"PF":>6} {"WR":>7}')
print(f'  {"-"*65}')

all_ib=[]; all_pb=[]
for k in loaded:
    ib = collect(k, 'IB')
    pb = collect(k, 'PB')
    all_ib.extend(ib); all_pb.extend(pb)
    ib_pf,ib_wr,ib_n = stats(ib)
    pb_pf,pb_wr,pb_n = stats(pb)
    pb_flag = '' if pb_pf >= 2.0 else (' !' if pb_pf >= 1.5 else ' ✗')
    print(f'  {k:>10}  {ib_n:>5} {ib_pf:>6.2f} {ib_wr:>6.1f}%  {pb_n:>5} {pb_pf:>6.2f} {pb_wr:>6.1f}%{pb_flag}')

print(f'  {"-"*65}')
ib_pf,ib_wr,ib_n = stats(all_ib)
pb_pf,pb_wr,pb_n = stats(all_pb)

# Combined (BOTH mode uses same day_count so run it fresh)
all_both=[]
for k in loaded:
    all_both.extend(collect(k, 'BOTH'))
bt_pf,bt_wr,bt_n = stats(all_both)

print(f'  {"TOTAL":>10}  {ib_n:>5} {ib_pf:>6.2f} {ib_wr:>6.1f}%  {pb_n:>5} {pb_pf:>6.2f} {pb_wr:>6.1f}%')

print(f'\n  Combined STRATEGY_BOTH (live):  {bt_n} trades | PF {bt_pf:.2f} | WR {bt_wr}%')
print(f'  IB only (validated backtest):   {ib_n} trades | PF {ib_pf:.2f} | WR {ib_wr}%')
print(f'  Extra trades from PB:           {pb_n} trades | PF {pb_pf:.2f}')

print('\n' + '='*75)
print('  VERDICT')
print('='*75)

if pb_pf >= 2.5:
    verdict = 'STRONG'
    msg = f'Pin bars add meaningful edge (PF {pb_pf:.2f}). Keep STRATEGY_BOTH. Live setup validated.'
elif pb_pf >= 2.0:
    verdict = 'DECENT'
    msg = f'Pin bars profitable (PF {pb_pf:.2f}) but weaker than IB. Fine to keep STRATEGY_BOTH.'
elif pb_pf >= 1.5:
    verdict = 'MARGINAL'
    msg = f'Pin bars marginal (PF {pb_pf:.2f}). Consider switching to IB only for cleaner match.'
else:
    verdict = 'NO EDGE'
    msg = f'Pin bars PF {pb_pf:.2f} — no meaningful edge on these instruments.'
    msg += '\nSwitch all non-USDJPY instances to STRATEGY_IB to match the validated backtest.'

print(f'\n  Pin bar verdict: {verdict}')
print(f'  {msg}')

if bt_pf >= ib_pf:
    print(f'\n  STRATEGY_BOTH PF ({bt_pf:.2f}) >= IB-only PF ({ib_pf:.2f}) — live setup is at least as good as backtest.')
else:
    diff = round((ib_pf - bt_pf) / ib_pf * 100, 1)
    print(f'\n  STRATEGY_BOTH PF ({bt_pf:.2f}) < IB-only PF ({ib_pf:.2f}) — pin bars drag by {diff}%.')

print('='*75)
print('Done.')
