"""
research_time_series_momentum.py

HYPOTHESIS 6: Time-Series Momentum (multi-week trend persistence).

WHY THIS IS A DIFFERENT HUNTING GROUND
-----------------------------------------
Every hypothesis tested so far (1-5) shares a trait: a single M1/H1 bar
triggers a same-day directional bet, held for minutes to a few hours.
All five failed. Rather than trying a sixth variation on that same
theme, this tests a structurally different mechanism at a completely
different horizon: multi-week trend persistence, entered on weekly
signals and held for weeks, with M1 data used only for realistic
execution (fills, stops), not for signal generation.

MARKET LOGIC
------------
This is NOT an invented pattern — it's testing "time-series momentum,"
one of the most extensively replicated findings in the academic asset
pricing literature (Moskowitz, Ooi & Pedersen 2012, and a large body of
subsequent work): assets that have trended over the past several months
tend to continue trending over the following 1-3 months, across nearly
every major asset class (equities, currencies, commodities, bonds).
The proposed mechanism is initial underreaction to new information,
amplified by trend-following/momentum-chasing flows over weeks to
months, eventually overshooting and reversing over much longer (12+
month) horizons — a completely different mechanism from any
microstructure/liquidity story tested in hypotheses 1-5.

Using an academically pre-established, multi-decade, multi-asset-class
anomaly as the starting point (rather than another intraday pattern
invented from scratch) directly addresses "avoid data mining" — this
isn't discovered by searching this dataset, it's a documented
regularity we're checking still holds on FTMO's specific instruments
and cost structure.

SIGNAL DEFINITION
------------------
1. Weekly bars (resampled from M1).
2. Trailing K-week return (K in LOOKBACK_WEEKS_GRID). Direction = sign
   of that return.
3. Only trade if the trailing return's magnitude clears MOM_PCTL of its
   own rolling 52-week absolute-value distribution (genuine momentum,
   not noise) — same percentile-threshold convention used in
   hypotheses 3-5, avoids an arbitrary fixed cutoff.
4. Entry = first M1 bar of the week AFTER the signal week (signal uses
   data up to week t's close, executed at week t+1's open — no
   look-ahead).
5. Stop = ATR_MULT_STOP x rolling 10-week average weekly true range.
6. Exit = fixed R target (TP_GRID — deliberately large, 3R-8R, matching
   real trend-following practice of cutting losses fast and letting
   winners run) OR TIME_STOP_WEEKS calendar weeks, whichever first.
7. One signal per instrument per week.

EXECUTION MODEL SIMPLIFICATION (stated explicitly, not hidden): the
exit scan uses H1 bars, not M1, for the coarse pass. Holding periods
here are weeks and stops are many ATRs wide, so M1-level precision
matters far less than it did for hypotheses 1-5's minute-scale trades,
and H1 keeps a multi-week x 9-instrument backtest computationally
tractable. If this hypothesis clears the accept bar, the full
validation pipeline must re-verify at M1 resolution before trusting
the exact numbers, particularly the exit price near the stop.

Full 9-instrument universe — momentum is documented across every asset
class here, no structural exclusion like hypothesis 2's auction-only
restriction.

COSTS: same round-trip price cost / actual stop distance convention as
the other research scripts.

Run in Codespaces (needs *_M1_ftmo.csv):
    python -u research_time_series_momentum.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
LOOKBACK_WEEKS_GRID = [4, 8, 12]
MOM_PCTL_GRID       = [0.50, 0.70]
ATR_MULT_STOP       = 2.0
TIME_STOP_WEEKS     = 4
TP_GRID             = [3.0, 5.0, 8.0]
MIN_SL_COST_MULT    = 3.0

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

_m1, _h1, _weekly = {}, {}, {}


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
    df['time'] = pd.to_datetime(ts, unit='s', utc=True) if ts.notna().mean() > 0.99 \
        else pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    _m1[k] = df

    h1 = df.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    _h1[k] = h1

    wk = df.resample('W').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    wk = wk[wk['open'] > 0]
    tr = np.maximum(wk['high'] - wk['low'],
         np.maximum((wk['high'] - wk['close'].shift()).abs(), (wk['low'] - wk['close'].shift()).abs()))
    wk['atr10'] = tr.rolling(10).mean()
    _weekly[k] = wk
    return True


def build_signals(k, lookback_weeks, mom_pctl):
    wk = _weekly[k]
    ret = wk['close'].pct_change(lookback_weeks)
    abs_ret = ret.abs()
    thresh = abs_ret.rolling(52).quantile(mom_pctl)
    valid = abs_ret > thresh
    direction = np.sign(ret)
    return wk.index[valid.fillna(False) & (direction != 0)], direction[valid.fillna(False) & (direction != 0)], wk


def simulate_h1(k, entry_idx_h1, direction, entry, stop, tp_r, deadline):
    h1 = _h1[k]
    sl_dist = abs(entry - stop)
    if sl_dist <= 0:
        return None
    tp = entry + sl_dist * tp_r if direction == 1 else entry - sl_dist * tp_r
    hi = h1['high'].values; lo = h1['low'].values; cl = h1['close'].values
    idx = h1.index
    end = entry_idx_h1
    for j in range(entry_idx_h1, len(h1)):
        if idx[j] > deadline:
            end = j
            break
        if direction == 1:
            if lo[j] <= stop: return -1.0, sl_dist
            if hi[j] >= tp:   return tp_r, sl_dist
        else:
            if hi[j] >= stop: return -1.0, sl_dist
            if lo[j] <= tp:   return tp_r, sl_dist
        end = j
    if end <= entry_idx_h1:
        return None
    r = (cl[end]-entry)/sl_dist if direction == 1 else (entry-cl[end])/sl_dist
    return r, sl_dist


def detect_and_simulate(k, lookback_weeks, mom_pctl, tp_r):
    m1 = _m1[k]; h1 = _h1[k]; wk = _weekly[k]
    sig_times, sig_dirs, wk_full = build_signals(k, lookback_weeks, mom_pctl)
    trades = []
    h1_idx = h1.index

    for ts, d in zip(sig_times, sig_dirs):
        d = int(d)
        row = wk_full.loc[ts]
        atr = row['atr10']
        if pd.isna(atr) or atr <= 0:
            continue
        # entry = first M1 bar strictly after this week's close (next week's open)
        m1_after = m1[m1.index > ts]
        if len(m1_after) == 0:
            continue
        entry_time = m1_after.index[0]
        entry = float(m1_after.iloc[0]['open'])
        stop = entry - atr * ATR_MULT_STOP if d == 1 else entry + atr * ATR_MULT_STOP
        sl_dist = abs(entry - stop)
        cost_price_i = COST_PRICE[k] * SLIPPAGE_MULT.get(k, 1.0)
        if sl_dist < cost_price_i * MIN_SL_COST_MULT:
            continue

        h1_pos = h1_idx.searchsorted(entry_time, side='left')
        if h1_pos >= len(h1_idx):
            continue
        deadline = entry_time + pd.Timedelta(weeks=TIME_STOP_WEEKS)

        res = simulate_h1(k, h1_pos, d, entry, stop, tp_r, deadline)
        if res is None:
            continue
        r_gross, sld = res
        cost_r = cost_price_i / sld
        trades.append({'instrument': k, 'time': entry_time, 'r_net': r_gross - cost_r})
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
    print(f'  {k}: {_m1[k].index[0].date()} -> {_m1[k].index[-1].date()}  ({len(_weekly[k]):,} weekly bars)')

# ── Coarse pass ───────────────────────────────────────────────────────────────
print(f'\n{"="*78}\n  HYPOTHESIS 6 - TIME-SERIES MOMENTUM (weekly signal, H1 execution)\n{"="*78}')

for lb in LOOKBACK_WEEKS_GRID:
    for pctl in MOM_PCTL_GRID:
        for tp_r in TP_GRID:
            print(f'\n=== lookback={lb}wk, mom_pctl>={pctl}, TP={tp_r}R ===')
            all_oos = []
            for k in loaded:
                trades = detect_and_simulate(k, lb, pctl, tp_r)
                oos_r = [t['r_net'] for t in trades if str(t['time'].date()) >= IS_OOS_SPLIT]
                all_oos += oos_r
                print(fmt(f'{k} OOS', stats(oos_r)))
            print(fmt('ALL INSTRUMENTS OOS', stats(all_oos)))

print(f'\n{"="*78}')
print('Coarse pass done. Decision rule (frozen before running):')
print('  ACCEPT for full validation pipeline only if OOS combined PF > 1.3 for')
print('  at least one (lookback, mom_pctl, TP) combination, part of a plateau')
print('  across neighbouring cells (not an isolated spike in an 18-cell grid),')
print('  AND >=6/9 instruments individually OOS-profitable at that combination.')
print('  If accepted: full validation MUST re-verify exit prices at M1')
print('  resolution before trusting the exact numbers (see execution model')
print('  simplification note in the docstring).')
print('  Otherwise: discard, do not cherry-pick the best cell.')
print(f'{"="*78}')
