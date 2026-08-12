"""
backtest_core.py — Gap Fill | Inside Day | PDH/PDL Sweep
OANDA M1 data, vectorized simulation, no iterrows in hot path.

Run: python backtest_core.py
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'UK100': 'UK100_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST = {'DAX':0.07,'UK100':0.07,'NAS100':0.06,'SP500':0.06,
        'EURUSD':0.08,'GBPUSD':0.08,'GOLD':0.08}
_m1 = {}

# ── DATA ──────────────────────────────────────────────────────────────────────
def load(k):
    if k in _m1: return
    fn = FILES.get(k, '')
    if not fn or not os.path.exists(fn):
        print(f'  MISSING {k}'); _m1[k] = None; return
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    print(f'  {k}: {len(_m1[k]):,} bars')

# ── SIMULATION ────────────────────────────────────────────────────────────────
def vsim(k, ep, d, entry, sl, tp_r, max_bars=4800):
    """Fixed-R TP simulation, vectorized."""
    m1 = _m1[k]
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep + 1 + max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]
    lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry + sl_d * tp_r if d == 1 else entry - sl_d * tp_r
    if d == 1:
        sl_idx = int(np.argmax(lo <= sl)) if np.any(lo <= sl) else max_bars
        tp_idx = int(np.argmax(hi >= tp)) if np.any(hi >= tp) else max_bars
    else:
        sl_idx = int(np.argmax(hi >= sl)) if np.any(hi >= sl) else max_bars
        tp_idx = int(np.argmax(lo <= tp)) if np.any(lo <= tp) else max_bars
    if tp_idx <= sl_idx: return tp_r
    if sl_idx < max_bars: return -1.0
    lp = m1['close'].values[end - 1]
    return ((lp - entry) if d == 1 else (entry - lp)) / sl_d

def vsim_price(k, ep, d, entry, sl, tp_price, max_bars=4800):
    """Price-target TP simulation (used for gap fill → prev close)."""
    m1 = _m1[k]
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep + 1 + max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]
    lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    if d == 1:
        sl_idx = int(np.argmax(lo <= sl))       if np.any(lo <= sl)       else max_bars
        tp_idx = int(np.argmax(hi >= tp_price)) if np.any(hi >= tp_price) else max_bars
    else:
        sl_idx = int(np.argmax(hi >= sl))       if np.any(hi >= sl)       else max_bars
        tp_idx = int(np.argmax(lo <= tp_price)) if np.any(lo <= tp_price) else max_bars
    if tp_idx <= sl_idx: return abs(tp_price - entry) / sl_d
    if sl_idx < max_bars: return -1.0
    lp = m1['close'].values[end - 1]
    return ((lp - entry) if d == 1 else (entry - lp)) / sl_d

# ── STATS ─────────────────────────────────────────────────────────────────────
def pf(r):
    r = np.asarray(r, float)
    w = r[r > 0]; l = r[r <= 0]
    if len(l) == 0 or l.sum() == 0: return 99.0
    return round(w.sum() / abs(l.sum()), 2)

def wr(r):
    r = np.asarray(r, float)
    return round(len(r[r > 0]) / len(r) * 100, 1) if len(r) else 0.0

# ── PRINT TABLE ───────────────────────────────────────────────────────────────
COLS = ['Nat/1.5R', 'TP_2R', 'TP_3R']

def print_table(title, results):
    W = 10
    print(f'\n{"═"*62}')
    print(f'  {title}')
    print(f'{"═"*62}')
    hdr = f'{"Instrument":<12}{"Trades":>8}' + ''.join(f'{c:>{W}}' for c in COLS)
    print(hdr); print('─' * len(hdr))
    sys_r = {c: [] for c in COLS}
    for k, rd in sorted(results.items()):
        if not rd[COLS[0]]: continue
        n = len(rd[COLS[0]])
        row = f'{k:<12}{n:>8}'
        for c in COLS:
            r = np.asarray(rd[c], float)
            sys_r[c].extend(r)
            row += f'{pf(r):>{W}.2f}'
        print(row)
    print('─' * len(hdr))
    row = f'{"SYSTEM":<12}{len(sys_r[COLS[0]]):>8}'
    for c in COLS:
        row += f'{pf(np.asarray(sys_r[c],float)):>{W}.2f}'
    print(row)
    # WR breakdown for best column
    best_c = max(COLS, key=lambda c: pf(np.asarray(sys_r[c], float)))
    print(f'\n  Best exit: {best_c}')
    for k, rd in sorted(results.items()):
        if not rd[best_c]: continue
        r = np.asarray(rd[best_c], float)
        tag = ' ★★' if pf(r) >= 1.7 else (' ★' if pf(r) >= 1.5 else ('  ✗' if pf(r) < 1.0 else ''))
        print(f'  {k:<12} {len(r):>5} trades  WR {wr(r):>5.1f}%  PF {pf(r):.2f}{tag}')
    sys_best = np.asarray(sys_r[best_c], float)
    print(f'  {"SYSTEM":<12} {len(sys_best):>5} trades  WR {wr(sys_best):>5.1f}%  PF {pf(sys_best):.2f}')


# ══════════════════════════════════════════════════════════════════════════════
# LOAD
# ══════════════════════════════════════════════════════════════════════════════
print('Loading OANDA M1 data...')
for k in FILES:
    load(k)
loaded = [k for k in FILES if _m1.get(k) is not None]
print(f'Ready: {", ".join(loaded)}\n')


# ══════════════════════════════════════════════════════════════════════════════
# 1. GAP FILL
# Overnight gap between prev session close and today's open.
# Trade: fade gap back to prev close (natural TP).
# SL: 1.5× gap distance beyond open (gap extends).
# ══════════════════════════════════════════════════════════════════════════════
GAP_CFG = {
    'DAX':   (8.0,  0.0003, 0.006),
    'UK100': (8.0,  0.0003, 0.006),
    'NAS100':(14.5, 0.0002, 0.005),
    'SP500': (14.5, 0.0002, 0.005),
}

def collect_gap(key, open_h, min_gap, max_gap):
    m1 = _m1[key]; cost = COST[key] * 1.5
    d1 = m1.resample('1D').agg({'open':'first','close':'last'}).dropna()
    dl = list(d1.index); sigs = []
    for i in range(1, len(dl)):
        ts = dl[i]
        if ts.dayofweek >= 4: continue
        prev_close = d1.iloc[i-1]['close']
        if prev_close <= 0: continue
        day = pd.Timestamp(ts.date(), tz='UTC')
        ob = m1[m1.index >= day + pd.Timedelta(hours=open_h)]
        if len(ob) == 0: continue
        open_price = ob.iloc[0]['open']
        ep = m1.index.searchsorted(ob.index[0])
        if ep >= len(m1): continue
        gap = open_price - prev_close
        gap_pct = abs(gap) / prev_close
        if gap_pct < min_gap or gap_pct > max_gap: continue
        if gap > 0:
            d = -1; sl = open_price + abs(gap) * 1.5
        else:
            d = 1;  sl = open_price - abs(gap) * 1.5
        sigs.append((ep, d, open_price, sl, prev_close, cost))
    return sigs

print('─── 1. GAP FILL ────────────────────────────────────────')
gf = {}
for k, (oh, mn, mx) in GAP_CFG.items():
    if k not in loaded: continue
    sigs = collect_gap(k, oh, mn, mx)
    print(f'  {k}: {len(sigs)} signals')
    rd = {c: [] for c in COLS}
    for ep, d, entry, sl, tp_price, cost in sigs:
        rd['Nat/1.5R'].append(vsim_price(k, ep, d, entry, sl, tp_price) - cost)
        rd['TP_2R'].append(vsim(k, ep, d, entry, sl, 2.0) - cost)
        rd['TP_3R'].append(vsim(k, ep, d, entry, sl, 3.0) - cost)
    gf[k] = rd
print_table('GAP FILL  [Nat/1.5R = fill to prev close, 2R, 3R]', gf)


# ══════════════════════════════════════════════════════════════════════════════
# 2. INSIDE DAY BREAKOUT
# ID day: yesterday's range is fully inside the day before's range.
# Entry: first M1 bar today that breaks the ID high or low.
# SL: opposite side of ID range.
# ══════════════════════════════════════════════════════════════════════════════
ID_SKIP = {
    'DAX':    frozenset({4}),
    'UK100':  frozenset({4}),
    'NAS100': frozenset({0,4}),
    'SP500':  frozenset({0,4}),
    'EURUSD': frozenset({4}),
    'GBPUSD': frozenset({4}),
    'GOLD':   frozenset({4}),
}

def collect_id(key, skip):
    m1 = _m1[key]; cost = COST[key] * 1.5
    d1 = m1.resample('1D').agg({'open':'first','high':'max',
                                'low':'min','close':'last'}).dropna()
    dl = list(d1.index); sigs = []
    for i in range(2, len(dl)):
        ts = dl[i]
        if ts.dayofweek in skip: continue
        prev  = d1.iloc[i-1]
        prev2 = d1.iloc[i-2]
        if not (prev['high'] < prev2['high'] and prev['low'] > prev2['low']): continue
        id_h = prev['high']; id_l = prev['low']
        if (id_h - id_l) <= 0: continue
        day = pd.Timestamp(ts.date(), tz='UTC')
        window = m1[(m1.index >= day) & (m1.index < day + pd.Timedelta(hours=18))]
        for j in range(len(window)):
            b = window.iloc[j]
            if b['high'] > id_h:
                d = 1; entry = id_h; sl = id_l
            elif b['low'] < id_l:
                d = -1; entry = id_l; sl = id_h
            else:
                continue
            ep = m1.index.searchsorted(window.index[j])
            if ep >= len(m1): break
            sigs.append((ep, d, entry, sl, cost)); break
    return sigs

print('\n─── 2. INSIDE DAY BREAKOUT ─────────────────────────────')
id_r = {}
for k, skip in ID_SKIP.items():
    if k not in loaded: continue
    sigs = collect_id(k, skip)
    print(f'  {k}: {len(sigs)} signals')
    rd = {c: [] for c in COLS}
    for ep, d, entry, sl, cost in sigs:
        rd['Nat/1.5R'].append(vsim(k, ep, d, entry, sl, 1.5) - cost)
        rd['TP_2R'].append(vsim(k, ep, d, entry, sl, 2.0) - cost)
        rd['TP_3R'].append(vsim(k, ep, d, entry, sl, 3.0) - cost)
    id_r[k] = rd
print_table('INSIDE DAY BREAKOUT  [1.5R, 2R, 3R]', id_r)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PDH/PDL LIQUIDITY SWEEP REVERSAL
# Price wicks through Previous Day High/Low (stop hunt) then body closes back.
# Bearish: wick above PDH, body closes below PDH → short.
# Bullish: wick below PDL, body closes above PDL → long.
# SL: beyond the wick extreme.
# ══════════════════════════════════════════════════════════════════════════════
PDL_CFG = {
    'DAX':   (8,  13, frozenset({0,4})),
    'UK100': (8,  13, frozenset({0,4})),
    'NAS100':(13, 18, frozenset({0,4})),
    'SP500': (13, 18, frozenset({0,4})),
    'EURUSD':(7,  12, frozenset({4})),
    'GBPUSD':(7,  12, frozenset({4})),
    'GOLD':  (8,  13, frozenset({4})),
}

def collect_pdh(key, lsh, leh, skip):
    m1 = _m1[key]; cost = COST[key] * 1.5
    d1 = m1.resample('1D').agg({'high':'max','low':'min'}).dropna()
    dates = sorted(set(m1.index.normalize().date)); sigs = []
    for date in dates[1:]:
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip: continue
        prev = d1[d1.index.normalize().date < date]
        if len(prev) == 0: continue
        pdh = prev.iloc[-1]['high']; pdl = prev.iloc[-1]['low']
        pd_rng = pdh - pdl
        if pd_rng <= 0: continue
        min_wick = pd_rng * 0.001
        window = m1[(m1.index >= day + pd.Timedelta(hours=lsh)) &
                    (m1.index < day + pd.Timedelta(hours=leh))]
        if len(window) == 0: continue
        for j in range(len(window)):
            b = window.iloc[j]
            body_h = max(b['open'], b['close'])
            body_l = min(b['open'], b['close'])
            ep = m1.index.searchsorted(window.index[j])
            if ep >= len(m1): break
            if b['high'] > pdh and body_h < pdh and (b['high'] - body_h) >= min_wick:
                sl = b['high'] + pd_rng * 0.05
                sigs.append((ep, -1, body_h, sl, cost)); break
            elif b['low'] < pdl and body_l > pdl and (body_l - b['low']) >= min_wick:
                sl = b['low'] - pd_rng * 0.05
                sigs.append((ep, 1, body_l, sl, cost)); break
    return sigs

print('\n─── 3. PDH/PDL LIQUIDITY SWEEP ─────────────────────────')
pdl_r = {}
for k, (lsh, leh, skip) in PDL_CFG.items():
    if k not in loaded: continue
    sigs = collect_pdh(k, lsh, leh, skip)
    print(f'  {k}: {len(sigs)} signals')
    rd = {c: [] for c in COLS}
    for ep, d, entry, sl, cost in sigs:
        rd['Nat/1.5R'].append(vsim(k, ep, d, entry, sl, 1.5) - cost)
        rd['TP_2R'].append(vsim(k, ep, d, entry, sl, 2.0) - cost)
        rd['TP_3R'].append(vsim(k, ep, d, entry, sl, 3.0) - cost)
    pdl_r[k] = rd
print_table('PDH/PDL LIQUIDITY SWEEP REVERSAL  [1.5R, 2R, 3R]', pdl_r)


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
print('\n\n' + '═'*62)
print('  SUMMARY')
print('═'*62)
for name, res in [('Gap Fill', gf), ('Inside Day', id_r), ('PDH/PDL Sweep', pdl_r)]:
    all_r = {c: [] for c in COLS}
    for rd in res.values():
        for c in COLS:
            all_r[c].extend(rd[c])
    best = max(COLS, key=lambda c: pf(np.asarray(all_r[c], float)))
    r = np.asarray(all_r[best], float)
    flag = ' ★★★ TARGET HIT' if pf(r) >= 2.0 else (' ★★ VERY CLOSE' if pf(r) >= 1.7 else (' ★ PROMISING' if pf(r) >= 1.5 else ''))
    print(f'  {name:<18} {len(r):>5} trades  WR {wr(r):>5.1f}%  PF {pf(r):.2f}  ({best}){flag}')
print('═'*62)
print('\nDone.')
