"""
strategy7_extended_hold.py

Same IB/PB entry signal as full_history_backtest.py (v2.07 EA), entry
detection logic copied VERBATIM and unchanged — that part is already
independently verified. This script only changes the EXIT: instead of
the fixed 8h time stop, it sweeps holding window x TP ratio, to test
whether the entry signal has latent edge that the tight time stop was
suppressing (per Key Lesson 3 in the research summary: the 8h time stop
was found to close trades at a "slightly negative" average price).

Windows tested:
  - 8h   (480 bars)  — baseline, matches full_history_backtest.py exactly
  - 3d   (4320 bars)
  - 5d   (7200 bars)
  - none (effectively uncapped — run to TP or SL or end of data)

KNOWN LIMITATION, flagged honestly: the cost model here is spread +
slippage only, same as every other script tonight. It does NOT include
overnight swap/rollover, which is real for any position held more than
a few hours. The "none" and "5d" windows in particular could hold for
days-to-weeks in practice — if either of those looks good, that needs a
swap-cost check before being trusted, not just this backtest.

Run in Codespace: python -u strategy7_extended_hold.py
(This sweeps 4 windows x 6 TP ratios over the full 17k-signal history —
expect this to take a while; let it run.)
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE   = 0.10
WIN_HOURS  = 3
MAX_PD     = 3
WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015
RISK_PCT   = 0.5
START_BAL  = 70000

WINDOWS = {
    '8h (baseline)': 480,
    '3d':            3 * 24 * 60,
    '5d':            5 * 24 * 60,
    'none (uncapped)': 10**7,   # vsim clamps this to end-of-data automatically
}
TP_SWEEP = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]

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
H1_HOURS = {
    'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},
}
H1_SKIP = {
    'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'USDJPY':frozenset(),'GOLD':frozenset(),
    'NAS100':frozenset({0}),'SP500':frozenset({0}),'US30':frozenset({0}),
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

def pin_bar_dir(o, h, l, c):
    body = abs(c - o); full = h - l
    if full <= 0 or body < full * 0.02: return 0
    uw = h - max(o, c); lw = min(o, c) - l
    if uw >= WICK_BODY * max(body, full * 0.001) and uw >= WICK_RANGE * full: return -1
    if lw >= WICK_BODY * max(body, full * 0.001) and lw >= WICK_RANGE * full: return  1
    return 0

# ── Same proven core as every other script tonight — NOT reimplemented ────────
def vsim(k, ep, d, entry, sl, tp_r, max_bars):
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


# ── Entry detection — copied VERBATIM from full_history_backtest.py, only the
#    trailing vsim() call is removed (exit is applied separately, in a sweep) ──
def collect_signals(k):
    m1 = _m1[k]; mi = m1.index
    skip    = H1_SKIP.get(k, frozenset())
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    h1 = m1.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); day_count = {}; signals = []

    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip or ts.dayofweek >= 5: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue

        bar = h1.iloc[i]; prev = h1.iloc[i-1]
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0: continue

        taken = False; d = 0; e = 0.0; sl = 0.0; j = 0

        if k == 'USDJPY':
            pb = pin_bar_dir(float(bar['open']),float(bar['high']),float(bar['low']),float(bar['close']))
            if pb == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            for jj in range(len(window)):
                b = window.iloc[jj]
                if pb == 1  and b['high'] > pb_h: d=1;  e=pb_h; sl=pb_l; j=jj; taken=True; break
                elif pb ==-1 and b['low']  < pb_l: d=-1; e=pb_l; sl=pb_h; j=jj; taken=True; break
        else:
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            is_ib = bar['high'] < prev['high'] and bar['low'] > prev['low']
            ib_ok = is_ib and (ib_h-ib_l) > 0 and (ib_h-ib_l)/ib_h >= MIN_RANGE
            if ib_ok:
                for jj in range(len(window)):
                    b = window.iloc[jj]
                    if b['high'] > ib_h:  d=1;  e=ib_h; sl=ib_l; j=jj; taken=True; break
                    elif b['low']  < ib_l: d=-1; e=ib_l; sl=ib_h; j=jj; taken=True; break
            if not taken:
                pb = pin_bar_dir(float(bar['open']),ib_h,ib_l,float(bar['close']))
                if pb != 0:
                    for jj in range(len(window)):
                        b = window.iloc[jj]
                        if pb == 1  and b['high'] > ib_h:  d=1;  e=ib_h; sl=ib_l; j=jj; taken=True; break
                        elif pb ==-1 and b['low']  < ib_l: d=-1; e=ib_l; sl=ib_h; j=jj; taken=True; break

        if not taken: continue
        sl_d = abs(e - sl)
        if sl_d <= 0: continue
        ep = mi.searchsorted(window.index[j])
        if ep >= len(m1): continue

        entry_time = window.index[j]
        day_count[date_k] = day_count.get(date_k, 0) + 1
        signals.append({
            'instrument': k, 'dir': d, 'entry': e, 'sl': sl,
            'entry_time': entry_time, 'ep': ep,
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

# ── Collect signals ONCE per instrument (entry point/price/SL only, no exit) ──
all_signals = []
for k in loaded:
    print(f'  Scanning {k} for IB/PB signals...', end=' ', flush=True)
    sig = collect_signals(k)
    print(f'{len(sig)} signals')
    all_signals.extend(sig)

print(f'\nTotal raw signals: {len(all_signals)}')

# ── Sweep window x TP on the SAME signal set ───────────────────────────────────
for win_label, max_bars in WINDOWS.items():
    print(f'\n{"#"*74}')
    print(f'  WINDOW = {win_label}')
    print(f'{"#"*74}')
    for tp_r in TP_SWEEP:
        trades = []
        for s in all_signals:
            r_gross, hold_bars = vsim(s['instrument'], s['ep'], s['dir'], s['entry'], s['sl'],
                                       tp_r, max_bars)
            r_net = r_gross - COST[s['instrument']] - SLIPPAGE
            trades.append({'year': s['entry_time'].year, 'r_net': r_net})

        r_all = np.array([t['r_net'] for t in trades])
        n, wr, pf, tot = stats(r_all)
        print(f'  TP={tp_r}R:', end=' ')
        print_row('', n, wr, pf, tot, width=0)

print('\nDone.')
