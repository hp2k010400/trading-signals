"""
research_opening_momentum.py

HYPOTHESIS 2: Post-Open Imbalance Continuation.

MARKET LOGIC
------------
Cash equity index markets (NYSE, Xetra) open via a centralized auction,
not continuous double-sided trading. Overnight order flow, news, and
futures positioning all get concentrated into a single auction match at
the open. Large imbalance orders frequently cannot be fully filled in
the auction itself and spill over into the first few minutes of
continuous trading as the market works off that residual imbalance.
That spillover produces short-horizon directional momentum immediately
after the open, which decays as the imbalance gets absorbed.

This is deliberately NOT the same claim as:
  - IB/Pin Bar compression->breakout (proven dead, PF 0.82 true).
  - Hours-long opening-range-breakout, already tested on this account
    (NAS_ORB/SP5_ORB/DAX_ORB capped ~PF 1.4-1.5 — mediocre, not this).
This is specifically about the FIRST 1-2 MINUTES' direction predicting
the NEXT FEW MINUTES, driven by auction-imbalance absorption, not chart
geometry, with a short time horizon (this is a fast-decaying
microstructure effect, not an intraday swing).

WHY ONLY 4 INSTRUMENTS
-----------------------
The mechanism requires a real centralized opening auction. DAX
(Xetra), NAS100/SP500/US30 (NYSE) all have one. EURUSD/GBPUSD/USDJPY/
GOLD/NATGAS trade continuously with no auction — applying this same
logic there would be forcing a mechanism onto a market structure where
it doesn't exist, which is exactly the kind of "multi-asset robustness"
that's actually just noise. They're excluded here on structural
grounds, not cherry-picked after seeing results.

HONEST TREATMENT OF THE "9:28am" CLAIM
----------------------------------------
Rather than hard-coding a specific entry minute because someone claimed
it works, ENTRY_OFFSETS sweeps -2..+2 minutes around each market's
actual local open. If a specific offset is meaningfully better than its
neighbours, that's suspicious (curve fit to noise) — a real effect
should look like a plateau centered near 0, not a spike at some
specific minute. This is the parameter-sensitivity check applied to the
claim itself, not just to my own idea.

SIGNAL DEFINITION
------------------
1. Session open = first M1 bar at/after the exchange's local open time,
   shifted by ENTRY_OFFSET minutes (tested -2..+2).
2. Direction = sign(close - open) of that bar, only if the move clears
   MIN_MOVE_ATR (fraction of H1 ATR14) — filters pure noise bars.
3. Entry = close of that bar, in the direction of the move.
4. Stop = that bar's opposite extreme (low if long, high if short)
   with a small ATR buffer.
5. Exit = fixed R target (TP_GRID) or TIME_STOP_BARS (short — this is a
   fast-decaying effect, not a multi-hour trade).
6. One signal per instrument per day.

COSTS: same approach as research_liquidity_sweep.py — round-trip price
cost converted to R using each trade's actual stop distance, not a flat
R deduction.

Run in Codespaces (needs *_M1_ftmo.csv):
    python -u research_opening_momentum.py
"""
import pandas as pd
import numpy as np
import os, warnings
from zoneinfo import ZoneInfo
warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
MIN_MOVE_ATR   = 0.05       # opening bar move must clear 5% of H1 ATR14 to count
ATR_BUFFER     = 0.10
TIME_STOP_BARS = 30         # 30 minutes — short horizon, fast-decaying effect
TP_GRID        = [1.0, 1.5, 2.0]
ENTRY_OFFSETS  = [-2, -1, 0, 1, 2]   # minutes around local open; sweeps the "9:28" claim honestly

# instrument -> (data file, exchange tz, local open time "HH:MM")
INSTRUMENTS = {
    'DAX':    ('GER40_M1_ftmo.csv', 'Europe/Berlin',    '09:00'),
    'NAS100': ('US100_M1_ftmo.csv', 'America/New_York', '09:30'),
    'SP500':  ('US500_M1_ftmo.csv', 'America/New_York', '09:30'),
    'US30':   ('US30_M1_ftmo.csv',  'America/New_York', '09:30'),
}

COST_PRICE = {'DAX': 2.0, 'NAS100': 2.0, 'SP500': 0.8, 'US30': 4.0}

IS_OOS_SPLIT = '2024-01-01'

_m1, _h1atr = {}, {}


def load(k, fn):
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    # schema check — FTMO MT5 exports may not match the OANDA CSV layout exactly
    cols = {c.lower(): c for c in df.columns}
    if 'time' not in cols or 'open' not in cols or 'high' not in cols or 'low' not in cols or 'close' not in cols:
        print(f'  {k}: UNEXPECTED SCHEMA {list(df.columns)} — skipping, needs mapping')
        return False
    df = df.rename(columns={cols['time']: 'time', cols['open']: 'open', cols['high']: 'high',
                             cols['low']: 'low', cols['close']: 'close'})
    ts = pd.to_numeric(df['time'], errors='coerce')
    # handle either unix seconds or an already-parseable datetime string
    if ts.notna().mean() > 0.99:
        df['time'] = pd.to_datetime(ts, unit='s', utc=True)
    else:
        df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    _m1[k] = df

    h1 = df.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    tr = np.maximum(h1['high'] - h1['low'],
         np.maximum((h1['high'] - h1['close'].shift()).abs(), (h1['low'] - h1['close'].shift()).abs()))
    h1['atr14'] = tr.rolling(14).mean()
    _h1atr[k] = h1['atr14']
    return True


def atr_at(k, ts):
    s = _h1atr[k]
    idx = s.index.searchsorted(ts, side='right') - 1
    if idx < 0 or idx >= len(s) or pd.isna(s.iloc[idx]):
        return None
    return float(s.iloc[idx])


def simulate(hi, lo, cl, start_i, direction, entry, stop, tp_r):
    sl_dist = abs(entry - stop)
    if sl_dist <= 0:
        return None
    tp = entry + sl_dist * tp_r if direction == 1 else entry - sl_dist * tp_r
    end = min(start_i + TIME_STOP_BARS, len(hi))
    if start_i >= end:
        return None
    for i in range(start_i, end):
        if direction == 1:
            if lo[i] <= stop: return -1.0, sl_dist
            if hi[i] >= tp:   return tp_r, sl_dist
        else:
            if hi[i] >= stop: return -1.0, sl_dist
            if lo[i] <= tp:   return tp_r, sl_dist
    r = (cl[end-1] - entry) / sl_dist if direction == 1 else (entry - cl[end-1]) / sl_dist
    return r, sl_dist


def detect_and_simulate(k, tp_r, offset_min, tz_name, open_hhmm):
    m1 = _m1[k]
    tz = ZoneInfo(tz_name)
    local_idx = m1.index.tz_convert(tz)
    oh, om = map(int, open_hhmm.split(':'))
    target_min = (oh * 60 + om + offset_min) % (24 * 60)
    t_h, t_m = divmod(target_min, 60)

    mask = (local_idx.hour == t_h) & (local_idx.minute == t_m) & (local_idx.dayofweek < 5)
    open_positions = np.where(mask)[0]

    hi = m1['high'].values; lo = m1['low'].values; cl = m1['close'].values; op = m1['open'].values
    idx = m1.index
    trades = []

    for i in open_positions:
        buf = atr_at(k, idx[i])
        if buf is None:
            continue
        move = cl[i] - op[i]
        if abs(move) < MIN_MOVE_ATR * buf:
            continue
        direction = 1 if move > 0 else -1
        entry = cl[i]
        stop = (lo[i] - buf * ATR_BUFFER) if direction == 1 else (hi[i] + buf * ATR_BUFFER)
        res = simulate(hi, lo, cl, i + 1, direction, entry, stop, tp_r)
        if res is None:
            continue
        r_gross, sld = res
        cost_r = COST_PRICE[k] / sld if sld > 0 else 0.0
        trades.append({'instrument': k, 'time': idx[i], 'r_net': r_gross - cost_r})
    return trades


def stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0, total_r=0.0)
    w = r[r > 0]; l = r[r <= 0]
    pf = round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else float('inf')
    return dict(n=len(r), wr=round(len(w)/len(r)*100, 1), pf=pf,
                exp=round(r.mean(), 3), total_r=round(r.sum(), 1))


def fmt(label, s, width=26):
    return (f'  {label:<{width}}  N={s["n"]:>5}  WR={s["wr"]:>5.1f}%  '
            f'PF={s["pf"]:>6.2f}  Exp(R)={s["exp"]:>+6.3f}  TotalR={s["total_r"]:>+9.1f}')


# ── Load ─────────────────────────────────────────────────────────────────────
print('Loading FTMO M1 data...')
loaded = [k for k, (fn, tz, ot) in INSTRUMENTS.items() if load(k, fn)]
missing = [k for k in INSTRUMENTS if k not in loaded]
print(f'Loaded {len(loaded)}/4: {loaded}')
if missing:
    print(f'MISSING/unreadable: {missing}')
for k in loaded:
    print(f'  {k}: {_m1[k].index[0].date()} -> {_m1[k].index[-1].date()}  ({len(_m1[k]):,} bars)')

# ── Coarse pass: TP grid x entry-offset grid, IS/OOS split ─────────────────
print(f'\n{"="*78}\n  HYPOTHESIS 2 - POST-OPEN IMBALANCE CONTINUATION - COARSE PASS\n{"="*78}')

for tp_r in TP_GRID:
    print(f'\n=== TP = {tp_r}R ===')
    for offset in ENTRY_OFFSETS:
        print(f'\n--- entry offset {offset:+d} min ---')
        all_is, all_oos = [], []
        for k in loaded:
            fn, tz, ot = INSTRUMENTS[k]
            trades = detect_and_simulate(k, tp_r, offset, tz, ot)
            is_r  = [t['r_net'] for t in trades if str(t['time'].date()) < IS_OOS_SPLIT]
            oos_r = [t['r_net'] for t in trades if str(t['time'].date()) >= IS_OOS_SPLIT]
            all_is += is_r; all_oos += oos_r
            print(fmt(f'{k} OOS', stats(oos_r)))
        print(fmt('ALL INSTRUMENTS OOS', stats(all_oos)))

print(f'\n{"="*78}')
print('Coarse pass done. Decision rule (frozen before running):')
print('  ACCEPT for full validation pipeline only if OOS combined PF > 1.3 at')
print('  offset=0 AND the offset sweep shows a plateau (neighbouring offsets')
print('  within ~15% of the PF at 0), not an isolated spike at one minute.')
print('  AND >=3/4 instruments individually OOS-profitable at offset=0.')
print('  Otherwise: discard, do not cherry-pick the best-looking offset.')
print(f'{"="*78}')
