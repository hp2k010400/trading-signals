"""
research_compression_trend.py

HYPOTHESIS 3: Extreme Compression + Trend-Aligned Breakout.

MARKET LOGIC
------------
Volatility clustering — low-volatility periods tend to be followed by
higher-volatility periods — is one of the most robust stylized facts in
finance (Mandelbrot 1963, the entire GARCH literature). This is not in
dispute. What IS in dispute, and what killed M1GOATV2's IB/Pin Bar
signal, is direction: compression tells you a bigger move is coming, it
does NOT tell you which way. IB traded any breakout direction
indiscriminately (long or short, whichever way price broke) and that
was empirically shown to be a coin flip (PF 0.82 true).

This hypothesis is deliberately NOT a repeat of that mistake. Two
changes, both structurally motivated, not just "add a filter until it
works":

1. ONLY take the breakout when it aligns with the prevailing higher-
   timeframe (H4) trend. Mechanism: trend-following institutional flow
   that paused during the low-volatility consolidation resumes in the
   SAME direction once volatility returns — this is "trend continuation
   after compression," a distinct behavior from "breakout, direction
   unknown." Counter-trend breakouts are skipped entirely, not traded
   and hoped to net out.

2. Compression must be GENUINE tail-event compression — bottom
   COMPRESSION_PCTL of the trailing range/ATR distribution — not just
   "smaller than the immediately preceding bar" (IB's definition, which
   fires on a large fraction of all bars and is barely a filter at all).

H4 EMA is used only to DEFINE trend direction/context (above/below =
up/down), not as an entry trigger or crossover signal — there's no
EMA-crossover timing bet here, just a coarse regime classifier, which
is a defensible, non-retail-indicator use.

FALSIFIABLE PREDICTION: if this is real, genuine compression + trend
alignment should show a meaningfully better win rate / PF than the
already-disproven "any IB breakout" baseline (WR ~49.6% at 1R, PF
capping at 0.82). If it doesn't clear that bar convincingly, discard —
volatility clustering being real doesn't mean this particular way of
monetizing it works.

SIGNAL DEFINITION
------------------
1. H1 bars. Compute range/ATR14 ratio per bar.
2. "Extreme compression" = ratio below the COMPRESSION_PCTL percentile
   of the trailing 200-bar distribution of that ratio.
3. Trend context = H4 close vs H4 EMA(20): above = uptrend context
   (only long breakouts eligible), below = downtrend (only short).
4. Entry = break of the compressed bar's high (uptrend context) or low
   (downtrend context), confirmed on M1 within the next WIN_HOURS.
5. Stop = opposite side of the compressed bar.
6. Exit = fixed R target (TP_GRID) or MAX_BARS time stop (8h — trend
   continuation plays out slower than a liquidity-sweep snap-back).
7. One signal per instrument per H1 bar; max MAX_PER_DAY per day.

COSTS: same convention as the other two research scripts — round-trip
price cost / actual stop distance, not a flat R deduction.

Run in Codespaces (needs *_M1_ftmo.csv):
    python -u research_compression_trend.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
COMPRESSION_LOOKBACK = 200      # bars for the rolling range/ATR percentile
COMPRESSION_PCTL_GRID = [0.10, 0.20, 0.30]   # tested, not cherry-picked after the fact
WIN_HOURS   = 6
MAX_BARS    = 480               # 8h time stop
MAX_PER_DAY = 3
TP_GRID     = [1.5, 2.0, 3.0]

FILES = {
    'DAX':    'GER40_M1_ftmo.csv',
    'NAS100': 'US100_M1_ftmo.csv',
    'SP500':  'US500_M1_ftmo.csv',
    'US30':   'US30_M1_ftmo.csv',
    'EURUSD': 'EURUSD_M1_ftmo.csv',
    'GBPUSD': 'GBPUSD_M1_ftmo.csv',
    'USDJPY': 'USDJPY_M1_ftmo.csv',
    'GOLD':   'XAUUSD_M1_ftmo.csv',
    'NATGAS': 'NATGAS_M1_ftmo.csv',
}

COST_PRICE = {
    'DAX': 2.0, 'NAS100': 2.0, 'SP500': 0.8, 'US30': 4.0,
    'EURUSD': 0.00020, 'GBPUSD': 0.00026, 'USDJPY': 0.026,
    'GOLD': 0.50, 'NATGAS': 0.010,
}
SLIPPAGE_MULT = {'NATGAS': 3.0}

IS_OOS_SPLIT = '2024-01-01'

_m1, _h1, _h4 = {}, {}, {}


def load(k):
    fn = FILES[k]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    cols = {c.lower(): c for c in df.columns}
    need = ['time', 'open', 'high', 'low', 'close']
    if not all(c in cols for c in need):
        print(f'  {k}: UNEXPECTED SCHEMA {list(df.columns)} — skipping, needs mapping')
        return False
    df = df.rename(columns={cols[c]: c for c in need})
    ts = pd.to_numeric(df['time'], errors='coerce')
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
    h1 = h1[h1['open'] > 0]
    tr = np.maximum(h1['high'] - h1['low'],
         np.maximum((h1['high'] - h1['close'].shift()).abs(), (h1['low'] - h1['close'].shift()).abs()))
    h1['atr14'] = tr.rolling(14).mean()
    h1['range'] = h1['high'] - h1['low']
    h1['range_atr'] = h1['range'] / h1['atr14']
    h1['pctl'] = h1['range_atr'].rolling(COMPRESSION_LOOKBACK).apply(
        lambda s: (s.iloc[:-1] < s.iloc[-1]).mean() if len(s) > 1 else np.nan, raw=False)
    _h1[k] = h1

    h4 = df.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    h4['ema20'] = h4['close'].ewm(span=20, adjust=False).mean()
    _h4[k] = h4
    return True


def h4_trend_at(k, ts):
    h4 = _h4[k]
    idx = h4.index.searchsorted(ts, side='right') - 1
    if idx < 1 or idx >= len(h4):
        return 0
    row = h4.iloc[idx]
    if pd.isna(row['ema20']):
        return 0
    return 1 if row['close'] > row['ema20'] else -1


def vsim(k, m1, ep, d, entry, sl, tp_r):
    sl_d = abs(entry - sl)
    if sl_d <= 0:
        return None
    end = min(ep + 1 + MAX_BARS, len(m1))
    slc = m1.iloc[ep+1:end]
    if len(slc) == 0:
        return None
    hi = slc['high'].values; lo = slc['low'].values; cl = slc['close'].values
    tp = entry + sl_d * tp_r if d == 1 else entry - sl_d * tp_r
    for i in range(len(hi)):
        if d == 1:
            if hi[i] >= tp: return tp_r, sl_d
            if lo[i] <= sl: return -1.0, sl_d
        else:
            if lo[i] <= tp: return tp_r, sl_d
            if hi[i] >= sl: return -1.0, sl_d
    r = (cl[-1]-entry)/sl_d if d == 1 else (entry-cl[-1])/sl_d
    return r, sl_d


def detect_and_simulate(k, tp_r, compression_pctl):
    m1 = _m1[k]; h1 = _h1[k]; mi = m1.index
    hl = list(h1.index)
    day_count = {}
    trades = []

    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek >= 5:
            continue
        row = h1.iloc[i]
        if pd.isna(row['pctl']) or row['pctl'] > compression_pctl:
            continue  # not extreme compression

        trend = h4_trend_at(k, ts)
        if trend == 0:
            continue

        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PER_DAY:
            continue

        bar_h = float(row['high']); bar_l = float(row['low'])
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0:
            continue

        taken = False; d = 0; e = 0.0; sl = 0.0; j = 0
        for jj in range(len(window)):
            b = window.iloc[jj]
            if trend == 1 and b['high'] > bar_h:
                d = 1; e = bar_h; sl = bar_l; j = jj; taken = True; break
            elif trend == -1 and b['low'] < bar_l:
                d = -1; e = bar_l; sl = bar_h; j = jj; taken = True; break

        if not taken:
            continue
        ep = mi.searchsorted(window.index[j])
        if ep >= len(m1):
            continue

        res = vsim(k, m1, ep, d, e, sl, tp_r)
        if res is None:
            continue
        r_gross, sld = res
        cost_price = COST_PRICE[k] * SLIPPAGE_MULT.get(k, 1.0)
        cost_r = cost_price / sld if sld > 0 else 0.0
        day_count[date_k] = day_count.get(date_k, 0) + 1
        trades.append({'instrument': k, 'time': window.index[j], 'r_net': r_gross - cost_r})
    return trades


def stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0, total_r=0.0)
    w = r[r > 0]; l = r[r <= 0]
    pf = round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else float('inf')
    return dict(n=len(r), wr=round(len(w)/len(r)*100, 1), pf=pf,
                exp=round(r.mean(), 3), total_r=round(r.sum(), 1))


def fmt(label, s, width=24):
    return (f'  {label:<{width}}  N={s["n"]:>5}  WR={s["wr"]:>5.1f}%  '
            f'PF={s["pf"]:>6.2f}  Exp(R)={s["exp"]:>+6.3f}  TotalR={s["total_r"]:>+9.1f}')


# ── Load ─────────────────────────────────────────────────────────────────────
print('Loading FTMO M1 data...')
loaded = [k for k in FILES if load(k)]
missing = [k for k in FILES if k not in loaded]
print(f'Loaded {len(loaded)}/9: {loaded}')
if missing:
    print(f'MISSING or unreadable *_M1_ftmo.csv: {missing}')
for k in loaded:
    print(f'  {k}: {_m1[k].index[0].date()} -> {_m1[k].index[-1].date()}  ({len(_m1[k]):,} bars)')

# ── Coarse pass ───────────────────────────────────────────────────────────────
print(f'\n{"="*78}\n  HYPOTHESIS 3 - EXTREME COMPRESSION + TREND-ALIGNED BREAKOUT\n{"="*78}')

for pctl in COMPRESSION_PCTL_GRID:
    for tp_r in TP_GRID:
        print(f'\n=== compression <= {int(pctl*100)}th pctl, TP = {tp_r}R ===')
        all_is, all_oos = [], []
        for k in loaded:
            trades = detect_and_simulate(k, tp_r, pctl)
            is_r  = [t['r_net'] for t in trades if str(t['time'].date()) < IS_OOS_SPLIT]
            oos_r = [t['r_net'] for t in trades if str(t['time'].date()) >= IS_OOS_SPLIT]
            all_is += is_r; all_oos += oos_r
            print(fmt(f'{k} OOS', stats(oos_r)))
        print(fmt('ALL INSTRUMENTS OOS', stats(all_oos)))

print(f'\n{"="*78}')
print('Coarse pass done. Decision rule (frozen before running):')
print('  ACCEPT for full validation pipeline only if OOS combined PF > 1.3 for')
print('  at least one (pctl, TP) combination AND that result is not an isolated')
print('  spike -- neighbouring pctl/TP cells should also be meaningfully above 1.0')
print('  (a plateau, not a single lucky cell in an 27-cell grid) AND >=6/9')
print('  instruments individually OOS-profitable at that combination.')
print('  Otherwise: discard, do not cherry-pick the best cell.')
print(f'{"="*78}')
