"""
backtest_usdjpy_pb.py
USDJPY Pin Bar Only — matches EA InpStrategy = PinBar
H1 pin bar detection -> M1 breakout entry, 4R TP

Pin bar rules (matching EA):
  wick >= 2.0 x body
  wick >= 0.5 x full bar range
  Hammer (lower wick) -> buy break of high
  Shooting star (upper wick) -> sell break of low

Run: python backtest_usdjpy_pb.py
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
FILE      = 'USDJPY_M1_oanda.csv'
COST      = 0.08
SLIPPAGE  = 0.10
TP_R      = 4.0
MAX_PD    = 3
WIN_HOURS = 3
ACCOUNT   = 70_000
RISK_FRAC = 0.005

WICK_BODY  = 2.0
WICK_RANGE = 0.5

H1_HOURS = {0, 1, 2, 8, 9}
H1_SKIP  = frozenset({4})  # no Friday

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')

# ── LOAD ──────────────────────────────────────────────────────────────────────
print('Loading USDJPY M1...')
df = pd.read_csv(FILE)
df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
df = df.set_index('time').sort_index()
for c in ['open','high','low','close']:
    df[c] = pd.to_numeric(df[c], errors='coerce')
m1 = df.dropna()
mi = m1.index
print(f'  {len(m1):,} bars  [{m1.index[0].year}-{m1.index[-1].year}]')

# ── SIMULATOR ─────────────────────────────────────────────────────────────────
def vsim(ep, d, entry, sl, max_bars=480):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep + 1 + max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]
    lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry + sl_d * TP_R if d == 1 else entry - sl_d * TP_R
    if d == 1:
        sl_i = int(np.argmax(lo <= sl)) if np.any(lo <= sl) else max_bars
        tp_i = int(np.argmax(hi >= tp)) if np.any(hi >= tp) else max_bars
    else:
        sl_i = int(np.argmax(hi >= sl)) if np.any(hi >= sl) else max_bars
        tp_i = int(np.argmax(lo <= tp)) if np.any(lo <= tp) else max_bars
    if tp_i <= sl_i: return TP_R
    if sl_i < max_bars: return -1.0
    lp = m1['close'].values[end - 1]
    return ((lp - entry) if d == 1 else (entry - lp)) / sl_d

# ── PIN BAR DETECTOR ──────────────────────────────────────────────────────────
def pin_bar_direction(o, h, l, c):
    body      = abs(c - o)
    full_rng  = h - l
    if full_rng <= 0: return 0
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    # Bearish (shooting star): upper wick dominates -> sell break of low
    if (upper_wick >= WICK_BODY * max(body, full_rng * 0.001) and
            upper_wick >= WICK_RANGE * full_rng):
        return -1
    # Bullish (hammer): lower wick dominates -> buy break of high
    if (lower_wick >= WICK_BODY * max(body, full_rng * 0.001) and
            lower_wick >= WICK_RANGE * full_rng):
        return 1
    return 0

# ── COLLECT ───────────────────────────────────────────────────────────────────
def collect(start=None, end=None):
    h1 = m1.resample('1h').agg(
        {'open':'first','high':'max','low':'min','close':'last'}
    ).dropna()
    h1 = h1[h1['open'] > 0]
    if start: h1 = h1[h1.index >= start]
    if end:   h1 = h1[h1.index < end]
    hl = list(h1.index)
    out = []; day_count = {}
    for i in range(len(hl)):
        ts = hl[i]
        if ts.dayofweek in H1_SKIP: continue
        if ts.hour not in H1_HOURS: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue
        bar = h1.iloc[i]
        pb_dir = pin_bar_direction(
            float(bar['open']), float(bar['high']),
            float(bar['low']),  float(bar['close'])
        )
        if pb_dir == 0: continue
        pb_h = float(bar['high']); pb_l = float(bar['low'])
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0: continue
        for j in range(len(window)):
            b = window.iloc[j]
            if pb_dir == 1 and b['high'] > pb_h:
                d = 1; entry_p = pb_h; sl = pb_l
            elif pb_dir == -1 and b['low'] < pb_l:
                d = -1; entry_p = pb_l; sl = pb_h
            else:
                continue
            ep = mi.searchsorted(window.index[j])
            if ep >= len(m1): break
            day_count[date_k] = day_count.get(date_k, 0) + 1
            r_gross = vsim(ep, d, entry_p, sl)
            out.append({
                'date': date_k,
                'year': ts.year,
                'r_net': r_gross - COST - SLIPPAGE,
            })
            break
    return out

def pf(r):
    r = np.asarray(r, float); w = r[r>0]; l = r[r<=0]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0

def wr(r):
    r = np.asarray(r, float)
    return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

# ── RUN ───────────────────────────────────────────────────────────────────────
print('Collecting all-years signals...')
all_trades = collect()
print(f'  Total: {len(all_trades)} pin bar trades')

oos = [t for t in all_trades if OOS_START.date() <= t['date'] < OOS_END.date()]
r_oos = np.asarray([t['r_net'] for t in oos], float)
oos_days = (OOS_END - OOS_START).days / 7 * 5

print()
print('=' * 60)
print('  USDJPY PIN BAR ONLY  |  TP = 4R')
print('=' * 60)
print(f'  Full period trades:  {len(all_trades)}')
print()
print(f'  OOS 2022-2025:')
print(f'    Trades:            {len(r_oos)}')
print(f'    Trades/day:        {len(r_oos)/oos_days:.2f}')
print(f'    Win rate:          {wr(r_oos):.1f}%')
print(f'    Profit factor:     {pf(r_oos):.2f}')
print(f'    Expectancy/trade:  {r_oos.mean():+.3f}R')
daily_pnl = r_oos.mean() * (len(r_oos)/oos_days) * ACCOUNT * RISK_FRAC
print(f'    Expected daily:    GBP {daily_pnl:,.0f}')

print()
print(f'  Year by year:')
print(f'  {"Year":>6}  {"Trades":>7}  {"WR":>7}  {"PF":>7}  {"Status":>10}')
print(f'  {"-"*45}')
for yr in range(2018, 2026):
    t_yr = [t for t in all_trades if t['year'] == yr]
    r = np.asarray([t['r_net'] for t in t_yr], float)
    if len(r) < 5: continue
    label = 'IS' if yr < 2022 else 'OOS'
    status = 'POSITIVE' if pf(r) >= 1.5 else ('MARGINAL' if pf(r) >= 1.0 else 'NEGATIVE')
    print(f'  {yr:>6}  {len(r):>7}  {wr(r):>6.1f}%  {pf(r):>7.2f}  [{label}] {status}')

print()
print(f'  vs IB+PB combined (from full suite):')
print(f'    IB+PB WR was 38.5%, PF 2.03')
print(f'    PB only WR: {wr(r_oos):.1f}%, PF: {pf(r_oos):.2f}')
print('=' * 60)
print('Done.')
