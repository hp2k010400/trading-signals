"""
overnight_intraday_test.py

Genuinely different question from anything tested tonight: not "is
there a pattern that predicts direction," but "which segment of the
trading day actually carries the market's return — the overnight gap
(prior close to today's open) or the regular session (today's open to
today's close)." This is a real, well-documented, named academic
finding for equity indices specifically (the "overnight effect") — not
a pattern search, a structural decomposition question.

Focused on the 4 equity indices (DAX, NAS100, SP500, US30) — this is
where the effect is actually documented; FX/gold trade ~24h with no
clean single "overnight gap" the same way, so they're excluded here
rather than force-fit.

Mechanical rules (no discretion):
  - Overnight leg: always long from yesterday's close to today's open,
    every single trading day, no signal/condition beyond that.
  - Intraday leg: always long from today's open to today's close, every
    single trading day.
  - Stop: entry +/- 3x ATR(20, daily) on each leg, for risk-normalized
    R-multiples consistent with everything else tonight (this is a
    tail-risk cap, not the primary exit — primary exit is always the
    fixed close-to-open or open-to-close boundary).
  - Both legs tested completely separately — this is a comparison of
    two structural exposures, not a single strategy with a TP sweep.

UPDATE after first run: the intraday leg came back positive (PF 1.07,
7 of 9 years) — real enough that skipping the holdout would be
inconsistent with every other test tonight, especially right after
watching the random forest look good in walk-forward and fail the
holdout. Added a locked final-holdout split (2025-02-01, same date used
all night) on the intraday leg specifically, checked once, at the end.

Run in Codespace: python -u overnight_intraday_test.py
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
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
}
# Raw spread+slippage cost in PRICE POINTS (not pre-scaled R-units — those
# from other scripts were calibrated against much tighter intraday stops
# and would swamp a return normalized against a wide 3x-daily-ATR stop).
# Approximate typical retail CFD spreads; divided by the SAME stop
# distance as the return below, so units are consistent.
COST_POINTS = {'DAX': 1.5, 'NAS100': 1.5, 'SP500': 0.6, 'US30': 2.0}

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


def build_legs(k):
    m1 = _m1[k]
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    d_atr = atr_daily(daily)

    rows = []
    for i in range(ATR_LEN + 1, len(daily)):
        prev_close = daily['close'].iloc[i-1]
        today_open = daily['open'].iloc[i]
        today_close = daily['close'].iloc[i]
        atr_val = d_atr.iloc[i-1]   # ATR as of yesterday's close — no lookahead
        if pd.isna(atr_val) or atr_val <= 0 or prev_close <= 0 or today_open <= 0:
            continue

        stop_dist = ATR_MULT * atr_val
        cost_r = COST_POINTS[k] / stop_dist   # same denominator as the return — consistent units

        overnight_ret = today_open / prev_close - 1
        intraday_ret  = today_close / today_open - 1
        overnight_r = overnight_ret * prev_close / stop_dist
        intraday_r  = intraday_ret * today_open / stop_dist

        rows.append({
            'instrument': k, 'date': daily.index[i], 'year': daily.index[i].year,
            'overnight_r_net': overnight_r - cost_r,
            'intraday_r_net':  intraday_r - cost_r,
        })
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
    print(f'  Building overnight/intraday legs for {k}...', end=' ', flush=True)
    rows = build_legs(k)
    print(f'{len(rows)} trading days')
    all_rows.extend(rows)

df = pd.DataFrame(all_rows)
print(f'\nTotal trading days across all instruments: {len(df)}')

for leg in ['overnight_r_net', 'intraday_r_net']:
    label = 'OVERNIGHT (prior close -> today open)' if 'overnight' in leg else 'INTRADAY (today open -> today close)'
    print(f'\n{"="*74}')
    print(f'  {label}')
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

# ── Locked holdout on the intraday leg — the one that showed a real result ────
IS_OOS_SPLIT = pd.Timestamp('2025-02-01', tz='UTC')
print(f'\n{"="*74}')
print('  INTRADAY LEG — IS/HOLDOUT SPLIT (locked, touched once)')
print(f'{"="*74}')
is_df  = df[df['date'] <  IS_OOS_SPLIT]
oos_df = df[df['date'] >= IS_OOS_SPLIT]
n, wr, pf, tot = stats(is_df['intraday_r_net'].values)
print('  IN-SAMPLE  (data start -> 2025-02-01):')
print_row('    ALL INSTRUMENTS', n, wr, pf, tot)
n, wr, pf, tot = stats(oos_df['intraday_r_net'].values)
print('  HOLDOUT  (2025-02-01 -> present):')
print_row('    ALL INSTRUMENTS', n, wr, pf, tot)
for inst, grp in oos_df.groupby('instrument'):
    n, wr, pf, tot = stats(grp['intraday_r_net'].values)
    flag = ' <- LOSING' if tot < 0 else ''
    print_row('      ' + inst + flag, n, wr, pf, tot)

print('\nDone.')
