"""
friday_close_backtest.py

Compares two scenarios across full OANDA history:
  A. NORMAL    — 8h time stop only. Late Friday entries carry over the weekend
                 gap and close Monday at whatever price the market opens at.
  B. FRI_CLOSE — Same signals, but any position still open at Friday 21:00 UTC
                 is force-closed at that bar's close price.

Answers: is it better to hold through the weekend gap or cut Friday?

Run in Codespace: python -u friday_close_backtest.py
"""

import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

BASE_TP     = 4.0
SLIPPAGE    = 0.10
WIN_HOURS   = 3
MAX_BARS    = 480       # 8h time stop
MAX_PD      = 3
WICK_BODY   = 2.0
WICK_RANGE  = 0.5
MIN_RANGE   = 0.00015
RISK_PCT    = 0.5
START_BAL   = 70000
FRI_CLOSE_H = 21       # UTC — force close any open trade at/after this on Friday

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

def vsim(k, ep, d, entry, sl, fri_close=False):
    """
    Simulate from bar ep+1 forward.
    fri_close=True: exit at Friday 21:00 UTC bar close if still open.
    Returns (r_gross, hold_bars).
    """
    m1 = _m1[k]
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0, MAX_BARS

    end = min(ep + 1 + MAX_BARS, len(m1))
    slc = m1.iloc[ep+1:end]
    if len(slc) == 0: return -1.0, MAX_BARS

    hi = slc['high'].values
    lo = slc['low'].values
    cl = slc['close'].values
    ts = slc.index
    tp = entry + sl_d * BASE_TP if d == 1 else entry - sl_d * BASE_TP

    for i in range(len(hi)):
        t = ts[i]

        # Friday forced close at 21:00 UTC
        if fri_close and t.dayofweek == 4 and t.hour >= FRI_CLOSE_H:
            r = (cl[i] - entry) / sl_d if d == 1 else (entry - cl[i]) / sl_d
            return r, i + 1

        if d == 1:
            if hi[i] >= tp: return BASE_TP, i + 1
            if lo[i] <= sl: return -1.0, i + 1
        else:
            if lo[i] <= tp: return BASE_TP, i + 1
            if hi[i] >= sl: return -1.0, i + 1

    # Time stop or end of data
    r = (cl[-1] - entry) / sl_d if d == 1 else (entry - cl[-1]) / sl_d
    return r, len(slc)


def collect(k, fri_close=False):
    m1 = _m1[k]; mi = m1.index
    skip    = H1_SKIP.get(k, frozenset())
    p_hours = H1_HOURS.get(k, {8, 9, 13, 14})
    h1 = m1.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index)
    day_count = {}
    trades = []

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
            pb = pin_bar_dir(float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close']))
            if pb == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            for jj in range(len(window)):
                b = window.iloc[jj]
                if pb == 1  and b['high'] > pb_h: d=1;  e=pb_h; sl=pb_l; j=jj; taken=True; break
                elif pb ==-1 and b['low']  < pb_l: d=-1; e=pb_l; sl=pb_h; j=jj; taken=True; break
        else:
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            is_ib = bar['high'] < prev['high'] and bar['low'] > prev['low']
            ib_ok = is_ib and (ib_h - ib_l) > 0 and (ib_h - ib_l) / ib_h >= MIN_RANGE
            if ib_ok:
                for jj in range(len(window)):
                    b = window.iloc[jj]
                    if b['high'] > ib_h:  d=1;  e=ib_h; sl=ib_l; j=jj; taken=True; break
                    elif b['low'] < ib_l: d=-1; e=ib_l; sl=ib_h; j=jj; taken=True; break
            if not taken:
                pb = pin_bar_dir(float(bar['open']), ib_h, ib_l, float(bar['close']))
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
        r_gross, hold_bars = vsim(k, ep, d, e, sl, fri_close=fri_close)

        day_count[date_k] = day_count.get(date_k, 0) + 1
        trades.append({
            'instrument': k,
            'entry_time': entry_time,
            'r_net':      r_gross - COST[k] - SLIPPAGE,
            'hold_bars':  hold_bars,
            'on_friday':  entry_time.dayofweek == 4,
        })
    return trades


def report(label, trades):
    rpr = START_BAL * RISK_PCT / 100.0
    DIV = '─' * 70
    print(f'\n  {label}')
    print(f'  {DIV}')
    if not trades:
        print('  NO TRADES'); return

    r  = np.array([t['r_net'] for t in trades])
    w  = r[r > 0]; l = r[r <= 0]
    pf = round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else 0.0
    wr = round(len(w) / len(r) * 100, 1)
    print(f'  All trades:  N={len(trades):>4}  WR={wr}%  PF={pf}  R={r.sum():+.2f}  £{r.sum()*rpr:+,.0f}')

    # Friday vs non-Friday breakdown
    fri = [t for t in trades if t['on_friday']]
    non = [t for t in trades if not t['on_friday']]
    for grp, name in [(fri, 'Friday entries'), (non, 'Mon–Thu entries')]:
        if not grp: continue
        rv = np.array([t['r_net'] for t in grp])
        wv = rv[rv > 0]; lv = rv[rv <= 0]
        pf2 = round(wv.sum() / abs(lv.sum()), 2) if len(lv) and lv.sum() != 0 else 0.0
        wr2 = round(len(wv) / len(rv) * 100, 1)
        print(f'  {name:<20} N={len(grp):>4}  WR={wr2}%  PF={pf2}  R={rv.sum():+.2f}  £{rv.sum()*rpr:+,.0f}')


# ── Main ─────────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded: {loaded}')
print(f'Date range: {min(_m1[k].index[0] for k in loaded).date()}  →  '
      f'{max(_m1[k].index[-1] for k in loaded).date()}')

print('\nScenario A — NORMAL (8h time stop, weekend gap exposure)...')
trades_normal = []
for k in loaded:
    trades_normal.extend(collect(k, fri_close=False))

print('Scenario B — FRIDAY CLOSE at 21:00 UTC...')
trades_fri = []
for k in loaded:
    trades_fri.extend(collect(k, fri_close=True))

# Find trades where the two scenarios produced a different outcome
key = lambda t: (t['instrument'], t['entry_time'])
n_map = {key(t): t for t in trades_normal}
f_map = {key(t): t for t in trades_fri}
affected = [(n_map[k], f_map[k]) for k in n_map
            if k in f_map and abs(n_map[k]['r_net'] - f_map[k]['r_net']) > 0.001]

print(f'\nTrades affected by the Friday close rule: {len(affected)} / {len(trades_normal)}')

print('\n' + '=' * 72)
print('  FRIDAY CLOSE vs HOLD WEEKEND — FULL HISTORY')
print('=' * 72)

report('A. NORMAL  — 8h time stop (can carry over weekend gap)', trades_normal)
report('B. FRI_CLOSE — force exit Friday 21:00 UTC',             trades_fri)

# Net impact of the rule
rpr = START_BAL * RISK_PCT / 100.0
r_normal = sum(t['r_net'] for t in trades_normal)
r_fri    = sum(t['r_net'] for t in trades_fri)
diff_r   = r_fri - r_normal
diff_gbp = diff_r * rpr

print(f'\n  Net impact of Friday close rule: {diff_r:+.2f}R  £{diff_gbp:+,.0f}')
print(f'  Verdict: {"BETTER to close Friday" if diff_r > 0 else "BETTER to hold over weekend"} '
      f'({abs(diff_r):.2f}R / £{abs(diff_gbp):,.0f} difference over full history)')

# Detailed breakdown of affected trades
if affected:
    diffs = [f_map[key(n)]['r_net'] - n['r_net'] for n, _ in affected]
    diffs = np.array(diffs)
    pos = diffs[diffs > 0]; neg = diffs[diffs < 0]
    print(f'\n  Affected trade breakdown:')
    print(f'    Friday close was better: {len(pos)} trades  (+{pos.sum():.2f}R  £{pos.sum()*rpr:+,.0f})')
    print(f'    Friday close was worse:  {len(neg)} trades  ({neg.sum():.2f}R  £{neg.sum()*rpr:+,.0f})')
    print(f'    Average impact per affected trade: {diffs.mean():+.3f}R')

print('\nDone.')
