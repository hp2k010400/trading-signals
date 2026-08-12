"""
backtest_m1_baseline.py  -  Ground truth M1 baseline, all 7 instruments
========================================================================
Data   : OANDA M1 CSVs (2018-2026), resampled to H1 for signal detection
Exits  : Trail 0.05 (live), Trail 5.0 (best sweep), TP 1R, TP 1.5R, TP 2R, TP 3R
Output : Per-strategy and system-level PF, WR, AvgW, trades for every exit method

Run: python backtest_m1_baseline.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── OANDA file map ─────────────────────────────────────────────────────────────
FILES = {
    'EURUSD': 'EURUSD_M1_oanda.csv',
    'GBPUSD': 'GBPUSD_M1_oanda.csv',
    'GOLD':   'XAUUSD_M1_oanda.csv',
    'DAX':    'GER40_M1_oanda.csv',
    'UK100':  'UK100_M1_oanda.csv',
    'NAS100': 'US100_M1_oanda.csv',
    'SP500':  'US500_M1_oanda.csv',
}

# Spread cost as fraction of 1R (broker spread / typical SL size)
COST = {
    'DAX':0.07, 'NAS100':0.06, 'SP500':0.06,
    'EURUSD':0.08, 'GBPUSD':0.08, 'UK100':0.07, 'GOLD':0.08
}

EXIT_METHODS = [
    ('Trail_0.05', 'trail', 0.05),   # current live
    ('Trail_5.0',  'trail', 5.0),    # best from sweep
    ('TP_1R',      'tp',    1.0),
    ('TP_1.5R',    'tp',    1.5),
    ('TP_2R',      'tp',    2.0),
    ('TP_3R',      'tp',    3.0),
]

# ── Load & cache ───────────────────────────────────────────────────────────────
_m1_cache, _h1_cache = {}, {}

def load_m1(key):
    if key in _m1_cache: return _m1_cache[key]
    fn = FILES[key]
    if not os.path.exists(fn):
        print(f'  MISSING: {fn}'); _m1_cache[key] = None; return None
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    _m1_cache[key] = df
    return df

def load_h1(key):
    if key in _h1_cache: return _h1_cache[key]
    m1 = load_m1(key)
    if m1 is None: _h1_cache[key] = None; return None
    h1 = m1.resample('1h').agg(open='first',high='max',low='min',close='last',tick_volume='sum').dropna()
    _h1_cache[key] = h1
    return h1

# ── Simulation ─────────────────────────────────────────────────────────────────
def sim(m1, ep, direction, entry, sl, method, value, max_bars=4800):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    rows = m1.iloc[ep+1: ep+1+max_bars]
    if method == 'tp':
        tp = entry + sl_d * value if direction == 1 else entry - sl_d * value
        for _, b in rows.iterrows():
            if direction == 1:
                if b['low']  <= sl: return -1.0
                if b['high'] >= tp: return value
            else:
                if b['high'] >= sl: return -1.0
                if b['low']  <= tp: return value
    else:  # trailing stop
        tr = sl_d * value; cs = sl; bst = entry; be = False
        for _, b in rows.iterrows():
            if direction == 1:
                if b['low'] <= cs: return (cs - entry) / sl_d
                bst = max(bst, b['high'])
                if not be and bst >= entry + sl_d: be = True; cs = entry
                if be:
                    ns = bst - tr
                    if ns > cs: cs = ns
            else:
                if b['high'] >= cs: return (entry - cs) / sl_d
                bst = min(bst, b['low'])
                if not be and bst <= entry - sl_d: be = True; cs = entry
                if be:
                    ns = bst + tr
                    if ns < cs: cs = ns
    lp = m1.iloc[min(ep + max_bars, len(m1)-1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def m1_pos(m1, ts):
    p = m1.index.searchsorted(ts)
    return int(p) if p < len(m1) else -1

# ── Signal generators ──────────────────────────────────────────────────────────
def signals_orb(key, ref_h, es, ee, rmin, rmax, skip_dow=frozenset()):
    h1 = load_h1(key); m1 = load_m1(key)
    if h1 is None: return []
    cost = COST[key] * 1.5
    sigs = []
    for date in sorted(set(h1.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb = h1[h1.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue
        edf = h1[(h1.index >= day + pd.Timedelta(hours=es)) &
                 (h1.index <  day + pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]
            if b['high'] > rhi:   d, entry, sl = 1,  rhi, rlo
            elif b['low'] < rlo:  d, entry, sl = -1, rlo, rhi
            else: continue
            ep = m1_pos(m1, edf.index[j])
            if ep < 0: continue
            sigs.append((m1, ep, d, entry, sl, cost))
            break
    return sigs

def signals_lc(key, min_move):
    h1 = load_h1(key); m1 = load_m1(key)
    if h1 is None: return []
    cost = COST[key] * 1.5
    sigs = []
    for date in sorted(set(h1.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        ob = h1[h1.index == day + pd.Timedelta(hours=7)]
        cb = h1[h1.index == day + pd.Timedelta(hours=15)]
        if len(ob) == 0 or len(cb) == 0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue
        sess = h1[(h1.index >= day + pd.Timedelta(hours=7)) &
                  (h1.index <= day + pd.Timedelta(hours=16))]
        if len(sess) == 0: continue
        dh = sess['high'].max(); dl = sess['low'].min()
        buf = (dh - dl) * 0.03
        p16 = h1[h1.index == day + pd.Timedelta(hours=16)]
        if len(p16) == 0: continue
        entry = p16.iloc[0]['open']
        d = -1 if move > 0 else 1
        sl = (dh + buf) if d == -1 else (dl - buf)
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        ep = m1_pos(m1, day + pd.Timedelta(hours=16))
        if ep < 0: continue
        sigs.append((m1, ep, d, entry, sl, cost))
    return sigs

# ── Stats ──────────────────────────────────────────────────────────────────────
def stats(r):
    if len(r) == 0: return None
    w = r[r > 0]; l = r[r <= 0]
    pf = w.sum() / abs(l.sum()) if len(l) and l.sum() != 0 else float('inf')
    return {'n': len(r), 'pf': pf, 'wr': len(w)/len(r)*100,
            'avgw': w.mean() if len(w) else 0, 'avgl': l.mean() if len(l) else 0}

# ── Load data ──────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data and resampling to H1...')
for key in FILES: load_h1(key)

loaded = [k for k in FILES if _m1_cache.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}')
if not loaded: print('No data found.'); exit(1)

m1_dates = set()
for k in loaded:
    m1_dates |= set(_m1_cache[k].index.normalize().date)
d_min, d_max = min(m1_dates), max(m1_dates)
print(f'Period : {d_min} to {d_max}\n')

# ── Collect signals ────────────────────────────────────────────────────────────
print('Collecting signals...')
STRATEGIES = {
    'DAX_ORB':  signals_orb('DAX',   8, 10, 12,   20, 200),
    'NAS_ORB':  signals_orb('NAS100',14, 16, 18,   30,1000, frozenset({0,2,4})),
    'SP5_ORB':  signals_orb('SP500', 14, 16, 19,    3, 150, frozenset({0})),
    'LC_EUR':   signals_lc('EURUSD', 0.001),
    'LC_GBP':   signals_lc('GBPUSD', 0.0025),
    'LC_DAX':   signals_lc('DAX',    50.0),
    'LC_UK':    signals_lc('UK100',  30.0),
    'LC_GOLD':  signals_lc('GOLD',   4.0),
}
for name, sigs in STRATEGIES.items():
    print(f'  {name:10}: {len(sigs):>4} signals')

# ── Run all exits ──────────────────────────────────────────────────────────────
print('\nSimulating on M1...\n')

# results[exit_label][strat] = array of R values
results = {label: {name: [] for name in STRATEGIES} for label, _, _ in EXIT_METHODS}

for name, sigs in STRATEGIES.items():
    for m1, ep, d, entry, sl, cost in sigs:
        for label, method, value in EXIT_METHODS:
            r = sim(m1, ep, d, entry, sl, method, value) - cost
            results[label][name].append(r)

# ── Print results table ────────────────────────────────────────────────────────
W = 12
header = f'{"Strategy":<12}' + ''.join(f'{lbl:>{W}}' for lbl, _, _ in EXIT_METHODS)
print('═' * len(header))
print('  PF BY EXIT METHOD')
print('═' * len(header))
print(header)
print('─' * len(header))

system_r = {label: [] for label, _, _ in EXIT_METHODS}

for name in STRATEGIES:
    row = f'{name:<12}'
    for label, _, _ in EXIT_METHODS:
        r = np.array(results[label][name])
        system_r[label].extend(r)
        if len(r) == 0: row += f'{"—":>{W}}'; continue
        s = stats(r)
        row += f'{s["pf"]:>{W}.2f}'
    print(row)

print('─' * len(header))
row = f'{"SYSTEM":<12}'
for label, _, _ in EXIT_METHODS:
    r = np.array(system_r[label])
    s = stats(r)
    row += f'{s["pf"]:>{W}.2f}'
print(row)
print('═' * len(header))

# ── Detailed best exit breakdown ───────────────────────────────────────────────
best_label = max(EXIT_METHODS, key=lambda x: stats(np.array(system_r[x[0]]))['pf'])[0]
print(f'\n  Best exit: {best_label}')
print(f'\n{"Strategy":<12} {"Trades":>7} {"WR":>7} {"PF":>7} {"AvgW":>8} {"AvgL":>8}')
print('─' * 55)
for name in STRATEGIES:
    r = np.array(results[best_label][name])
    if len(r) == 0: continue
    s = stats(r)
    mark = '  ◄ DROP' if s['pf'] < 1.0 else ''
    print(f'{name:<12} {s["n"]:>7} {s["wr"]:>6.1f}% {s["pf"]:>7.2f} {s["avgw"]:>7.2f}R {s["avgl"]:>7.2f}R{mark}')
print('─' * 55)
sys_r = np.array(system_r[best_label])
s = stats(sys_r)
print(f'{"SYSTEM":<12} {s["n"]:>7} {s["wr"]:>6.1f}% {s["pf"]:>7.2f} {s["avgw"]:>7.2f}R {s["avgl"]:>7.2f}R')
print('═' * 55)
print(f'\nPeriod: {d_min} to {d_max}')
