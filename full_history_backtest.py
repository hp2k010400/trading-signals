"""
full_history_backtest.py

Full system backtest — all available OANDA M1 data.
Matches live EA v2.07 exactly: IB + PB signals, 4R TP, 8h time stop,
correct USDJPY Asian hours, no news filter.

Shows: overall · per-year · per-instrument · monthly

Run in Codespace: python -u full_history_backtest.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

BASE_TP    = 4.0
SLIPPAGE   = 0.10
WIN_HOURS  = 3
MAX_BARS   = 480
MAX_PD     = 3
WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015
RISK_PCT   = 0.5
START_BAL  = 70000

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

def vsim(k, ep, d, entry, sl):
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0, MAX_BARS
    end = min(ep + 1 + MAX_BARS, len(m1))
    slc = m1.iloc[ep+1:end]
    if len(slc) == 0: return -1.0, MAX_BARS
    hi = slc['high'].values; lo = slc['low'].values; cl = slc['close'].values
    tp = entry + sl_d * BASE_TP if d == 1 else entry - sl_d * BASE_TP
    for i in range(len(hi)):
        if d == 1:
            if hi[i] >= tp: return BASE_TP, i + 1
            if lo[i] <= sl: return -1.0, i + 1
        else:
            if lo[i] <= tp: return BASE_TP, i + 1
            if hi[i] >= sl: return -1.0, i + 1
    r = (cl[-1]-entry)/sl_d if d==1 else (entry-cl[-1])/sl_d
    return r, len(slc)

def collect(k):
    m1 = _m1[k]; mi = m1.index
    skip    = H1_SKIP.get(k, frozenset())
    p_hours = H1_HOURS.get(k, {8,9,13,14})
    h1 = m1.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); day_count = {}; trades = []

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
        r_gross, hold_bars = vsim(k, ep, d, e, sl)
        r_net = r_gross - COST[k] - SLIPPAGE
        day_count[date_k] = day_count.get(date_k, 0) + 1
        trades.append({
            'instrument': k,
            'entry_time': entry_time,
            'year':       entry_time.year,
            'month':      entry_time.strftime('%Y-%m'),
            'r_net':      r_net,
        })
    return trades


def stats(r_arr):
    if len(r_arr) == 0: return 0, 0.0, 0.0, 0.0
    w = r_arr[r_arr > 0]; l = r_arr[r_arr <= 0]
    pf = round(w.sum()/abs(l.sum()), 2) if len(l) and l.sum() != 0 else 0.0
    wr = round(len(w)/len(r_arr)*100, 1)
    return len(r_arr), wr, pf, r_arr.sum()

DIV = '─' * 74
RPR = START_BAL * RISK_PCT / 100.0


def print_row(label, n, wr, pf, total_r, width=20):
    gbp = total_r * RPR
    print(f'  {label:<{width}}  N={n:>5}  WR={wr:>5.1f}%  PF={pf:>5.2f}  '
          f'R={total_r:>+9.2f}  £{gbp:>+10,.0f}')


# ── Load ─────────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded {len(loaded)} instruments: {loaded}')
dates = [(k, _m1[k].index[0].date(), _m1[k].index[-1].date()) for k in loaded]
for k, s, e in dates:
    print(f'  {k}: {s} → {e}')

# ── Collect ───────────────────────────────────────────────────────────────────
all_trades = []
for k in loaded:
    print(f'  Running {k}...', end=' ', flush=True)
    t = collect(k)
    print(f'{len(t)} trades')
    all_trades.extend(t)

print(f'\nTotal trades: {len(all_trades)}')

# ── Overall ───────────────────────────────────────────────────────────────────
print(f'\n{"="*74}')
print('  FULL HISTORY — OVERALL')
print(f'{"="*74}')
r_all = np.array([t['r_net'] for t in all_trades])
n, wr, pf, tot = stats(r_all)
print_row('ALL INSTRUMENTS', n, wr, pf, tot)

# ── Per instrument ─────────────────────────────────────────────────────────────
print(f'\n  {"─"*70}')
print(f'  {"Instrument":<20}  {"N":>5}  {"WR":>7}  {"PF":>7}  {"Total R":>9}  {"Est £":>11}')
print(f'  {"─"*70}')
by_inst = {}
for t in all_trades:
    by_inst.setdefault(t['instrument'], []).append(t['r_net'])
for k in sorted(by_inst, key=lambda x: -sum(by_inst[x])):
    rv = np.array(by_inst[k])
    n, wr, pf, tot = stats(rv)
    print_row(k, n, wr, pf, tot)

# ── Per year ──────────────────────────────────────────────────────────────────
print(f'\n{"="*74}')
print('  YEAR-BY-YEAR BREAKDOWN')
print(f'{"="*74}')
print(f'  {"Year":<20}  {"N":>5}  {"WR":>7}  {"PF":>7}  {"Total R":>9}  {"Est £":>11}')
print(f'  {"─"*70}')
by_year = {}
for t in all_trades:
    by_year.setdefault(t['year'], []).append(t['r_net'])
for yr in sorted(by_year):
    rv = np.array(by_year[yr])
    n, wr, pf, tot = stats(rv)
    flag = ' ◄ LOSING' if tot < 0 else ''
    print_row(str(yr) + flag, n, wr, pf, tot)

# ── Monthly ───────────────────────────────────────────────────────────────────
print(f'\n{"="*74}')
print('  MONTHLY BREAKDOWN')
print(f'{"="*74}')
print(f'  {"Month":<20}  {"N":>5}  {"WR":>7}  {"PF":>7}  {"Total R":>9}  {"Est £":>11}')
print(f'  {"─"*70}')
by_month = {}
for t in all_trades:
    by_month.setdefault(t['month'], []).append(t['r_net'])
for mo in sorted(by_month):
    rv = np.array(by_month[mo])
    n, wr, pf, tot = stats(rv)
    flag = ' ✗' if tot < 0 else ''
    print_row(mo + flag, n, wr, pf, tot)

# ── Summary ───────────────────────────────────────────────────────────────────
years = sorted(by_year.keys())
losing_years = [y for y in years if sum(by_year[y]) < 0]
winning_months = sum(1 for m in by_month if sum(by_month[m]) > 0)
total_months = len(by_month)

print(f'\n{"="*74}')
print(f'  Profitable months: {winning_months} / {total_months} '
      f'({round(winning_months/total_months*100,1)}%)')
print(f'  Losing years: {losing_years if losing_years else "none"}')
print(f'  Best year:  {max(by_year, key=lambda y: sum(by_year[y]))} '
      f'({sum(by_year[max(by_year, key=lambda y: sum(by_year[y]))]):.1f}R  '
      f'£{sum(by_year[max(by_year, key=lambda y: sum(by_year[y]))])*RPR:,.0f})')
print(f'  Worst year: {min(by_year, key=lambda y: sum(by_year[y]))} '
      f'({sum(by_year[min(by_year, key=lambda y: sum(by_year[y]))]):.1f}R  '
      f'£{sum(by_year[min(by_year, key=lambda y: sum(by_year[y]))])*RPR:,.0f})')
print(f'{"="*74}')
print('Done.')
