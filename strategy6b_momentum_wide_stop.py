"""
strategy6b_momentum_wide_stop.py

Strategy 6b — same as strategy6_momentum.py, ONE change: ATR_MULT 3.0 -> 6.0.

Why: strategy6's result (IS PF 0.80, holdout PF 0.96, uniformly losing
across 6 full years) failed cleanly, no bug. Hypothesis for the failure:
a 3x DAILY ATR stop is tight for a position meant to be held a full
month — normal monthly noise can produce a 3x-ATR pullback in the
middle of a trend that's still intact, so the stop may have been
cutting winners before the trend had room to prove itself.

HONESTY NOTE on the holdout: the decision to widen the stop was informed
by having already seen strategy6's full result (both IS and holdout),
so this is not a blind test in the way strategy6 was. The multiplier
value itself (6.0, a straight doubling) was picked by reasoning before
running this script, not by scanning multiple values against the data —
but the holdout split below should be read as a second opinion, not
fresh, untouched evidence the way it was the first time. If this also
fails, that's a real answer. If it "passes," it needs a genuinely fresh
piece of data (or real forward paper-trading) before being trusted,
not just this rerun.

Everything else — signal, entry timing, exit mechanics, vsim() core,
IS/OOS split date — is identical to strategy6_momentum.py.

Run in Codespace: python -u strategy6b_momentum_wide_stop.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE     = 0.10
LOOKBACK_MO  = 12
ATR_LEN      = 20
ATR_MULT     = 6.0          # was 3.0 in strategy6 — see docstring
RISK_PCT     = 0.5
START_BAL    = 70000
TP_DISABLE   = 100.0        # effectively unreachable -> time-stop is the real exit
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


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def collect_signals(k):
    m1 = _m1[k]; mi = m1.index

    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    monthly_close = daily['close'].resample('ME').last()

    first_ts = mi[0]; last_ts = mi[-1]
    starts = pd.date_range(first_ts.normalize().replace(day=1), last_ts, freq='MS', tz='UTC')

    signals = []
    for si in range(len(starts) - 1):
        start = starts[si]; next_start = starts[si + 1]

        pos = monthly_close.index.searchsorted(start) - 1   # last monthly close strictly before `start`
        if pos < LOOKBACK_MO or pos >= len(monthly_close): continue
        this_close = monthly_close.iloc[pos]; past_close = monthly_close.iloc[pos - LOOKBACK_MO]
        if past_close == 0 or np.isnan(this_close) or np.isnan(past_close): continue
        ret = this_close / past_close - 1
        if ret == 0: continue
        direction = 1 if ret > 0 else -1

        idx_entry = mi.searchsorted(start)
        idx_next  = mi.searchsorted(next_start)
        if idx_entry >= len(m1) or idx_next <= idx_entry: continue
        max_bars = idx_next - idx_entry - 1
        if max_bars <= 0: continue

        atr_val = d_atr.asof(start - pd.Timedelta(days=1))
        if pd.isna(atr_val) or atr_val <= 0: continue

        entry_price = float(m1['close'].values[idx_entry])
        sl = entry_price - direction * ATR_MULT * atr_val

        signals.append({
            'instrument': k, 'dir': direction, 'entry': entry_price, 'sl': sl,
            'entry_time': mi[idx_entry], 'ep': idx_entry, 'max_bars': max_bars,
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
    print(f'  Scanning {k} for monthly momentum signals (wide stop)...', end=' ', flush=True)
    sig = collect_signals(k)
    print(f'{len(sig)} signals')
    all_signals.extend(sig)

print(f'\nTotal raw signals: {len(all_signals)}')
if len(all_signals) < 100:
    print('WARNING: fewer than 100 signals total — treat any PF here as unreliable.')

# ── Run the ONE fixed rule (no sweep) ───────────────────────────────────────────
trades = []
for s in all_signals:
    r_gross, hold_bars = vsim(s['instrument'], s['ep'], s['dir'], s['entry'], s['sl'],
                               TP_DISABLE, s['max_bars'])
    r_net = r_gross - COST[s['instrument']] - SLIPPAGE
    trades.append({
        'instrument': s['instrument'], 'year': s['entry_time'].year,
        'entry_time': s['entry_time'], 'r_net': r_net,
    })

is_trades  = [t for t in trades if t['entry_time'] <  IS_OOS_SPLIT]
oos_trades = [t for t in trades if t['entry_time'] >= IS_OOS_SPLIT]

print(f'\n{"="*74}')
print('  IN-SAMPLE  (data start -> 2025-02-01)')
print(f'{"="*74}')
r_is = np.array([t['r_net'] for t in is_trades])
n, wr, pf, tot = stats(r_is)
print_row('ALL INSTRUMENTS', n, wr, pf, tot)
by_year = {}
for t in is_trades: by_year.setdefault(t['year'], []).append(t['r_net'])
for yr in sorted(by_year):
    rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('  ' + str(yr) + flag, n, wr, pf, tot)

print(f'\n{"="*74}')
print('  HOLDOUT — 2025-02-01 -> present (NOT a fresh holdout this time — see docstring)')
print(f'{"="*74}')
r_oos = np.array([t['r_net'] for t in oos_trades])
n, wr, pf, tot = stats(r_oos)
print_row('ALL INSTRUMENTS', n, wr, pf, tot)
by_year = {}
for t in oos_trades: by_year.setdefault(t['year'], []).append(t['r_net'])
for yr in sorted(by_year):
    rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('  ' + str(yr) + flag, n, wr, pf, tot)

print('\nDone.')
