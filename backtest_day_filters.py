"""
backtest_day_filters.py
Tests day-of-week filters and EOD close rules on M1GOATV2.

Configurations tested:
  1. Baseline       — current (no Fri for most, no Sun/Fri for US)
  2. No Monday      — skip Mon + existing skips
  3. No Mon+Fri     — skip both Mon and Fri
  4. EOD close      — force close any open trade at 22:00 UTC same day
  5. No Mon + EOD   — combined

Run: python backtest_day_filters.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
TP_R      = 4.0
SLIPPAGE  = 0.10
MAX_PD    = 3
WIN_HOURS = 3
ACCOUNT   = 70_000
RISK_FRAC = 0.005
EOD_HOUR  = 22    # force close at 22:00 UTC

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

# Base skips (current EA behaviour)
H1_SKIP_BASE = {
    'DAX':    frozenset({4}),
    'EURUSD': frozenset({4}),
    'GBPUSD': frozenset({4}),
    'USDJPY': frozenset({4}),
    'GOLD':   frozenset({4}),
    'NATGAS': frozenset({4}),
    'NAS100': frozenset({0,4}),  # already skips Monday
    'SP500':  frozenset({0,4}),
    'US30':   frozenset({0,4}),
}
WICK_BODY  = 2.0
WICK_RANGE = 0.5

_m1 = {}

# ── LOAD ──────────────────────────────────────────────────────────────────────
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

# ── SIMULATORS ────────────────────────────────────────────────────────────────
def vsim_normal(k, ep, d, entry, sl, max_bars=480):
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep + 1 + max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry + sl_d * TP_R if d == 1 else entry - sl_d * TP_R
    if d == 1:
        sl_i = int(np.argmax(lo <= sl)) if np.any(lo <= sl) else max_bars
        tp_i = int(np.argmax(hi >= tp)) if np.any(hi >= tp) else max_bars
    else:
        sl_i = int(np.argmax(hi >= sl)) if np.any(hi >= sl) else max_bars
        tp_i = int(np.argmax(lo <= tp)) if np.any(lo <= tp) else max_bars
    if tp_i <= sl_i: return TP_R
    if sl_i < max_bars: return -1.0
    return ((m1['close'].values[end-1] - entry) if d==1 else (entry - m1['close'].values[end-1])) / sl_d

def vsim_eod(k, ep, entry_ts, d, entry, sl):
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    eod = entry_ts.replace(hour=EOD_HOUR, minute=0, second=0, microsecond=0)
    if entry_ts >= eod: return None  # too late, skip trade
    bars = m1[(m1.index > entry_ts) & (m1.index <= eod)]
    if len(bars) == 0: return None
    hi = bars['high'].values; lo = bars['low'].values
    tp = entry + sl_d * TP_R if d == 1 else entry - sl_d * TP_R
    max_b = len(hi)
    if d == 1:
        sl_i = int(np.argmax(lo <= sl)) if np.any(lo <= sl) else max_b
        tp_i = int(np.argmax(hi >= tp)) if np.any(hi >= tp) else max_b
    else:
        sl_i = int(np.argmax(hi >= sl)) if np.any(hi >= sl) else max_b
        tp_i = int(np.argmax(lo <= tp)) if np.any(lo <= tp) else max_b
    if tp_i <= sl_i: return TP_R
    if sl_i < max_b: return -1.0
    # Closed at EOD — take current price
    lp = bars['close'].values[-1]
    return ((lp - entry) if d==1 else (entry - lp)) / sl_d

# ── PIN BAR ───────────────────────────────────────────────────────────────────
def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body, full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body, full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

# ── COLLECTOR ─────────────────────────────────────────────────────────────────
def collect(key, skip_override=None, use_eod=False):
    m1 = _m1[key]; mi = m1.index
    skip = skip_override if skip_override is not None else H1_SKIP_BASE.get(key, frozenset({4}))
    p_hours = H1_HOURS.get(key, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); out = []; day_count = {}
    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue

        bar = h1.iloc[i]

        if key == 'USDJPY':
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
                if use_eod:
                    r = vsim_eod(key, ep, window.index[j], d, ep2, sl)
                    if r is None: break
                else:
                    r = vsim_normal(key, ep, d, ep2, sl)
                day_count[date_k] = day_count.get(date_k, 0) + 1
                out.append({'date': date_k, 'year': ts.year,
                            'r_net': r - COST[key] - SLIPPAGE})
                break
        else:
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
                if use_eod:
                    r = vsim_eod(key, ep, window.index[j], d, ep2, sl)
                    if r is None: break
                else:
                    r = vsim_normal(key, ep, d, ep2, sl)
                day_count[date_k] = day_count.get(date_k, 0) + 1
                out.append({'date': date_k, 'year': ts.year,
                            'r_net': r - COST[key] - SLIPPAGE})
                break
    return out

def pf(r):
    r = np.asarray(r, float); w = r[r>0]; l = r[r<=0]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
def wr(r):
    r = np.asarray(r, float)
    return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

# ── LOAD DATA ─────────────────────────────────────────────────────────────────
print('Loading data...')
loaded = []
for k in FILES:
    if load(k):
        loaded.append(k)
        print(f'  {k}: {len(_m1[k]):,} bars')
    else:
        print(f'  {k}: not found')

OOS_DAYS = (OOS_END - OOS_START).days / 7 * 5

# ── BUILD SKIP CONFIGS ────────────────────────────────────────────────────────
def make_skip(add_monday=False, add_friday=False):
    result = {}
    for k in loaded:
        base = set(H1_SKIP_BASE.get(k, frozenset({4})))
        if add_monday: base.add(0)
        if add_friday: base.add(4)
        result[k] = frozenset(base)
    return result

CONFIGS = [
    ('Baseline (current)',       make_skip(),                          False),
    ('No Monday',                make_skip(add_monday=True),           False),
    ('No Mon + No Fri',          make_skip(add_monday=True,
                                           add_friday=True),           False),
    ('EOD close 22:00',          make_skip(),                          True),
    ('No Monday + EOD close',    make_skip(add_monday=True),           True),
    ('No Mon+Fri + EOD close',   make_skip(add_monday=True,
                                           add_friday=True),           True),
]

# ── RUN ALL CONFIGS ───────────────────────────────────────────────────────────
print()
print('=' * 80)
print('  DAY FILTER + EOD CLOSE TEST  |  OOS 2022-2025  |  TP = 4R')
print('=' * 80)
print(f'\n  {"Config":<26}  {"Trades":>7}  {"T/day":>6}  {"WR":>7}  '
      f'{"PF":>7}  {"Exp/trade":>10}  {"Monthly":>10}')
print(f'  {"-"*78}')

best_pf = 0
best_name = ''
results = {}

for name, skip_cfg, eod in CONFIGS:
    print(f'  Running: {name}...')
    all_trades = []
    for k in loaded:
        t = collect(k, skip_override=skip_cfg.get(k), use_eod=eod)
        all_trades.extend(t)
    r = np.asarray([t['r_net'] for t in all_trades], float)
    if len(r) == 0:
        print(f'  {name:<26}  (no trades)')
        continue
    tpd = len(r) / OOS_DAYS
    exp = r.mean()
    monthly = exp * tpd * ACCOUNT * RISK_FRAC * 22
    p = pf(r)
    flag = ' *' if p > best_pf else ''
    if p > best_pf:
        best_pf = p; best_name = name
    results[name] = {'n': len(r), 'tpd': tpd, 'wr': wr(r), 'pf': p,
                     'exp': exp, 'monthly': monthly, 'r': r}
    print(f'  {name:<26}  {len(r):>7,}  {tpd:>6.2f}  {wr(r):>6.1f}%  '
          f'{p:>7.2f}  {exp:>+9.3f}R  GBP{monthly:>8,.0f}{flag}')

# ── YEAR BY YEAR FOR BEST CONFIG ──────────────────────────────────────────────
print()
print('=' * 80)
print(f'  YEAR BY YEAR — Best config: {best_name}')
print('=' * 80)
print(f'\n  {"Year":>6}  {"Trades":>7}  {"WR":>7}  {"PF":>7}  {"Status":>12}')
print(f'  {"-"*48}')

# Re-collect for best config
best_cfg = next(c for c in CONFIGS if c[0] == best_name)
skip_cfg_best, eod_best = best_cfg[1], best_cfg[2]
all_best = []
for k in loaded:
    t = collect(k, skip_override=skip_cfg_best.get(k), use_eod=eod_best)
    all_best.extend(t)

for yr in range(2018, 2026):
    t_yr = [t for t in all_best if t['year'] == yr]
    r = np.asarray([t['r_net'] for t in t_yr], float)
    if len(r) < 10: continue
    label = 'IS' if yr < 2022 else 'OOS'
    status = 'POSITIVE' if pf(r) >= 1.5 else ('MARGINAL' if pf(r) >= 1.0 else 'NEGATIVE')
    print(f'  {yr:>6}  {len(r):>7}  {wr(r):>6.1f}%  {pf(r):>7.2f}  [{label}] {status}')

# ── MONDAY VS FRIDAY BREAKDOWN ────────────────────────────────────────────────
print()
print('=' * 80)
print('  MON vs FRI BREAKDOWN — Baseline trades only')
print('=' * 80)

# Re-collect baseline with day tag
print('\n  Collecting baseline with day tags...')
baseline_trades = []
skip_base = make_skip()
for k in loaded:
    m1 = _m1[k]; mi = m1.index
    skip = skip_base.get(k, frozenset({4}))
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
    if len(m1w) < 100: continue
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); day_count = {}
    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        dow = ts.dayofweek
        if dow in skip: continue
        if day_count.get(date_k, 0) >= MAX_PD: continue
        if k == 'USDJPY':
            bar = h1.iloc[i]
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
                r = vsim_normal(k, ep, d, ep2, sl)
                day_count[date_k] = day_count.get(date_k, 0) + 1
                baseline_trades.append({'dow': dow, 'r_net': r - COST[k] - SLIPPAGE})
                break
        else:
            prev = h1.iloc[i-1]
            bar = h1.iloc[i]
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
                r = vsim_normal(k, ep, d, ep2, sl)
                day_count[date_k] = day_count.get(date_k, 0) + 1
                baseline_trades.append({'dow': dow, 'r_net': r - COST[k] - SLIPPAGE})
                break

day_names = {0:'Monday',1:'Tuesday',2:'Wednesday',3:'Thursday',4:'Friday'}
print(f'\n  {"Day":<12}  {"Trades":>7}  {"WR":>7}  {"PF":>7}  {"Exp/trade":>10}  {"Verdict":>12}')
print(f'  {"-"*60}')
for dow in range(5):
    t_dow = [t for t in baseline_trades if t['dow'] == dow]
    r = np.asarray([t['r_net'] for t in t_dow], float)
    if len(r) < 10:
        print(f'  {day_names[dow]:<12}  (skipped or no data)')
        continue
    p = pf(r)
    verdict = 'STRONG' if p >= 2.5 else ('GOOD' if p >= 1.5 else ('WEAK' if p >= 1.0 else 'AVOID'))
    print(f'  {day_names[dow]:<12}  {len(r):>7}  {wr(r):>6.1f}%  {p:>7.2f}  '
          f'{r.mean():>+9.3f}R  {verdict:>12}')

print()
print('=' * 80)
print('  VERDICT')
print('=' * 80)
if best_name != 'Baseline (current)':
    base_pf = results.get('Baseline (current)', {}).get('pf', 0)
    print(f'  Best config: {best_name}')
    print(f'  PF improvement over baseline: {best_pf - base_pf:+.2f}')
    print(f'  Recommendation: consider updating EA skip days')
else:
    print(f'  Baseline is already optimal — no day filter improvement found')
print('=' * 80)
print('Done.')
