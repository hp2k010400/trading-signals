"""
strategy9_relative_value.py

Strategy 9 — Cross-instrument relative value (mean reversion of the
SPREAD between two correlated instruments, not either instrument's own
price pattern).

Genuinely different signal source from everything tested tonight — base
IB/PB, Donchian, order-block reclaim, liquidity-sweep fade, momentum,
carry all derived their signal from ONE instrument's own OHLC. This one
uses the relationship BETWEEN two instruments.

HONEST SIMPLIFICATION: a true institutional pairs trade holds two
offsetting legs (long one, short the other, dollar/vol-neutral). This
project's infrastructure is single-instrument-R-based, so this v1
trades only the "A" leg of each pair, using the z-score of A vs B as
A's entry trigger — not a hedged, market-neutral position. That's a
real simplification, stated up front, not hidden. It still tests the
core hypothesis (does relative mispricing predict reversion) with much
less new-code surface / bug risk than building true two-legged pairs
mechanics from scratch tonight.

Mechanical rules (no discretion):
  - Pairs tested: (US30, SP500), (NAS100, SP500), (EURUSD, GBPUSD) —
    correlated instruments already in our 8-instrument set.
  - Spread: log(close_A) - log(close_B), on DAILY closes.
  - Z-score: (spread_today - rolling_mean_20d) / rolling_std_20d,
    computed using data up to and including the current completed daily
    bar (no lookahead — this is the same "use the just-completed bar"
    pattern as every H1/H4 signal tonight).
  - Signal: z > +2 -> A is relatively expensive vs B -> SHORT A
            z < -2 -> A is relatively cheap vs B -> LONG A
  - Entry: first M1 bar after that day's close.
  - Stop: entry +/- 3x ATR(20, daily) on instrument A.
  - Exit: SAME vsim() core as every other script tonight — NOT
    reimplemented. 5-day time cap (matches strategy4/5's swing hold).
  - TP sweep: 1.5R, 2.0R, 3.0R, 4.0R.

IS/OOS SPLIT — LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u strategy9_relative_value.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE       = 0.10
MAX_BARS_SWING = 5 * 24 * 60
Z_LOOKBACK     = 20
Z_THRESHOLD    = 2.0
ATR_LEN        = 20
ATR_MULT       = 3.0
RISK_PCT       = 0.5
START_BAL      = 70000
TP_SWEEP       = [1.5, 2.0, 3.0, 4.0]
IS_OOS_SPLIT   = pd.Timestamp('2025-02-01', tz='UTC')

PAIRS = [
    ('US30',   'SP500'),
    ('NAS100', 'SP500'),
    ('EURUSD', 'GBPUSD'),
]
FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,'GOLD':0.08,
}

_m1 = {}

def load(k):
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True


# ── Same proven core as every other script tonight — NOT reimplemented ────────
def vsim(k, ep, d, entry, sl, tp_r, max_bars=MAX_BARS_SWING):
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0, max_bars
    end = min(ep + 1 + max_bars, len(m1))
    slc = m1.iloc[ep+1:end]
    if len(slc) == 0: return -1.0, max_bars
    hi = slc['high'].values; lo = slc['low'].values; cl = slc['close'].values
    tp = entry + sl_d * tp_r if d == 1 else entry - sl_d * tp_r
    for i in range(len(hi)):
        if d == 1:
            if hi[i] >= tp: return tp_r, i + 1
            if lo[i] <= sl: return -1.0, i + 1
        else:
            if lo[i] <= tp: return tp_r, i + 1
            if hi[i] >= sl: return -1.0, i + 1
    r = (cl[-1]-entry)/sl_d if d==1 else (entry-cl[-1])/sl_d
    return r, len(slc)


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def collect_signals(a, b):
    m1a = _m1[a]; mia = m1a.index
    daily_a = m1a.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily_a = daily_a[daily_a['open'] > 0]
    d_atr = atr_daily(daily_a)

    daily_b = _m1[b].resample('1D').agg({'close':'last'}).dropna()

    joined = daily_a[['close']].join(daily_b[['close']], lsuffix='_a', rsuffix='_b', how='inner').dropna()
    spread = np.log(joined['close_a']) - np.log(joined['close_b'])
    roll_mean = spread.rolling(Z_LOOKBACK).mean()
    roll_std  = spread.rolling(Z_LOOKBACK).std()
    z = (spread - roll_mean) / roll_std

    signals = []
    for i in range(Z_LOOKBACK, len(z) - 1):
        zi = z.iloc[i]
        if pd.isna(zi): continue
        if zi > Z_THRESHOLD: direction = -1       # A relatively expensive -> short A
        elif zi < -Z_THRESHOLD: direction = 1     # A relatively cheap -> long A
        else: continue

        day = z.index[i]
        atr_val = d_atr.asof(day)
        if pd.isna(atr_val) or atr_val <= 0: continue

        entry_time = day + pd.Timedelta(days=1)   # first bar of the NEXT day, after this day's close is known
        ep = mia.searchsorted(entry_time)
        if ep >= len(m1a): continue

        entry_price = float(m1a['close'].values[ep])
        sl = entry_price - direction * ATR_MULT * atr_val

        signals.append({
            'instrument': a, 'dir': direction, 'entry': entry_price, 'sl': sl,
            'entry_time': mia[ep], 'ep': ep,
        })

    return signals


def stats(r_arr):
    if len(r_arr) == 0: return 0, 0.0, 0.0, 0.0
    w = r_arr[r_arr > 0]; l = r_arr[r_arr <= 0]
    pf = round(w.sum()/abs(l.sum()), 2) if len(l) and l.sum() != 0 else 0.0
    wr = round(len(w)/len(r_arr)*100, 1)
    return len(r_arr), wr, pf, r_arr.sum()

RPR = START_BAL * RISK_PCT / 100.0

def print_row(label, n, wr, pf, total_r, width=20):
    gbp = total_r * RPR
    print(f'  {label:<{width}}  N={n:>5}  WR={wr:>5.1f}%  PF={pf:>5.2f}  '
          f'R={total_r:>+9.2f}  £{gbp:>+10,.0f}')


# ── Load ─────────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
needed = set()
for a, b in PAIRS: needed.add(a); needed.add(b)
loaded = [k for k in needed if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

# ── Collect signals ONCE per pair ──────────────────────────────────────────────
all_signals = []
for a, b in PAIRS:
    if a not in _m1 or b not in _m1: continue
    print(f'  Scanning {a} vs {b} for relative-value signals...', end=' ', flush=True)
    sig = collect_signals(a, b)
    print(f'{len(sig)} signals')
    all_signals.extend(sig)

print(f'\nTotal raw signals: {len(all_signals)}')
if len(all_signals) < 100:
    print('WARNING: fewer than 100 signals total — treat any PF here as unreliable.')

# ── Sweep TP ratios on the SAME signal set, split IS/OOS ───────────────────────
for tp_r in TP_SWEEP:
    print(f'\n{"="*74}')
    print(f'  TP = {tp_r}R')
    print(f'{"="*74}')
    trades = []
    for s in all_signals:
        r_gross, hold_bars = vsim(s['instrument'], s['ep'], s['dir'], s['entry'], s['sl'], tp_r)
        r_net = r_gross - COST[s['instrument']] - SLIPPAGE
        trades.append({'entry_time': s['entry_time'], 'year': s['entry_time'].year, 'r_net': r_net})

    is_trades  = [t for t in trades if t['entry_time'] <  IS_OOS_SPLIT]
    oos_trades = [t for t in trades if t['entry_time'] >= IS_OOS_SPLIT]

    r_is = np.array([t['r_net'] for t in is_trades])
    n, wr, pf, tot = stats(r_is)
    print('  IN-SAMPLE:')
    print_row('    ALL PAIRS', n, wr, pf, tot)
    by_year = {}
    for t in is_trades: by_year.setdefault(t['year'], []).append(t['r_net'])
    for yr in sorted(by_year):
        rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('      ' + str(yr) + flag, n, wr, pf, tot)

    r_oos = np.array([t['r_net'] for t in oos_trades])
    n, wr, pf, tot = stats(r_oos)
    print('  HOLDOUT:')
    print_row('    ALL PAIRS', n, wr, pf, tot)

print('\nDone.')
