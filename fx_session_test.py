"""
fx_session_test.py

Same methodology that found the one real result tonight (overnight vs
intraday decomposition for equities), applied to a genuinely different,
less-correlated asset class: FX. Equities have a clean open/close; FX
trades ~24h, so this decomposes the day into 3 non-overlapping sessions
instead of 2 day-parts — same underlying question: does one session
structurally carry the return while others drag, the same way "trading
hours" did for equities.

Sessions (UTC, clean non-overlapping split covering the full day):
  Asian:  00:00-08:00
  London: 08:00-13:00
  NY:     13:00-24:00 (includes the London/NY overlap, the most liquid
          window, folded in rather than split further to keep this to
          3 clean legs — same simplicity as the 2-leg equity version)

Instruments: EURUSD, GBPUSD, USDJPY, GOLD — the FX majors + gold, a
different correlation structure from the 4 equity indices already
tested (this is explicitly the point: find something that DOESN'T move
with "long equities during the day," not another version of it).

Mechanical rules (no discretion):
  - Each leg: always long from that session's start price to its end
    price, every single trading day, no signal/condition beyond that.
  - Stop: entry +/- 3x ATR(20, daily) for risk-normalized R-multiples,
    consistent with everything else tonight (tail-risk cap, not the
    primary exit — primary exit is always the fixed session boundary).
  - Costs defined in raw price points, normalized by the SAME stop
    distance as the return (learned from the earlier bug in the equity
    version — not reusing pre-scaled R-units from a different
    convention this time).

No IS/OOS holdout ceremony on the first pass — same reasoning as the
equity test originally: checking whether a structural effect shows up
at all, not fitting a discovered pattern. If any leg comes back
positive, it gets the same locked-holdout treatment before being
trusted, exactly like the equity result did once it looked real.

Run in Codespace: python -u fx_session_test.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN   = 20
ATR_MULT  = 3.0
RISK_PCT  = 0.5
START_BAL = 70000

FILES = {
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
# Raw spread+slippage cost in PRICE POINTS, normalized by the same stop
# distance as the return — same fix applied to the equity version.
COST_POINTS = {'EURUSD': 0.00012, 'GBPUSD': 0.00015, 'USDJPY': 0.012, 'GOLD': 0.25}

SESSIONS = {
    'ASIAN':  (0, 8),
    'LONDON': (8, 13),
    'NY':     (13, 24),
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


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def build_sessions(k):
    m1 = _m1[k]; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    rows = []
    for i in range(ATR_LEN + 1, len(daily)):
        day = daily.index[i]
        atr_val = d_atr.iloc[i-1]   # ATR as of yesterday's close — no lookahead
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = COST_POINTS[k] / stop_dist

        row = {'instrument': k, 'date': day.date(), 'year': day.year}
        valid = True
        for name, (h_start, h_end) in SESSIONS.items():
            start_ts = day + pd.Timedelta(hours=h_start)
            end_ts   = day + pd.Timedelta(hours=h_end) if h_end < 24 else day + pd.Timedelta(days=1)
            s_idx = mi.searchsorted(start_ts)
            e_idx = mi.searchsorted(end_ts) - 1
            if s_idx >= len(m1) or e_idx >= len(m1) or e_idx <= s_idx:
                valid = False; break
            p_start = m1['close'].values[s_idx]
            p_end   = m1['close'].values[e_idx]
            if p_start <= 0:
                valid = False; break
            ret = p_end / p_start - 1
            r = ret * p_start / stop_dist - cost_r
            row[name + '_r'] = r
        if valid:
            rows.append(row)
    return rows


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


print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')

all_rows = []
for k in loaded:
    print(f'  Building session legs for {k}...', end=' ', flush=True)
    rows = build_sessions(k)
    print(f'{len(rows)} trading days')
    all_rows.extend(rows)

df = pd.DataFrame(all_rows)
print(f'\nTotal trading days across all instruments: {len(df)}')

for sess in SESSIONS:
    leg = sess + '_r'
    print(f'\n{"="*74}')
    print(f'  {sess} SESSION')
    print(f'{"="*74}')
    r_all = df[leg].values
    n, wr, pf, tot = stats(r_all)
    print_row('ALL INSTRUMENTS', n, wr, pf, tot)

    by_inst = {}
    for _, row in df.iterrows(): by_inst.setdefault(row['instrument'], []).append(row[leg])
    for inst in sorted(by_inst, key=lambda x: -sum(by_inst[x])):
        rv = np.array(by_inst[inst]); n, wr, pf, tot = stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('  ' + inst + flag, n, wr, pf, tot)

    by_year = {}
    for _, row in df.iterrows(): by_year.setdefault(row['year'], []).append(row[leg])
    print()
    for yr in sorted(by_year):
        rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('    ' + str(yr) + flag, n, wr, pf, tot)

print('\nDone.')
