"""
strategy10_cot.py

Strategy 10 — COT positioning fade, weekly rebalance.

Genuinely different data source from everything tested tonight: futures
positioning, not price at all. Classic contrarian idea: when leveraged
speculators are at a positioning extreme (per the 52-week z-score),
they've historically tended to be caught wrong-footed at turning points
— fade the extreme rather than follow it. Weaker, more debated evidence
base than momentum or carry, worth testing but not over-trusting even
before seeing a number.

Covers 7 instruments (no DAX — no CFTC coverage for Eurex-listed
contracts): EURUSD, GBPUSD, USDJPY, GOLD, SP500, NAS100, US30.

Mechanical rules (no discretion):
  - Signal: z52 (52-week rolling z-score of net leveraged-money/money-
    manager positioning) from COT_weekly_final.csv, evaluated as of the
    COT report requires strictly matching the ACTUAL publication lag,
    not just the report date. CFTC publishes each Tuesday's data the
    FOLLOWING Friday afternoon. Using the report date directly as the
    tradeable date would be a lookahead bug — same class of mistake as
    strategy4's original bug. This script enters no earlier than the
    Monday AFTER the report's Friday release (report_date + 6 days,
    rounded to the next trading day), not on the report date itself.
  - z52 > +2 -> speculators net-long extreme -> fade -> SHORT
    z52 < -2 -> speculators net-short extreme -> fade -> LONG
  - Entry: first M1 bar at/after the actionable date, at that bar's
    close price.
  - Stop: entry +/- 3x ATR(20, daily).
  - Exit: SAME vsim() core as every other script tonight — NOT
    reimplemented. 5-day time cap (weekly signal, matches strategy9's
    swing-hold convention).
  - TP sweep: 1.5R, 2.0R, 3.0R, 4.0R.

IS/OOS SPLIT — LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u strategy10_cot.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE       = 0.10
MAX_BARS_SWING = 5 * 24 * 60
Z_THRESHOLD    = 2.0
ATR_LEN        = 20
ATR_MULT       = 3.0
RISK_PCT       = 0.5
START_BAL      = 70000
TP_SWEEP       = [1.5, 2.0, 3.0, 4.0]
IS_OOS_SPLIT   = pd.Timestamp('2025-02-01', tz='UTC')
PUBLICATION_LAG_DAYS = 6   # Tuesday report -> Friday release -> actionable Monday

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
COT_INSTRUMENTS = ['EURUSD','GBPUSD','USDJPY','GOLD','SP500','NAS100','US30']  # no DAX

_m1 = {}
_cot = None

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

def load_cot():
    global _cot
    fn = 'COT_weekly_final.csv'
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn, parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date'], utc=True)
    _cot = df
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


def collect_signals(k):
    m1 = _m1[k]; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    cot_k = _cot[_cot['instrument'] == k].sort_values('date')
    if cot_k.empty: return []

    signals = []
    for _, row in cot_k.iterrows():
        z = row['z52']
        if pd.isna(z): continue
        if z > Z_THRESHOLD: direction = -1
        elif z < -Z_THRESHOLD: direction = 1
        else: continue

        actionable_date = row['date'] + pd.Timedelta(days=PUBLICATION_LAG_DAYS)
        ep = mi.searchsorted(actionable_date)
        if ep >= len(m1): continue

        atr_val = d_atr.asof(actionable_date)
        if pd.isna(atr_val) or atr_val <= 0: continue

        entry_price = float(m1['close'].values[ep])
        sl = entry_price - direction * ATR_MULT * atr_val

        signals.append({
            'instrument': k, 'dir': direction, 'entry': entry_price, 'sl': sl,
            'entry_time': mi[ep], 'ep': ep,
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
loaded = [k for k in COT_INSTRUMENTS if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

print('Loading COT data...')
if not load_cot():
    print('COT_weekly_final.csv not found — run download_cot3_final.py first.')
    raise SystemExit(1)
print(f'  {len(_cot)} rows, instruments: {sorted(_cot["instrument"].unique())}')

# ── Collect signals ONCE per instrument ────────────────────────────────────────
all_signals = []
for k in loaded:
    print(f'  Scanning {k} for COT positioning-fade signals...', end=' ', flush=True)
    sig = collect_signals(k)
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
    print_row('    ALL INSTRUMENTS', n, wr, pf, tot)
    by_year = {}
    for t in is_trades: by_year.setdefault(t['year'], []).append(t['r_net'])
    for yr in sorted(by_year):
        rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('      ' + str(yr) + flag, n, wr, pf, tot)

    r_oos = np.array([t['r_net'] for t in oos_trades])
    n, wr, pf, tot = stats(r_oos)
    print('  HOLDOUT:')
    print_row('    ALL INSTRUMENTS', n, wr, pf, tot)

print('\nDone.')
