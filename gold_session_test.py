"""
gold_session_test.py

Follow-up on the one thread that showed something in the FX session
test: GOLD specifically was positive in the Asian (PF 1.04) and NY
(PF 1.08) sessions, while EURUSD/GBPUSD/USDJPY were negative in every
session. This tests gold on its own, properly, with a locked holdout
from the start — not added after the fact once something looked good,
like the equity test needed. Genuinely different asset/correlation
profile from the equity-intraday result if it holds up: gold is a
safe-haven commodity, not equity beta.

Same mechanics as fx_session_test.py: 3 non-overlapping UTC sessions
(Asian 00-08, London 08-13, NY 13-24), always long each session,
ATR-based R-normalization, price-point costs normalized by the same
stop distance.

IS/OOS SPLIT — LOCKED BEFORE ANY RESULTS ARE SEEN:
  In-sample:  data start -> 2025-02-01
  Holdout:    2025-02-01 -> present (touched ONCE)

Run in Codespace: python -u gold_session_test.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ATR_LEN   = 20
ATR_MULT  = 3.0
RISK_PCT  = 0.5
START_BAL = 70000
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')

FILE = 'XAUUSD_M1_oanda.csv'
COST_POINTS = 0.25

SESSIONS = {
    'ASIAN':  (0, 8),
    'LONDON': (8, 13),
    'NY':     (13, 24),
}

_m1 = None

def load():
    global _m1
    if not os.path.exists(FILE): return False
    df = pd.read_csv(FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1 = df.dropna()
    return True


def atr_daily(daily, n=ATR_LEN):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def build_sessions():
    m1 = _m1; mi = m1.index
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    rows = []
    for i in range(ATR_LEN + 1, len(daily)):
        day = daily.index[i]
        atr_val = d_atr.iloc[i-1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        stop_dist = ATR_MULT * atr_val
        cost_r = COST_POINTS / stop_dist

        row = {'date': day, 'year': day.year}
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


print('Loading GOLD M1 data...')
if not load():
    print('File not found.')
    raise SystemExit(1)

rows = build_sessions()
df = pd.DataFrame(rows)
print(f'Total trading days: {len(df)}')

is_df  = df[df['date'] <  IS_OOS_SPLIT]
oos_df = df[df['date'] >= IS_OOS_SPLIT]

for sess in SESSIONS:
    leg = sess + '_r'
    print(f'\n{"="*74}')
    print(f'  {sess} SESSION — GOLD')
    print(f'{"="*74}')

    n, wr, pf, tot = stats(is_df[leg].values)
    print('  IN-SAMPLE  (data start -> 2025-02-01):')
    print_row('    ALL', n, wr, pf, tot)
    by_year = {}
    for _, row in is_df.iterrows(): by_year.setdefault(row['year'], []).append(row[leg])
    for yr in sorted(by_year):
        rv = np.array(by_year[yr]); n, wr, pf, tot = stats(rv)
        flag = ' <- LOSING' if tot < 0 else ''
        print_row('      ' + str(yr) + flag, n, wr, pf, tot)

    n, wr, pf, tot = stats(oos_df[leg].values)
    print('  HOLDOUT  (2025-02-01 -> present — touched ONCE):')
    print_row('    ALL', n, wr, pf, tot)

print('\nDone.')
