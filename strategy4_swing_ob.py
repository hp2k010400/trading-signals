"""
strategy4_swing_ob.py

Strategy 4 — D1 trend bias + H4 order-block reclaim, swing hold (up to 5 days).

Mechanical rules (no discretion):
  - Bias: D1 close vs D1 EMA(50), using the PRIOR completed daily bar (no lookahead).
  - Zone: the H4 candle immediately before an H4 candle that closes beyond the
    prior-5-bar H4 high/low, opposite colour to the break (classic order-block def).
  - Trigger: a later H4 bar's wick returns into the zone, then closes back out
    of it in the bias direction (reclaim). Zone expires after ZONE_LIFE H4 bars
    if never touched. One trade per zone.
  - Stop: zone boundary +/- 0.25x ATR(14,H4) buffer.
  - Exit: SAME vsim() as full_history_backtest.py (bar-by-bar M1 loop, proven
    correct against the 2026-08-01 backtest_is_oos.py bug) — NOT reimplemented.
    Collect signals once, sweep TP ratios in a second pass (per project lesson).
  - Time stop: 5 calendar days (MAX_BARS_SWING M1 bars) — closes at actual
    market price, same as the base system's 8h stop, just longer.

Run in Codespace: python -u strategy4_swing_ob.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE       = 0.10
MAX_BARS_SWING = 5 * 24 * 60      # 5 calendar days of M1 bars
ZONE_LIFE      = 20               # H4 bars a zone stays active if untouched
ATR_LEN        = 14
ATR_BUFFER     = 0.25
BREAK_LOOKBACK = 5                # H4 bars used to define "prior range" for a break
RISK_PCT       = 0.5
START_BAL      = 70000
TP_SWEEP       = [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]

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


# ── Same proven core as full_history_backtest.py — NOT reimplemented ──────────
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


def atr(h4, n=ATR_LEN):
    hi, lo, cl_prev = h4['high'], h4['low'], h4['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def collect_signals(k):
    """Detect D1-bias-aligned order-block reclaim entries. Returns raw signals
    (direction, entry, sl, entry M1 index) with NO exit applied yet.

    FIXED 2026-08-02: earlier version priced the fill at the zone boundary
    (z['hi']/z['lo']) but stamped the entry TIME at the H4 reclaim bar's
    CLOSE — by which point price had already closed beyond that boundary,
    so every trade was credited with free, riskless profit for the move
    from the zone edge up to the bar's close. That's why the first run
    showed 0 losing years out of 54 year/TP combos — a look-ahead bug, not
    edge. Fix: resolve the touch-then-reclaim at M1 resolution and enter
    at the actual M1 close price of the confirming bar, not the zone edge.
    """
    m1 = _m1[k]; mi = m1.index
    hi_arr = m1['high'].values; lo_arr = m1['low'].values; cl_arr = m1['close'].values

    d1 = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    d1_ema = d1['close'].ewm(span=50, adjust=False).mean()
    # bias as of the PRIOR completed daily bar — no lookahead
    bias_up = (d1['close'] > d1_ema).shift(1)
    bias_dn = (d1['close'] < d1_ema).shift(1)
    bias_up.index = bias_up.index.date
    bias_dn.index = bias_dn.index.date

    h4 = m1.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h4 = h4[h4['open'] > 0]
    h4_atr = atr(h4)
    hl = list(h4.index)

    signals = []

    for i in range(BREAK_LOOKBACK + 1, len(hl)):
        ts = hl[i]; bar = h4.iloc[i]
        day = ts.date()
        up = bias_up.get(day, False)
        dn = bias_dn.get(day, False)

        window = h4.iloc[i-BREAK_LOOKBACK:i]
        prior_hi = window['high'].max(); prior_lo = window['low'].min()
        prev = h4.iloc[i-1]
        prev_bear = prev['close'] < prev['open']
        prev_bull = prev['close'] > prev['open']

        zdir = 0
        if bar['close'] > prior_hi and up and prev_bear:
            zdir = 1; z_hi = prev['high']; z_lo = prev['low']
        elif bar['close'] < prior_lo and dn and prev_bull:
            zdir = -1; z_hi = prev['high']; z_lo = prev['low']
        if zdir == 0:
            continue

        buf = ATR_BUFFER * (h4_atr.iloc[i] if not np.isnan(h4_atr.iloc[i]) else 0)

        # Zone is known only once bar i has fully closed — scan M1 data
        # STRICTLY AFTER that point, so nothing here can see the future.
        zone_start = ts + pd.Timedelta(hours=4)
        zone_end   = zone_start + pd.Timedelta(hours=4*ZONE_LIFE)
        s_idx = mi.searchsorted(zone_start)
        e_idx = mi.searchsorted(zone_end)
        if s_idx >= e_idx or s_idx >= len(m1): continue
        e_idx = min(e_idx, len(m1))

        touched = False
        for jj in range(s_idx, e_idx):
            if not touched:
                if (zdir == 1 and lo_arr[jj] <= z_hi) or (zdir == -1 and hi_arr[jj] >= z_lo):
                    touched = True
                continue
            # already touched on an earlier bar — this bar's REAL close decides reclaim
            if zdir == 1 and cl_arr[jj] > z_hi:
                signals.append({
                    'instrument': k, 'dir': 1, 'entry': cl_arr[jj], 'sl': z_lo - buf,
                    'entry_time': mi[jj], 'ep': jj,
                })
                break
            if zdir == -1 and cl_arr[jj] < z_lo:
                signals.append({
                    'instrument': k, 'dir': -1, 'entry': cl_arr[jj], 'sl': z_hi + buf,
                    'entry_time': mi[jj], 'ep': jj,
                })
                break

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
    print(f'  Scanning {k} for order-block reclaims...', end=' ', flush=True)
    sig = collect_signals(k)
    print(f'{len(sig)} signals')
    all_signals.extend(sig)

print(f'\nTotal raw signals (pre-exit): {len(all_signals)}')
if len(all_signals) < 100:
    print('WARNING: fewer than 100 signals total — any PF here is not yet trustworthy.')

# ── Sweep TP ratios on the SAME signal set ─────────────────────────────────────
for tp_r in TP_SWEEP:
    print(f'\n{"="*74}')
    print(f'  TP = {tp_r}R')
    print(f'{"="*74}')
    trades = []
    for s in all_signals:
        r_gross, hold_bars = vsim(s['instrument'], s['ep'], s['dir'], s['entry'], s['sl'], tp_r)
        r_net = r_gross - COST[s['instrument']] - SLIPPAGE
        trades.append({
            'instrument': s['instrument'], 'year': s['entry_time'].year, 'r_net': r_net,
        })

    r_all = np.array([t['r_net'] for t in trades])
    n, wr, pf, tot = stats(r_all)
    print_row('ALL INSTRUMENTS', n, wr, pf, tot)

    by_year = {}
    for t in trades:
        by_year.setdefault(t['year'], []).append(t['r_net'])
    for yr in sorted(by_year):
        rv = np.array(by_year[yr])
        n, wr, pf, tot = stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('  ' + str(yr) + flag, n, wr, pf, tot)

print('\nDone.')
