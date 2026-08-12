"""
strategy5_fade.py

Strategy 5 — H4 structure fade (liquidity sweep), swing hold (up to 5 days).

Hypothesis: Strategies 1/3/4 all failed by trying to FOLLOW a break of
structure (IB/PB breakout, Donchian breakout, order-block reclaim
continuation). All three lost in the same direction. This tests the
opposite: FADE a break of structure instead of following it.

Mechanical rules (no discretion):
  - Level: rolling N-bar H4 high/low, using STRICTLY PRIOR bars (not
    including the signal bar itself).
  - Signal: the current H4 bar's high sweeps above that prior-N high but
    its own close comes back below it (failed break / liquidity sweep) ->
    SHORT. Mirror for lows -> LONG.
  - Entry: the signal bar's own real close price. Deliberately NOT a
    delayed zone-touch-then-confirm design like strategy4 — signal and
    entry are resolved on the SAME bar, so there is no window for a
    future close to leak into the recorded entry price (see strategy4's
    2026-08-02 bugfix note for what that bug looked like).
  - Stop: beyond the sweep wick extreme + 0.25x ATR(14,H4) buffer.
  - Exit: SAME vsim() as full_history_backtest.py / strategy4_swing_ob.py
    (bar-by-bar M1 loop) — NOT reimplemented. Collect signals once, sweep
    TP ratios in a second pass.
  - Time stop: 5 calendar days, same as strategy4, for comparability.
  - No D1 trend filter in this v1 — testing the raw fade hypothesis
    before stacking any other condition on top of it.

Run in Codespace: python -u strategy5_fade.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE       = 0.10
MAX_BARS_SWING = 5 * 24 * 60      # 5 calendar days of M1 bars
LEVEL_LOOKBACK = 20               # H4 bars — matches the Donchian test for comparability
ATR_LEN        = 14
ATR_BUFFER     = 0.25
RISK_PCT       = 0.5
START_BAL      = 70000
TP_SWEEP       = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]

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


# ── Same proven core as full_history_backtest.py / strategy4 — NOT reimplemented ──
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
    """Detect H4 liquidity-sweep fade signals. Signal and entry are resolved
    on the SAME bar (its own close) — no delayed multi-bar confirmation
    window, so there's no gap for a future price to leak into the entry."""
    m1 = _m1[k]; mi = m1.index

    h4 = m1.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h4 = h4[h4['open'] > 0]
    h4_atr = atr(h4)
    hl = list(h4.index)

    signals = []

    for i in range(LEVEL_LOOKBACK + 1, len(hl)):
        ts = hl[i]; bar = h4.iloc[i]
        window = h4.iloc[i-LEVEL_LOOKBACK:i]        # strictly prior bars only
        prior_hi = window['high'].max(); prior_lo = window['low'].min()
        buf = ATR_BUFFER * (h4_atr.iloc[i] if not np.isnan(h4_atr.iloc[i]) else 0)

        swept_hi = bar['high'] > prior_hi and bar['close'] < prior_hi
        swept_lo = bar['low']  < prior_lo and bar['close'] > prior_lo
        # if both trigger on the same bar (wide-range bar), skip — ambiguous
        if swept_hi and swept_lo:
            continue

        if swept_hi:
            entry = float(bar['close']); sl = float(bar['high']) + buf; d = -1
        elif swept_lo:
            entry = float(bar['close']); sl = float(bar['low']) - buf; d = 1
        else:
            continue

        entry_time = ts + pd.Timedelta(hours=4)     # this bar's own close — known, not future
        ep = mi.searchsorted(entry_time)
        if ep >= len(m1): continue

        signals.append({
            'instrument': k, 'dir': d, 'entry': entry, 'sl': sl,
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
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

# ── Collect signals ONCE per instrument ────────────────────────────────────────
all_signals = []
for k in loaded:
    print(f'  Scanning {k} for liquidity-sweep fades...', end=' ', flush=True)
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
