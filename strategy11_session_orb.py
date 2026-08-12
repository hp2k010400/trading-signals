"""
strategy11_session_orb.py

Strategy 11 — Session opening-range breakout.

Different specific trigger from Donchian (rolling N-bar range) and the
base IB/PB signal (H1 compression pattern) — this anchors the range to
a fixed session-open time per instrument, mirroring what the earlier
6botV2 system used (DAX_ORB/NAS_ORB/SP5_ORB reference-bar approach).
That system reportedly showed PF ~1.4-1.5, but only on H1 simulation,
never verified at M1 precision the way everything has been tonight —
this is that overdue re-check, not a fresh guess.

Mechanical rules (no discretion), reusing the SAME verified no-lookahead
entry-scan pattern as full_history_backtest.py/strategy7 (sequential
M1 scan for the exact breakout bar, not a window-max shortcut):
  - Reference bar: a fixed 1-hour session-open bar per instrument
    (DAX 08:00 UTC, NAS100/SP500/US30 13:00 UTC, EURUSD/GBPUSD/GOLD
    07:00 UTC, USDJPY 00:00 UTC — same anchors 6botV2 used).
  - Entry window: the following 3 hours, scanned M1-by-M1 for the exact
    bar that breaks the reference bar's high or low.
  - Stop: opposite side of the reference bar.
  - Exit: SAME vsim() core as every other script tonight — NOT
    reimplemented. 8h time cap (480 bars), matching the original
    baseline convention.
  - TP sweep: 1.0R, 1.5R, 2.0R, 2.5R, 3.0R, 4.0R.

IS/OOS SPLIT — LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u strategy11_session_orb.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE     = 0.10
WIN_HOURS    = 3
MAX_BARS     = 480
RISK_PCT     = 0.5
START_BAL    = 70000
TP_SWEEP     = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

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
REF_HOUR = {
    'DAX':8, 'NAS100':13, 'SP500':13, 'US30':13,
    'EURUSD':7, 'GBPUSD':7, 'GOLD':7, 'USDJPY':0,
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
def vsim(k, ep, d, entry, sl, tp_r, max_bars=MAX_BARS):
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


def collect_signals(k):
    m1 = _m1[k]; mi = m1.index
    ref_hour = REF_HOUR[k]
    h1 = m1.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    ref_bars = h1[h1.index.hour == ref_hour]

    signals = []
    for ts, bar in ref_bars.iterrows():
        if ts.dayofweek >= 5: continue
        rhi = float(bar['high']); rlo = float(bar['low'])
        if rhi <= rlo: continue

        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0: continue

        taken = False; d = 0; e = 0.0; sl = 0.0; j = 0
        for jj in range(len(window)):
            b = window.iloc[jj]
            if b['high'] > rhi: d = 1; e = rhi; sl = rlo; j = jj; taken = True; break
            elif b['low'] < rlo: d = -1; e = rlo; sl = rhi; j = jj; taken = True; break

        if not taken: continue
        ep = mi.searchsorted(window.index[j])
        if ep >= len(m1): continue

        signals.append({
            'instrument': k, 'dir': d, 'entry': e, 'sl': sl,
            'entry_time': window.index[j], 'ep': ep,
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
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

# ── Collect signals ONCE per instrument ────────────────────────────────────────
all_signals = []
for k in loaded:
    print(f'  Scanning {k} (ref hour {REF_HOUR[k]}:00 UTC) for ORB signals...', end=' ', flush=True)
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
