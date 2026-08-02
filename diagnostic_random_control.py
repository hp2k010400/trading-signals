"""
diagnostic_random_control.py

PURPOSE: sanity-check the backtest engine itself, not a new hypothesis.

After 4 straight rejections (5 counting the original M1GOATV2 IB
signal), it's fair to ask: is the entry/stop/target simulation loop
itself biased, silently manufacturing losses regardless of what
direction is traded? If so, every rejection so far would be
meaningless — not "no edge exists," but "the engine can't measure edge
correctly."

METHOD: reuse the EXACT same event detection and trade-simulation
mechanics as research_momentum_ignition.py (same shock criteria, same
stop/target/time-stop logic, same cost model) but assign trade
direction via a rule that is DETERMINISTIC (reproducible) and
DECORRELATED from actual price action (alternating by event index,
not derived from the bar's own open/close) instead of the market's
real direction.

If the engine is unbiased: the random-direction control should show
gross (no-cost) expectancy statistically indistinguishable from zero
across a few thousand events — a coin flip against an engine with no
structural bias nets out near zero. It does NOT need to show exactly
50% win rate (that depends on the R:R payoff shape, not on bias), but
Exp(R) should hover near 0, not show a large, consistent skew.

If the control ALSO shows a large, consistent gross Exp(R) skew (in
either direction), that points to an engine bug: something in the
stop-vs-target check order, the entry price, or the cost application
is systematically favoring one outcome regardless of direction.

Also reports the REAL direction's gross (no-cost) and net (with-cost)
numbers side by side, so we can see directly how much of hypothesis
4's rejection came from costs vs. how much was already there before
any cost was applied.

Run in Codespaces (needs *_M1_ftmo.csv):
    python -u diagnostic_random_control.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

LOOKBACK        = 500
RANGE_PCTL      = 0.95
VOL_PCTL        = 0.95
SESSION_START_UTC = 6
SESSION_END_UTC   = 20
STOP_BUFFER_FRAC  = 0.10
MIN_SL_COST_MULT  = 3.0
TIME_STOP_MIN     = 120
TP_R              = 2.0
MAX_PER_DAY       = 3

FILES = {
    'DAX':    'GER40_M1_ftmo.csv',   'NAS100': 'US100_M1_ftmo.csv',
    'SP500':  'US500_M1_ftmo.csv',   'US30':   'US30_M1_ftmo.csv',
    'EURUSD': 'EURUSD_M1_ftmo.csv',  'GBPUSD': 'GBPUSD_M1_ftmo.csv',
    'USDJPY': 'USDJPY_M1_ftmo.csv',  'GOLD':   'XAUUSD_M1_ftmo.csv',
    'NATGAS': 'NATGAS_M1_ftmo.csv',
}
COST_PRICE = {
    'DAX': 2.0, 'NAS100': 2.0, 'SP500': 0.8, 'US30': 4.0,
    'EURUSD': 0.00020, 'GBPUSD': 0.00026, 'USDJPY': 0.026,
    'GOLD': 0.50, 'NATGAS': 0.010,
}
SLIPPAGE_MULT = {'NATGAS': 3.0}
IS_OOS_SPLIT = '2024-01-01'

_m1, _has_volume = {}, {}


def load(k):
    fn = FILES[k]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    cols = {c.lower(): c for c in df.columns}
    need = ['time', 'open', 'high', 'low', 'close']
    if not all(c in cols for c in need):
        return False
    rename = {cols[c]: c for c in need}
    vol_col = cols.get('tick_volume') or cols.get('volume')
    if vol_col:
        rename[vol_col] = 'volume'
    df = df.rename(columns=rename)
    ts = pd.to_numeric(df['time'], errors='coerce')
    df['time'] = pd.to_datetime(ts, unit='s', utc=True) if ts.notna().mean() > 0.99 \
        else pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df['range'] = df['high'] - df['low']
    has_vol = 'volume' in df.columns
    _has_volume[k] = has_vol
    if has_vol:
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce').fillna(0)
    _m1[k] = df
    return True


def run(k):
    df = _m1[k]; n = len(df)
    range_thresh = df['range'].rolling(LOOKBACK).quantile(RANGE_PCTL).shift(1)
    ignite = df['range'] > range_thresh
    if _has_volume[k]:
        vol_thresh = df['volume'].rolling(LOOKBACK).quantile(VOL_PCTL).shift(1)
        ignite = ignite & (df['volume'] > vol_thresh)
    idx = df.index; hrs = idx.hour
    ignite = ignite & (hrs >= SESSION_START_UTC) & (hrs < SESSION_END_UTC) & (idx.dayofweek < 5)

    op = df['open'].values; hi = df['high'].values; lo = df['low'].values
    cl = df['close'].values; rng = df['range'].values
    ignite_pos = np.where(ignite.values)[0]

    day_count = {}
    rows = []
    event_num = 0

    for i in ignite_pos:
        d = idx[i].date()
        if day_count.get(d, 0) >= MAX_PER_DAY:
            continue
        real_dir = 1 if cl[i] > op[i] else (-1 if cl[i] < op[i] else 0)
        if real_dir == 0:
            continue

        # deterministic, price-independent "random" direction: alternate by
        # event count, NOT derived from this bar's own price action
        rand_dir = 1 if event_num % 2 == 0 else -1
        event_num += 1

        cost_price_i = COST_PRICE[k] * SLIPPAGE_MULT.get(k, 1.0)

        def sim(direction):
            entry = cl[i]
            buf = rng[i] * STOP_BUFFER_FRAC
            stop = lo[i] - buf if direction == 1 else hi[i] + buf
            sl_dist = abs(entry - stop)
            if sl_dist < cost_price_i * MIN_SL_COST_MULT:
                return None
            tp = entry + sl_dist * TP_R if direction == 1 else entry - sl_dist * TP_R
            end = min(i + 1 + TIME_STOP_MIN, n)
            if i + 1 >= end:
                return None
            r_gross = None
            for j in range(i + 1, end):
                if direction == 1:
                    if lo[j] <= stop: r_gross = -1.0; break
                    if hi[j] >= tp:   r_gross = TP_R;  break
                else:
                    if hi[j] >= stop: r_gross = -1.0; break
                    if lo[j] <= tp:   r_gross = TP_R;  break
            if r_gross is None:
                r_gross = (cl[end-1]-entry)/sl_dist if direction == 1 else (entry-cl[end-1])/sl_dist
            return r_gross, sl_dist

        real = sim(real_dir)
        rand = sim(rand_dir)
        if real is None or rand is None:
            continue
        day_count[d] = day_count.get(d, 0) + 1
        r_gross_real, sld = real
        r_gross_rand, _ = rand
        cost_r = cost_price_i / sld
        rows.append({
            'time': idx[i],
            'real_gross': r_gross_real, 'real_net': r_gross_real - cost_r,
            'rand_gross': r_gross_rand,
        })
    return rows


def stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(n=0, wr=0.0, pf=0.0, exp=0.0)
    w = r[r > 0]; l = r[r <= 0]
    pf = round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else float('inf')
    return dict(n=len(r), wr=round(len(w)/len(r)*100, 1), pf=pf, exp=round(r.mean(), 3))


def fmt(label, s, width=26):
    return f'  {label:<{width}}  N={s["n"]:>5}  WR={s["wr"]:>5.1f}%  PF={s["pf"]:>6.2f}  Exp(R)={s["exp"]:>+6.3f}'


print('Loading FTMO M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)}/9: {loaded}\n')

print(f'{"="*78}\n  ENGINE SANITY CHECK: real signal vs price-independent random control\n{"="*78}')
print('  (config: range>=95th pctl+vol, time_stop=120min, TP=2.0R -- same as')
print('   hypothesis 4 first cell, for direct comparison)\n')

all_real_gross, all_real_net, all_rand_gross = [], [], []
for k in loaded:
    rows = run(k)
    oos = [r for r in rows if str(r['time'].date()) >= IS_OOS_SPLIT]
    rg = [r['real_gross'] for r in oos]; rn = [r['real_net'] for r in oos]; ra = [r['rand_gross'] for r in oos]
    all_real_gross += rg; all_real_net += rn; all_rand_gross += ra
    print(f'--- {k} ---')
    print(fmt('  real direction, GROSS', stats(rg)))
    print(fmt('  real direction, NET (w/ cost)', stats(rn)))
    print(fmt('  random control, GROSS', stats(ra)))
    print()

print(f'{"="*78}\n  COMBINED ALL INSTRUMENTS\n{"="*78}')
print(fmt('real direction, GROSS', stats(all_real_gross)))
print(fmt('real direction, NET (w/ cost)', stats(all_real_net)))
print(fmt('random control, GROSS', stats(all_rand_gross)))
print(f'\n{"="*78}')
print('Interpretation:')
print('  - If "random control GROSS" Exp(R) is close to 0 (say, within')
print('    +/-0.05R) while "real direction GROSS" is clearly negative,')
print('    the engine is unbiased and the market itself carries real')
print('    (adverse) directional information at these events -- not a bug.')
print('  - If "random control GROSS" is ALSO meaningfully skewed, that is')
print('    an engine bug independent of any real market pattern, and every')
print('    prior rejection needs to be re-examined before trusting it.')
print(f'{"="*78}')
