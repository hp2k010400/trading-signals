"""
research_liquidity_sweep.py

HYPOTHESIS 1 (post-M1GOATV2-bug reset): Liquidity Sweep Reversal at the
prior day's high/low.

MARKET LOGIC
------------
Retail stop-losses and breakout entry orders cluster just beyond obvious
reference levels — the prior day's high and low are the most-watched
levels on any chart. Market makers and larger participants have a
standing incentive to push price through that liquidity, fill size
against the resting stop/breakout orders, and then let price revert once
there is no genuine follow-through demand/supply behind the move.

This is structurally different from the IB/Pin-Bar signal that killed
M1GOATV2 v2.07 (PF 0.82 confirmed 2026-08-01). That signal traded ANY
breakout of a compression range indiscriminately, long or short, with no
directional context — it was betting breakouts continue, which is the
crowded, arbitraged side of the trade. This hypothesis bets the opposite:
that a breakout beyond a well-known level FAILS and reverts, which is a
narrower, more specific claim with a real economic mechanism behind it
(stop-hunt / liquidity-grab, not "compression precedes expansion").

Falsifiable prediction: if this is real, price that pierces the prior
day's high/low and closes back inside within a few minutes should show a
positive-expectancy reversion toward the opposite side of the range,
appreciably better than a coin flip, and this should hold across
unrelated asset classes (FX, indices, metals, energy) since the
mechanism (clustered stops at an obvious level) is not asset-specific.

If this fails on a coarse multi-asset backtest, discard it — do not
tune parameters to rescue it. See PARAMETER GRID at bottom for the one
round of coarse sensitivity checking done before accepting/rejecting.

SIGNAL DEFINITION
------------------
1. Reference level = previous UTC calendar day's high (PDH) and low (PDL).
2. Only scanned during the liquid window 07:00-17:00 UTC (London+NY
   overlap) — avoids thin overnight liquidity where "sweeps" are just
   noise, not real stop-hunts.
3. Sweep = an M1 bar's high > PDH (or low < PDL).
4. Confirmation = within CONFIRM_BARS minutes of the sweep bar, an M1
   bar closes back on the correct side of the level (below PDH for a
   failed high-sweep, above PDL for a failed low-sweep). If confirmation
   doesn't happen within the window, the signal is void — that's not a
   sweep, that's a genuine breakout continuing, and we are not trading
   that (already proven to have no edge).
5. Entry = close of the confirmation bar, in the reversal direction.
6. Stop = the sweep extreme (highest high / lowest low reached during
   the sweep attempt) + a volatility buffer (0.1x H1 ATR14) so normal
   noise doesn't stop us out immediately.
7. Exit = fixed R target (tested 1.5R/2R/3R) OR time stop (240 M1 bars
   = 4h — sweeps that haven't resolved in 4h have lost their edge as an
   intraday liquidity-grab trade).
8. Only ONE signal per instrument per day per side (first sweep only) —
   avoids re-counting the same stop-hunt as multiple correlated trades.

COSTS
-----
Modeled as round-trip price cost (spread + slippage + commission-in-
price-equivalent), converted to an R-cost by dividing by each trade's
ACTUAL stop distance (not a flat R deduction like the old codebase used
— that under/over-charges trades with unusually tight/wide stops). NATGAS
gets an extra slippage multiplier: it's known to gap through stops (see
memory: NG_ORB removed from 6botV2/11botV3 after -£790/-£817 slippage
events), so a coarse backtest that assumes clean fills there would be
dishonest.

Run in Codespaces (needs the full *_M1_oanda.csv files):
    python -u research_liquidity_sweep.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
SESSION_START_UTC = 7
SESSION_END_UTC    = 17
CONFIRM_BARS  = 10          # minutes allowed for the sweep to fail back
ATR_BUFFER    = 0.10        # stop buffer = 10% of H1 ATR14
TIME_STOP_BARS = 240        # 4h time stop
TP_GRID       = [1.5, 2.0, 3.0]

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

# Round-trip execution cost in PRICE units: spread + slippage + commission-equiv.
# Rough institutional/FTMO-broker assumptions — refine with real spread logs
# before trusting the absolute PF, but fine for a first accept/reject pass.
COST_PRICE = {
    'DAX':    2.0,
    'NAS100': 2.0,
    'SP500':  0.8,
    'US30':   4.0,
    'EURUSD': 0.00020,
    'GBPUSD': 0.00026,
    'USDJPY': 0.026,
    'GOLD':   0.50,
    'NATGAS': 0.010,
}
SLIPPAGE_MULT = {  # extra multiplier on cost for illiquid/gappy instruments
    'NATGAS': 3.0,
}

IS_OOS_SPLIT = '2024-01-01'   # IS = 2018-2023, OOS = 2024-2026, frozen before any tuning

_m1, _h1atr = {}, {}


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
    tr = np.maximum(h1['high'] - h1['low'],
         np.maximum((h1['high'] - h1['close'].shift()).abs(), (h1['low'] - h1['close'].shift()).abs()))
    h1['atr14'] = tr.rolling(14).mean()
    _h1atr[k] = h1['atr14']
    return True


def prior_day_levels(m1):
    daily = m1.resample('1D').agg({'high': 'max', 'low': 'min'}).dropna()
    daily['pdh'] = daily['high'].shift(1)
    daily['pdl'] = daily['low'].shift(1)
    return daily[['pdh', 'pdl']].dropna()


def atr_at(k, ts):
    s = _h1atr[k]
    idx = s.index.searchsorted(ts, side='right') - 1
    if idx < 0 or idx >= len(s) or pd.isna(s.iloc[idx]):
        return None
    return float(s.iloc[idx])


def simulate(m1_high, m1_low, m1_close, start_i, direction, entry, stop, tp_r):
    sl_dist = abs(entry - stop)
    if sl_dist <= 0:
        return None
    tp = entry + sl_dist * tp_r if direction == 1 else entry - sl_dist * tp_r
    end = min(start_i + TIME_STOP_BARS, len(m1_high))
    for i in range(start_i, end):
        if direction == 1:
            if m1_low[i] <= stop:
                return -1.0, i - start_i + 1, sl_dist
            if m1_high[i] >= tp:
                return tp_r, i - start_i + 1, sl_dist
        else:
            if m1_high[i] >= stop:
                return -1.0, i - start_i + 1, sl_dist
            if m1_low[i] <= tp:
                return tp_r, i - start_i + 1, sl_dist
    r = (m1_close[end - 1] - entry) / sl_dist if direction == 1 else (entry - m1_close[end - 1]) / sl_dist
    return r, end - start_i, sl_dist


def detect_and_simulate(k, tp_r):
    m1 = _m1[k]
    levels = prior_day_levels(m1)
    hi = m1['high'].values; lo = m1['low'].values; cl = m1['close'].values
    idx = m1.index
    day_of = idx.normalize()

    trades = []
    swept_today = {}  # date -> set of sides already used

    n = len(m1)
    for i in range(n):
        ts = idx[i]
        if not (SESSION_START_UTC <= ts.hour < SESSION_END_UTC):
            continue
        d = ts.normalize()
        row = levels.loc[levels.index == d]
        if row.empty:
            continue
        pdh = row['pdh'].iloc[0]; pdl = row['pdl'].iloc[0]
        used = swept_today.setdefault(d, set())

        # -- upside sweep: high pierces PDH, look for close back below within window --
        if 'high' not in used and hi[i] > pdh:
            extreme = hi[i]
            confirmed_at = None
            for j in range(i + 1, min(i + 1 + CONFIRM_BARS, n)):
                extreme = max(extreme, hi[j])
                if cl[j] < pdh:
                    confirmed_at = j
                    break
                if not (SESSION_START_UTC <= idx[j].hour < SESSION_END_UTC):
                    break
            used.add('high')
            if confirmed_at is not None:
                buf = atr_at(k, ts)
                if buf is not None:
                    stop = extreme + buf * ATR_BUFFER
                    entry = cl[confirmed_at]
                    res = simulate(hi, lo, cl, confirmed_at + 1, -1, entry, stop, tp_r)
                    if res is not None:
                        r, bars, sld = res
                        trades.append({'instrument': k, 'time': idx[confirmed_at], 'dir': -1,
                                        'r_gross': r, 'sl_dist': sld})

        # -- downside sweep: low pierces PDL, look for close back above within window --
        if 'low' not in used and lo[i] < pdl:
            extreme = lo[i]
            confirmed_at = None
            for j in range(i + 1, min(i + 1 + CONFIRM_BARS, n)):
                extreme = min(extreme, lo[j])
                if cl[j] > pdl:
                    confirmed_at = j
                    break
                if not (SESSION_START_UTC <= idx[j].hour < SESSION_END_UTC):
                    break
            used.add('low')
            if confirmed_at is not None:
                buf = atr_at(k, ts)
                if buf is not None:
                    stop = extreme - buf * ATR_BUFFER
                    entry = cl[confirmed_at]
                    res = simulate(hi, lo, cl, confirmed_at + 1, 1, entry, stop, tp_r)
                    if res is not None:
                        r, bars, sld = res
                        trades.append({'instrument': k, 'time': idx[confirmed_at], 'dir': 1,
                                        'r_gross': r, 'sl_dist': sld})

    # apply realistic costs, converted to R using each trade's ACTUAL stop distance
    for t in trades:
        cost_price = COST_PRICE[k] * SLIPPAGE_MULT.get(k, 1.0)
        cost_r = cost_price / t['sl_dist'] if t['sl_dist'] > 0 else 0.0
        t['r_net'] = t['r_gross'] - cost_r
    return trades


def stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0, total_r=0.0)
    w = r[r > 0]; l = r[r <= 0]
    pf = round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else float('inf')
    return dict(n=len(r), wr=round(len(w) / len(r) * 100, 1), pf=pf,
                exp=round(r.mean(), 3), total_r=round(r.sum(), 1))


def fmt(label, s, width=22):
    return (f'  {label:<{width}}  N={s["n"]:>5}  WR={s["wr"]:>5.1f}%  '
            f'PF={s["pf"]:>6.2f}  Exp(R)={s["exp"]:>+6.3f}  TotalR={s["total_r"]:>+9.1f}')


# ── Load ─────────────────────────────────────────────────────────────────────
print('Loading M1 data...')
loaded = [k for k in FILES if load(k)]
missing = [k for k in FILES if k not in loaded]
print(f'Loaded {len(loaded)}/9: {loaded}')
if missing:
    print(f'MISSING or unreadable *_M1_ftmo.csv: {missing}')
for k in loaded:
    print(f'  {k}: {_m1[k].index[0].date()} -> {_m1[k].index[-1].date()}  ({len(_m1[k]):,} bars)')

# ── Coarse pass: TP grid x instrument, IS/OOS split ─────────────────────────
print(f'\n{"="*78}\n  HYPOTHESIS 1 - LIQUIDITY SWEEP REVERSAL - COARSE MULTI-ASSET PASS\n{"="*78}')

for tp_r in TP_GRID:
    print(f'\n--- TP = {tp_r}R ---')
    all_is, all_oos = [], []
    for k in loaded:
        trades = detect_and_simulate(k, tp_r)
        is_r  = [t['r_net'] for t in trades if str(t['time'].date()) < IS_OOS_SPLIT]
        oos_r = [t['r_net'] for t in trades if str(t['time'].date()) >= IS_OOS_SPLIT]
        all_is += is_r; all_oos += oos_r
        s_is, s_oos = stats(is_r), stats(oos_r)
        print(fmt(f'{k} IS', s_is))
        print(fmt(f'{k} OOS', s_oos))
    print('  ' + '-'*74)
    print(fmt('ALL INSTRUMENTS IS', stats(all_is)))
    print(fmt('ALL INSTRUMENTS OOS', stats(all_oos)))

print(f'\n{"="*78}')
print('Coarse pass done. Decision rule (frozen before running):')
print('  ACCEPT for full validation pipeline only if OOS combined PF > 1.3')
print('  AND at least 6/9 instruments individually OOS-profitable')
print('  AND no single instrument accounts for >40% of total OOS profit.')
print('  Otherwise: discard, do not tune parameters to rescue it.')
print(f'{"="*78}')
