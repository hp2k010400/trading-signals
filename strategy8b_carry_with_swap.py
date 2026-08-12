"""
strategy8b_carry_with_swap.py

Same as strategy8_carry.py, ONE addition: mechanical swap/rollover income.

Why: strategy8 only tested whether the higher-yielding currency also
tends to appreciate in price (uncovered interest parity violation) —
and found nothing (PF 0.58 IS, 0.52 holdout, every year losing). But
that's only HALF of what a real carry trade earns. The other half is
the swap/rollover credit paid daily just for holding the higher-yield
side, which is mechanical, not statistical — it accrues regardless of
what price does. strategy8 captured zero of that. This version adds it.

Direction is always chosen to be on the high-yield side (by construction
of the signal: direction=1 requires the long leg to yield more, and
direction=-1 requires the short leg to yield more), so swap income is
ALWAYS a positive addition here, never a cost — that's the whole
mechanical point of a carry trade.

APPROXIMATION, stated honestly: swap is estimated as
    swap_R = (|rate_diff_pct| / 100) * (days_held / 365) * entry_price / stop_distance
This is a research-level approximation of the standard swap accrual
formula (rate differential x notional x time / 365), normalized into R
the same way everything else in this project is. It is NOT a
broker-exact calculation (real brokers apply triple swap on
Wednesdays for weekend rollover, and add their own markup) — it's
meant to get the right order of magnitude, not the exact number a
live account would see.

IS/OOS SPLIT — SAME rule as strategy8 and strategy6/6b: this holdout
was NOT fresh going in (the decision to add swap was made after seeing
strategy8's full result), so treat it as a second opinion, not blind
evidence, same honesty rule as strategy6b.

Run in Codespace: python -u strategy8b_carry_with_swap.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

SLIPPAGE     = 0.10
ATR_LEN      = 20
ATR_MULT     = 6.0
RISK_PCT     = 0.5
START_BAL    = 70000
TP_DISABLE   = 100.0
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

PAIRS = {
    'EURUSD': ('EUR', 'USD', 1),
    'GBPUSD': ('GBP', 'USD', 1),
    'USDJPY': ('USD', 'JPY', 1),
}
FILES = {
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
}
COST = {'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08}
RATE_FILES = {'USD':'rate_USD.csv','EUR':'rate_EUR.csv','GBP':'rate_GBP.csv','JPY':'rate_JPY.csv'}

_m1 = {}
_rates = {}

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

def load_rate(ccy):
    fn = RATE_FILES[ccy]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    date_col = df.columns[0]; val_col = df.columns[1]
    df[date_col] = pd.to_datetime(df[date_col], utc=True)
    df = df.set_index(date_col).sort_index()
    s = pd.to_numeric(df[val_col], errors='coerce').dropna()
    monthly = s.resample('ME').last().ffill()
    _rates[ccy] = monthly
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
    long_ccy, short_ccy, sign = PAIRS[k]
    if long_ccy not in _rates or short_ccy not in _rates: return []

    m1 = _m1[k]; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    diff = (_rates[long_ccy] - _rates[short_ccy]) * sign

    first_ts = mi[0]; last_ts = mi[-1]
    starts = pd.date_range(first_ts.normalize().replace(day=1), last_ts, freq='MS', tz='UTC')

    signals = []
    for si in range(len(starts) - 1):
        start = starts[si]; next_start = starts[si + 1]

        prior_val = diff.asof(start - pd.Timedelta(days=1))
        if pd.isna(prior_val) or prior_val == 0: continue
        direction = 1 if prior_val > 0 else -1

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
            'rate_diff_pct': abs(prior_val),   # always positive — direction already guarantees the carry side
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
print('Loading FX M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

print('Loading rate data...')
for ccy in RATE_FILES:
    ok = load_rate(ccy)
    print(f'  {ccy}: {"OK" if ok else "MISSING"}')

# ── Collect signals ONCE per instrument ────────────────────────────────────────
all_signals = []
for k in loaded:
    print(f'  Scanning {k} for carry signals...', end=' ', flush=True)
    sig = collect_signals(k)
    print(f'{len(sig)} signals')
    all_signals.extend(sig)

print(f'\nTotal raw signals: {len(all_signals)}')
if len(all_signals) < 60:
    print('WARNING: fewer than 60 signals total — treat any PF here as unreliable, more than usual.')

# ── Run the ONE fixed rule, now with swap income added ─────────────────────────
avg_swap_r = []
trades = []
for s in all_signals:
    r_gross, hold_bars = vsim(s['instrument'], s['ep'], s['dir'], s['entry'], s['sl'],
                               TP_DISABLE, s['max_bars'])
    sl_d = abs(s['entry'] - s['sl'])
    days_held = hold_bars / (24 * 60)
    swap_r = (s['rate_diff_pct'] / 100) * (days_held / 365) * s['entry'] / sl_d
    avg_swap_r.append(swap_r)
    r_net = r_gross - COST[s['instrument']] - SLIPPAGE + swap_r
    trades.append({
        'instrument': s['instrument'], 'year': s['entry_time'].year,
        'entry_time': s['entry_time'], 'r_net': r_net,
    })

print(f'Average swap contribution per trade: {np.mean(avg_swap_r):+.4f}R '
      f'(median {np.median(avg_swap_r):+.4f}R, max {np.max(avg_swap_r):+.4f}R)')

is_trades  = [t for t in trades if t['entry_time'] <  IS_OOS_SPLIT]
oos_trades = [t for t in trades if t['entry_time'] >= IS_OOS_SPLIT]

print(f'\n{"="*74}')
print('  IN-SAMPLE  (data start -> 2025-02-01)')
print(f'{"="*74}')
r_is = np.array([t['r_net'] for t in is_trades])
n, wr, pf, tot = stats(r_is)
print_row('ALL PAIRS', n, wr, pf, tot)
by_year = {}
for t in is_trades: by_year.setdefault(t['year'], []).append(t['r_net'])
for yr in sorted(by_year):
    rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('  ' + str(yr) + flag, n, wr, pf, tot)

print(f'\n{"="*74}')
print('  HOLDOUT — 2025-02-01 -> present (NOT fresh this time — see docstring)')
print(f'{"="*74}')
r_oos = np.array([t['r_net'] for t in oos_trades])
n, wr, pf, tot = stats(r_oos)
print_row('ALL PAIRS', n, wr, pf, tot)
by_year = {}
for t in oos_trades: by_year.setdefault(t['year'], []).append(t['r_net'])
for yr in sorted(by_year):
    rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('  ' + str(yr) + flag, n, wr, pf, tot)

print('\nDone.')
