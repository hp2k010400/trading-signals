"""
backtest_optimise2.py — Exit & parameter optimisation

A. TRAIL SWEEP    — 0.2R to 1.5R across all strong strategies
B. PARTIAL TP     — 50% out at 1R + trail vs full trail
C. MONTH FILTER   — which months hurt PF? Should we skip any?
D. WALK-FORWARD   — in-sample vs out-of-sample edge validation

Strategies tested (with known DOW filters already applied):
  NAS100 ORB  (skip Mon)  |  NatGas ORB (all days)  |  SP500 ORB  (skip Mon)
  LB EURUSD   (skip Tue)  |  DAX H4 EMA              |  NatGas H4 EMA
  UK100 H4 EMA

Run: python backtest_optimise2.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT    = 70_000
RISK       = ACCOUNT * 0.005          # £350 per trade @ 0.5%
TRAIL_VALS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5]

# ── Data ──────────────────────────────────────────────────────────────────────
_cache = {}
def get_h1(sym):
    if sym not in _cache:
        try:
            df = yf.download(sym, interval="1h", period="730d",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None: df.index = df.index.tz_localize('UTC')
            else:                   df.index = df.index.tz_convert('UTC')
            _cache[sym] = df if len(df) > 200 else None
        except: _cache[sym] = None
    return _cache[sym]

def resample_h4(df):
    return df.resample('4h').agg({'open':'first','high':'max',
                                   'low':'min','close':'last','volume':'sum'}).dropna()

def add_indicators(df, fast=10, slow=20, p=14):
    d = df.copy()
    d['ef']  = d['close'].ewm(span=fast, adjust=False).mean()
    d['es']  = d['close'].ewm(span=slow, adjust=False).mean()
    hi,lo,cl = d['high'],d['low'],d['close']
    tr  = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    d['atr'] = tr.ewm(com=p-1, adjust=False).mean()
    dmp = ((hi-hi.shift())>(lo.shift()-lo)).astype(float)*(hi-hi.shift()).clip(lower=0)
    dmm = ((lo.shift()-lo)>(hi-hi.shift())).astype(float)*(lo.shift()-lo).clip(lower=0)
    as_ = tr.ewm(com=p-1, adjust=False).mean()
    dip = 100*dmp.ewm(com=p-1,adjust=False).mean()/as_
    dim = 100*dmm.ewm(com=p-1,adjust=False).mean()/as_
    dx  = (100*(dip-dim).abs()/(dip+dim).replace(0,1)).fillna(0)
    d['adx']  = dx.ewm(com=p-1, adjust=False).mean()
    d['bull'] = (d['ef']>d['es']) & (d['ef'].shift()<=d['es'].shift())
    d['bear'] = (d['ef']<d['es']) & (d['ef'].shift()>=d['es'].shift())
    return d

# ── Simulators ────────────────────────────────────────────────────────────────

def sim_trail(bars_df, direction, entry, sl, trail_mult, max_bars=200):
    """Full-position trailing stop. Returns R outcome."""
    sl_dist = abs(entry - sl)
    if sl_dist <= 0 or len(bars_df) == 0: return 0.0
    trail  = sl_dist * trail_mult
    sl_cur = sl; best = entry; be = False
    rows   = bars_df.iloc[:max_bars]
    ex     = rows.iloc[-1]['close']

    for _, b in rows.iterrows():
        if direction == 'buy':
            if b['low']  <= sl_cur: return (sl_cur - entry) / sl_dist
            if b['high'] > best:    best = b['high']
            if not be and best >= entry + sl_dist: be = True; sl_cur = entry
            if be:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur: return (entry - sl_cur) / sl_dist
            if b['low']  < best:    best = b['low']
            if not be and best <= entry - sl_dist: be = True; sl_cur = entry
            if be:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns
    return ((ex - entry) if direction == 'buy' else (entry - ex)) / sl_dist


def sim_partial(bars_df, direction, entry, sl, trail_mult, max_bars=200):
    """50% closed at 1R, remaining 50% trails. Returns blended R."""
    sl_dist = abs(entry - sl)
    if sl_dist <= 0 or len(bars_df) == 0: return 0.0
    trail        = sl_dist * trail_mult
    tp1          = entry + sl_dist if direction == 'buy' else entry - sl_dist
    sl_cur       = sl; best = entry
    half_closed  = False; half_r = 0.0
    rows         = bars_df.iloc[:max_bars]

    for _, b in rows.iterrows():
        if direction == 'buy':
            if b['low'] <= sl_cur:
                r2 = (sl_cur - entry) / sl_dist
                return (0.5*half_r + 0.5*r2) if half_closed else r2
            if b['high'] > best: best = b['high']
            if not half_closed and best >= tp1:
                half_closed = True; half_r = 1.0; sl_cur = entry
            if half_closed:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur:
                r2 = (entry - sl_cur) / sl_dist
                return (0.5*half_r + 0.5*r2) if half_closed else r2
            if b['low'] < best: best = b['low']
            if not half_closed and best <= tp1:
                half_closed = True; half_r = 1.0; sl_cur = entry
            if half_closed:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns

    ex = rows.iloc[-1]['close']
    r2 = ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist
    return (0.5*half_r + 0.5*r2) if half_closed else r2

# ── Setup collectors — separates trade discovery from simulation ──────────────

def collect_orb(sym, min_rng, max_rng, exit_h=20, skip_dow=None, date_f=None):
    """Returns list of dicts: {dir, entry, sl, bars_df, month, date, year}"""
    df = get_h1(sym)
    if df is None: return []
    setups = []
    for d in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(d, tz='UTC')
        if day.dayofweek >= 5: continue
        if skip_dow and day.dayofweek in skip_dow: continue
        if date_f and not date_f(day): continue
        pm = df[df.index == day + pd.Timedelta(hours=13)]
        if len(pm) == 0: continue
        r_hi, r_lo = pm.iloc[0]['high'], pm.iloc[0]['low']
        rng = r_hi - r_lo
        if not (min_rng <= rng <= max_rng): continue
        eb = df[(df.index >= day+pd.Timedelta(hours=14)) &
                (df.index <  day+pd.Timedelta(hours=16))]
        direction = entry = et = None
        for bt, b in eb.iterrows():
            if b['high'] > r_hi: direction='buy';  entry=r_hi; et=bt; break
            if b['low']  < r_lo: direction='sell'; entry=r_lo; et=bt; break
        if direction is None: continue
        sl = r_lo if direction=='buy' else r_hi
        if abs(entry-sl) <= 0: continue
        bars = df[(df.index > et) & (df.index <= day+pd.Timedelta(hours=exit_h))]
        setups.append({'dir':direction,'entry':entry,'sl':sl,
                       'bars':bars,'month':day.month,'year':day.year,'date':day})
    return setups


def collect_lb(sym, pip, min_pips=10, max_pips=100, skip_dow=None, date_f=None):
    df = get_h1(sym)
    if df is None: return []
    setups = []
    for d in sorted(set(df.index.normalize().date)):
        day  = pd.Timestamp(d, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if day.dayofweek >= 5: continue
        if skip_dow and day.dayofweek in skip_dow: continue
        if date_f and not date_f(day): continue
        rb = df[(df.index >= prev+pd.Timedelta(hours=22)) &
                (df.index <  day +pd.Timedelta(hours=7))]
        if len(rb) < 3: continue
        r_hi, r_lo = rb['high'].max(), rb['low'].min()
        rng = r_hi - r_lo
        if not (min_pips <= rng/pip <= max_pips): continue
        eb = df[(df.index >= day+pd.Timedelta(hours=7)) &
                (df.index <  day+pd.Timedelta(hours=10))]
        direction = entry = et = None
        for bt, b in eb.iterrows():
            if b['high'] > r_hi: direction='buy';  entry=r_hi; et=bt; break
            if b['low']  < r_lo: direction='sell'; entry=r_lo; et=bt; break
        if direction is None: continue
        buf = rng * 0.15
        sl  = (r_lo-buf) if direction=='buy' else (r_hi+buf)
        if abs(entry-sl) <= 0: continue
        bars = df[(df.index > et) & (df.index <= day+pd.Timedelta(hours=13))]
        setups.append({'dir':direction,'entry':entry,'sl':sl,
                       'bars':bars,'month':day.month,'year':day.year,'date':day})
    return setups


def collect_h4(sym, s_start, s_end, adx_min=25, date_f=None):
    h1 = get_h1(sym)
    if h1 is None: return []
    df = add_indicators(resample_h4(h1))
    setups = []
    for i in range(25, len(df)):
        bar = df.iloc[i]
        if date_f and not date_f(bar.name): continue
        h = bar.name.hour
        if not (s_start <= h < s_end): continue
        if bar['adx'] < adx_min: continue
        direction = 'buy' if bar['bull'] else ('sell' if bar['bear'] else None)
        if direction is None: continue
        entry = bar['close']
        sl    = entry-1.5*bar['atr'] if direction=='buy' else entry+1.5*bar['atr']
        bars  = df.iloc[i+1:i+121]
        setups.append({'dir':direction,'entry':entry,'sl':sl,
                       'bars':bars,'month':bar.name.month,
                       'year':bar.name.year,'date':bar.name})
    return setups

# ── Stats ──────────────────────────────────────────────────────────────────────

def pf(results_r):
    if len(results_r) < 8: return 0.0
    gbp   = np.array(results_r) * RISK
    wins  = gbp[gbp >  5].sum()
    loss  = abs(gbp[gbp < -5].sum())
    return round(wins / (loss if loss > 0 else 1), 2)

def stats(results_r, setups):
    if len(results_r) < 8: return None
    gbp    = np.array(results_r) * RISK
    wins   = gbp[gbp >  5]; losses = gbp[gbp < -5]
    n      = len(gbp)
    wr     = len(wins)/n*100
    pf_    = wins.sum() / (abs(losses.sum()) if len(losses) else 1)
    total  = gbp.sum()
    cum    = np.cumsum(gbp); pk = np.maximum.accumulate(cum)
    dd     = (cum-pk).min()
    days   = max(1, (setups[-1]['date']-setups[0]['date']).days)
    mo     = total/days*30
    return {'n':n,'wr':round(wr,1),'pf':round(pf_,2),
            'mo':round(mo*2,0),'dd':round(dd*2,0)}

def verdict(p): return "✅ STRONG" if p>=1.5 else ("⚠️  OK" if p>=1.2 else "❌")

# ── Strategies ────────────────────────────────────────────────────────────────

print("Loading data (this takes ~60s)...", flush=True)

STRATEGIES = {
    'NAS100 ORB':  collect_orb("NQ=F",   50,   1500, skip_dow={0}),
    'NatGas ORB':  collect_orb("NG=F",   0.03, 1.0),
    'SP500 ORB':   collect_orb("ES=F",   10,   200,  skip_dow={0}),
    'LB EURUSD':   collect_lb ("EURUSD=X",0.0001,     skip_dow={1}),
    'DAX H4 EMA':  collect_h4 ("^GDAXI", 8,  16),
    'NatGas H4':   collect_h4 ("NG=F",  14,  21),
    'UK100 H4':    collect_h4 ("^FTSE",  8,  16),
}

print("Done.\n")

# ══════════════════════════════════════════════════════════════════════════════
# A. TRAILING STOP SWEEP
# ══════════════════════════════════════════════════════════════════════════════

print("=" * 90)
print("  A. TRAILING STOP SWEEP — profit factor at each R multiplier")
print("  Current setting: 0.5R  |  Lower = tighter trail  |  Higher = more room")
print("=" * 90)
print(f"\n  {'Strategy':<14}" + "".join(f"  {t:.1f}R" for t in TRAIL_VALS)
      + "   BEST")
print("  " + "─" * 80)

best_trail = {}
for name, setups in STRATEGIES.items():
    if not setups: continue
    pfs = []
    for tv in TRAIL_VALS:
        results = [sim_trail(s['bars'], s['dir'], s['entry'], s['sl'], tv)
                   for s in setups]
        pfs.append(pf(results))
    bi        = int(np.argmax(pfs))
    best_trail[name] = TRAIL_VALS[bi]
    row = f"  {name:<14}" + "".join(f"  {p:.2f}" for p in pfs)
    row += f"  ← {TRAIL_VALS[bi]}R ({pfs[bi]:.2f})"
    print(row)

# ══════════════════════════════════════════════════════════════════════════════
# B. PARTIAL TP vs FULL TRAIL
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*90}")
print("  B. PARTIAL TP — 50% out at 1R, trail rest  vs  full-position trail")
print(f"  Each at its own optimal trail multiplier from section A")
print(f"{'='*90}")
print(f"  {'Strategy':<14} {'Mode':<13} {'Win%':>5}  {'T/mo':>5}  "
      f"{'Monthly@1%':>11}  {'PF':>5}  {'DD@1%':>8}  Verdict")
print("  " + "─" * 75)

for name, setups in STRATEGIES.items():
    if not setups: continue
    bt = best_trail.get(name, 0.5)
    for label, partial in [("Full trail", False), ("50% at 1R", True)]:
        sim  = sim_partial if partial else sim_trail
        res  = [sim(s['bars'], s['dir'], s['entry'], s['sl'], bt) for s in setups]
        s    = stats(res, setups)
        if not s: continue
        v    = verdict(s['pf'])
        tpm  = s['n'] / max(1, (setups[-1]['date']-setups[0]['date']).days/30)
        print(f"  {name:<14} {label:<13} {s['wr']:>5.1f}%  {tpm:>5.1f}  "
              f"£{s['mo']:>9,.0f}  {s['pf']:>5.2f}  £{s['dd']:>7,.0f}  {v}")
    print()

# ══════════════════════════════════════════════════════════════════════════════
# C. MONTH SEASONALITY
# ══════════════════════════════════════════════════════════════════════════════

MO_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

print(f"{'='*90}")
print("  C. MONTH SEASONALITY — PF by calendar month (red = avoid, green = strong)")
print(f"{'='*90}")
print(f"  {'Strategy':<14} " + "  ".join(f"{m[:3]}" for m in MO_NAMES))
print("  " + "─" * 75)

agg = {m: [] for m in range(1, 13)}

for name, setups in STRATEGIES.items():
    if not setups: continue
    bt = best_trail.get(name, 0.5)
    row = f"  {name:<14}"
    for m in range(1, 13):
        ms  = [s for s in setups if s['month'] == m]
        res = [sim_trail(s['bars'],s['dir'],s['entry'],s['sl'],bt) for s in ms]
        p   = pf(res) if len(ms) >= 5 else 0
        agg[m].append(p) if p > 0 else None
        sym = "✅" if p >= 1.5 else ("⚠" if p >= 1.0 else ("❌" if p > 0 else "--"))
        row += f"  {sym} "
    print(row)

# Avg row
print(f"\n  {'Avg PF':<14} " + "  ".join(
    f"{np.mean(agg[m]):.2f}" if agg[m] else " -- " for m in range(1, 13)))

weak = [MO_NAMES[m-1] for m in range(1,13) if agg[m] and np.mean(agg[m]) < 1.1]
strong_months = [MO_NAMES[m-1] for m in range(1,13) if agg[m] and np.mean(agg[m]) >= 1.5]
if weak:
    print(f"\n  ⚠️  Weak months (avg PF < 1.1): {', '.join(weak)}")
    print(f"     → Reduce risk to 0.25% in these months or skip")
if strong_months:
    print(f"  ✅ Strong months (avg PF ≥ 1.5): {', '.join(strong_months)}")
    print(f"     → Could push risk to 0.75% in these months")

# ══════════════════════════════════════════════════════════════════════════════
# D. WALK-FORWARD VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

# First and last dates tell us the actual data range
first_dates = []
for s in STRATEGIES.values():
    if s: first_dates.append(s[0]['date'])
last_dates = []
for s in STRATEGIES.values():
    if s: last_dates.append(s[-1]['date'])

data_start  = min(first_dates)
data_end    = max(last_dates)
data_mid    = data_start + (data_end - data_start) / 2

print(f"\n{'='*90}")
print(f"  D. WALK-FORWARD VALIDATION")
print(f"  Data range: {data_start.date()} → {data_end.date()}")
print(f"  In-sample:     {data_start.date()} → {data_mid.date()}")
print(f"  Out-of-sample: {data_mid.date()} → {data_end.date()}")
print(f"  An edge is real if out-of-sample PF ≥ 1.2")
print(f"{'='*90}")
print(f"  {'Strategy':<14}  {'IS PF':>7}  {'IS trades':>9}  "
      f"{'OOS PF':>7}  {'OOS trades':>10}  {'Verdict':>12}")
print("  " + "─" * 65)

for name, setups in STRATEGIES.items():
    if not setups: continue
    bt    = best_trail.get(name, 0.5)
    is_s  = [s for s in setups if s['date'] <  data_mid]
    oos_s = [s for s in setups if s['date'] >= data_mid]

    is_r  = [sim_trail(s['bars'],s['dir'],s['entry'],s['sl'],bt) for s in is_s]
    oos_r = [sim_trail(s['bars'],s['dir'],s['entry'],s['sl'],bt) for s in oos_s]

    pf_is  = pf(is_r)
    pf_oos = pf(oos_r)

    if pf_is == 0 or pf_oos == 0:
        print(f"  {name:<14}  {'n/a':>7}  {'n/a':>9}  {'n/a':>7}  {'n/a':>10}")
        continue

    delta = pf_oos - pf_is
    sign  = "+" if delta >= 0 else ""
    hold  = "✅ REAL EDGE" if pf_oos>=1.3 else ("⚠️  WEAK" if pf_oos>=1.0 else "❌ OVERFIT")
    print(f"  {name:<14}  {pf_is:>7.2f}  {len(is_r):>9}  "
          f"{pf_oos:>7.2f}  {len(oos_r):>10}  {hold}  ({sign}{delta:.2f})")

# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════

print(f"\n{'='*90}")
print("  SUMMARY OF CHANGES TO MAKE")
print(f"{'='*90}")
print()

# Best trail vs current (0.5)
changes = [(n, best_trail[n]) for n in best_trail if abs(best_trail[n]-0.5)>0.09]
if changes:
    print("  Trail adjustments (currently all 0.5R):")
    for n, t in sorted(changes, key=lambda x: x[1]):
        direction = "tighter ↓" if t < 0.5 else "wider ↑"
        print(f"    {n:<14} → {t}R  ({direction})")
else:
    print("  Trail: 0.5R is already optimal or near-optimal for all strategies ✅")
print()
print("  Full results above show optimal trail, partial TP comparison,")
print("  months to avoid, and walk-forward validation.")
print()
