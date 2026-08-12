"""
scalp_play.py

Just playing with the M1 data — not a deployment candidate, no formal
holdout ceremony, just a quick look at whether there's anything here.

Idea: after 5 consecutive same-direction 1-minute closes (a short micro
burst), fade it — bet on a quick pullback. Tight stop, small target,
short hold (max 30 minutes). Classic scalp shape.

Honest expectation going in: this is a form of mean-reversion, same
general family as the liquidity-sweep fade that already failed tonight,
and scalping specifically eats spread cost harder than anything else
tried tonight since the target is tiny relative to the fixed per-trade
cost. Don't be surprised if it's bad — the point is to actually look,
not to guess from the couch.

Run in Codespace: python -u scalp_play.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE   = 0.10
STREAK_LEN = 5
HOLD_SWEEP = [1, 5, 10, 30]  # minutes
RISK_PCT   = 0.5
START_BAL  = 70000
TP_SWEEP   = [4.0, 5.0, 6.0]   # note: a 4-6R move within 1-5 minutes is a big ask —
                               # expect very few/zero hits at the tight end of HOLD_SWEEP

FILES = {
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST = {'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,'GOLD':0.08}

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


def collect_signals(k):
    m1 = _m1[k]; mi = m1.index
    cl = m1['close'].values; hi = m1['high'].values; lo = m1['low'].values
    up = cl[1:] > cl[:-1]
    signals = []

    i = STREAK_LEN
    n = len(m1)
    while i < n - 1:
        # check if the last STREAK_LEN closes were all same direction
        window = up[i-STREAK_LEN:i]
        if window.all():          # streak of ups -> fade -> SHORT
            direction = -1
        elif not window.any():    # streak of downs -> fade -> LONG
            direction = 1
        else:
            i += 1
            continue

        # FIXED: entry price is bar i's close, so ep must be i (vsim simulates
        # from ep+1 onward) — it was i+1, which skipped bar i+1's high/low
        # entirely, the single most dangerous bar for an immediate stop-out
        # on a tight scalp stop. That gap was giving free, unrisked bars.
        if i >= n - 1: break
        entry = float(cl[i])
        # stop = recent 5-bar extreme + a couple pips buffer, scaled to instrument
        recent_range = float(hi[i-STREAK_LEN:i].max() - lo[i-STREAK_LEN:i].min())
        buf = max(recent_range * 0.2, entry * 0.00005)
        if direction == 1:
            sl = float(lo[i-STREAK_LEN:i].min()) - buf
        else:
            sl = float(hi[i-STREAK_LEN:i].max()) + buf

        signals.append({
            'instrument': k, 'dir': direction, 'entry': entry, 'sl': sl,
            'entry_time': mi[i], 'ep': i,
        })
        i += STREAK_LEN   # skip past this streak, don't re-trigger mid-streak

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
    print(f'  {label:<{width}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  '
          f'R={total_r:>+9.2f}  £{gbp:>+10,.0f}')


print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

all_signals = []
for k in loaded:
    print(f'  Scanning {k} for {STREAK_LEN}-bar streak fades...', end=' ', flush=True)
    sig = collect_signals(k)
    print(f'{len(sig)} signals')
    all_signals.extend(sig)

print(f'\nTotal raw signals: {len(all_signals)}')

for hold_min in HOLD_SWEEP:
    print(f'\n{"#"*60}')
    print(f'  MAX HOLD = {hold_min} minute(s)')
    print(f'{"#"*60}')
    for tp_r in TP_SWEEP:
        trades = []
        for s in all_signals:
            r_gross, hold_bars = vsim(s['instrument'], s['ep'], s['dir'], s['entry'], s['sl'], tp_r, hold_min)
            r_net = r_gross - COST[s['instrument']] - SLIPPAGE
            trades.append(r_net)
        r_all = np.array(trades)
        n, wr, pf, tot = stats(r_all)
        print(f'  TP={tp_r}R:', end=' ')
        print_row('', n, wr, pf, tot, width=0)

print('\nDone. Just a look, not a verdict — take it for what it is.')
