"""
backtest_goat_suite.py
M1GOATV2 — Full Backtest Suite
H1 Inside Bar -> M1 breakout entry, 4R TP (matching live EA settings)

Sections:
  1. Full system backtest — all available instruments, OOS 2022-2025
  2. Walk-forward — year by year consistency check
  3. Monte Carlo — FTMO 70k challenge pass rate (using actual OOS stats)

Instruments with M1 data: DAX, NAS100, SP500, EURUSD, GBPUSD, GOLD
Missing M1 data (not in backtest): USDJPY, NATGAS, US30
Note: USDJPY uses Pin Bar only in EA; others use IB + Pin Bar

Run: python backtest_goat_suite.py
"""
import pandas as pd
import numpy as np
import os
import warnings
from datetime import date
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
TP_R      = 4.0     # EA InpTPR = 4.0
SLIPPAGE  = 0.10    # R slippage per trade
MAX_PD    = 3       # EA InpMaxPerDay = 3
WIN_HOURS = 3       # EA hours after signal to watch for breakout
ACCOUNT   = 70_000  # GBP - new account starting balance
RISK_FRAC = 0.005   # 0.5%

# FTMO challenge thresholds
FTMO_TARGET = 77_000   # +10%
FTMO_FLOOR  = 63_000   # -10%
FTMO_DAILY  = 3_500    # 5% daily loss limit
N_SIMS      = 100_000

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
}
COST = {
    'DAX':0.07, 'NAS100':0.06, 'SP500':0.06, 'US30':0.06,
    'EURUSD':0.08, 'GBPUSD':0.08, 'USDJPY':0.08,
    'GOLD':0.08, 'NATGAS':0.15,
}
H1_HOURS = {
    'DAX':    {8, 9, 10, 13, 14},
    'NAS100': {13, 14, 15, 16},
    'SP500':  {13, 14, 15, 16},
    'US30':   {13, 14, 15, 16},
    'EURUSD': {8, 9, 13, 14, 15},
    'GBPUSD': {8, 9, 13, 14, 15},
    'USDJPY': {0, 1, 2, 8, 9},
    'GOLD':   {8, 9, 13, 14, 15},
    'NATGAS': {13, 14, 15, 16},
}
H1_SKIP = {
    'DAX':    frozenset(),       # trade Mon-Fri: PF 3.40 Friday OOS
    'EURUSD': frozenset(),
    'GBPUSD': frozenset(),
    'USDJPY': frozenset(),
    'GOLD':   frozenset(),
    'NATGAS': frozenset(),
    'NAS100': frozenset({0}),    # skip Monday only: Friday PF 6.74 OOS
    'SP500':  frozenset({0}),
    'US30':   frozenset({0}),
}
# USDJPY uses Pin Bar only in the EA (no Inside Bar)
PB_ONLY = {'USDJPY'}

_m1 = {}

# ── DATA LOAD ─────────────────────────────────────────────────────────────────
def load(k):
    fn = FILES[k]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open', 'high', 'low', 'close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True

# ── TRADE SIMULATOR ───────────────────────────────────────────────────────────
def vsim(k, ep, d, entry, sl, max_bars=480):
    m1 = _m1[k]
    sl_d = abs(entry - sl)
    if sl_d <= 0:
        return -1.0
    end = min(ep + 1 + max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]
    lo = m1['low'].values[ep+1:end]
    if len(hi) == 0:
        return -1.0
    tp = entry + sl_d * TP_R if d == 1 else entry - sl_d * TP_R
    if d == 1:
        sl_i = int(np.argmax(lo <= sl)) if np.any(lo <= sl) else max_bars
        tp_i = int(np.argmax(hi >= tp)) if np.any(hi >= tp) else max_bars
    else:
        sl_i = int(np.argmax(hi >= sl)) if np.any(hi >= sl) else max_bars
        tp_i = int(np.argmax(lo <= tp)) if np.any(lo <= tp) else max_bars
    if tp_i <= sl_i:
        return TP_R
    if sl_i < max_bars:
        return -1.0
    lp = m1['close'].values[end - 1]
    return ((lp - entry) if d == 1 else (entry - lp)) / sl_d

# ── SIGNAL COLLECTOR ──────────────────────────────────────────────────────────
def collect_all(key):
    m1 = _m1[key]
    mi = m1.index
    skip = H1_SKIP.get(key, frozenset({4}))
    p_hours = H1_HOURS.get(key, {8, 9, 13, 14})
    h1 = m1.resample('1h').agg(
        {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
    ).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index)
    out = []
    day_count = {}
    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip:
            continue
        if ts.hour not in p_hours:
            continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD:
            continue
        curr = h1.iloc[i]
        prev = h1.iloc[i - 1]
        if not (curr['high'] < prev['high'] and curr['low'] > prev['low']):
            continue
        ib_h = float(curr['high'])
        ib_l = float(curr['low'])
        if (ib_h - ib_l) <= 0 or (ib_h - ib_l) / ib_h < 0.00015:
            continue
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0:
            continue
        for j in range(len(window)):
            b = window.iloc[j]
            if b['high'] > ib_h:
                d = 1; entry_p = ib_h; sl = ib_l
            elif b['low'] < ib_l:
                d = -1; entry_p = ib_l; sl = ib_h
            else:
                continue
            ep = mi.searchsorted(window.index[j])
            if ep >= len(m1):
                break
            day_count[date_k] = day_count.get(date_k, 0) + 1
            r_gross = vsim(key, ep, d, entry_p, sl)
            cost = COST[key] + SLIPPAGE
            out.append({
                'date': date_k,
                'year': ts.year,
                'r_net': r_gross - cost,
                'instrument': key,
            })
            break
    return out

# ── STATS HELPERS ─────────────────────────────────────────────────────────────
def pf(r):
    r = np.asarray(r, float)
    w = r[r > 0]; l = r[r <= 0]
    return round(w.sum() / abs(l.sum()), 2) if len(l) and l.sum() != 0 else 0.0

def wr(r):
    r = np.asarray(r, float)
    return round(len(r[r > 0]) / len(r) * 100, 1) if len(r) else 0.0

# ── LOAD DATA ─────────────────────────────────────────────────────────────────
print('Loading M1 data...')
loaded = []
for k in FILES:
    if load(k):
        loaded.append(k)
        span = f'{_m1[k].index[0].year}-{_m1[k].index[-1].year}'
        print(f'  {k}: {len(_m1[k]):,} bars  [{span}]')
    else:
        print(f'  {k}: NOT FOUND — skipped')

print(f'  (USDJPY uses Pin Bar only — no Inside Bar signals)')

# ── COLLECT ALL SIGNALS ───────────────────────────────────────────────────────
print('\nCollecting signals across all years (this takes ~1-2 min)...')
all_time = {}
for k in loaded:
    t = collect_all(k)
    all_time[k] = t
    print(f'  {k}: {len(t)} total trades')

all_trades_all = [t for k in loaded for t in all_time[k]]

# OOS slice
oos_trades = [
    t for t in all_trades_all
    if OOS_START.date() <= t['date'] < OOS_END.date()
]
r_oos = np.asarray([t['r_net'] for t in oos_trades], float)
oos_days = (OOS_END - OOS_START).days / 7 * 5

# ── SECTION 1: FULL SYSTEM OOS ────────────────────────────────────────────────
print()
print('=' * 70)
print('  SECTION 1 — FULL SYSTEM  |  OOS 2022-2025  |  TP = 4R')
print('=' * 70)
print(f'  Instruments:      {", ".join(loaded)}')
print(f'  (excluded from backtest: USDJPY, NATGAS, US30 — no M1 data)')
print()
print(f'  Total trades:     {len(r_oos):,}')
print(f'  Trading days:     {oos_days:.0f}')
print(f'  Trades/day:       {len(r_oos)/oos_days:.2f}')
print(f'  Win rate:         {wr(r_oos):.1f}%')
print(f'  Profit factor:    {pf(r_oos):.2f}')

exp_trade = r_oos.mean()
tpd = len(r_oos) / oos_days
daily_r = exp_trade * tpd
daily_pnl = daily_r * ACCOUNT * RISK_FRAC
print(f'  Expectancy/trade: {exp_trade:+.3f}R')
print(f'  Expected daily:   GBP {daily_pnl:,.0f}')
print(f'  Expected monthly: GBP {daily_pnl*22:,.0f}')

print()
print(f'  Per instrument (OOS 2022-2025):')
print(f'  {"Instr":<8}  {"Trades":>7}  {"WR":>7}  {"PF":>7}  {"Exp/trade":>10}  {"Daily":>8}')
print(f'  {"-"*58}')
for k in loaded:
    t_k = [t for t in all_time[k] if OOS_START.date() <= t['date'] < OOS_END.date()]
    r = np.asarray([t['r_net'] for t in t_k], float)
    if len(r) == 0:
        continue
    k_tpd = len(r) / oos_days
    k_daily = r.mean() * k_tpd * ACCOUNT * RISK_FRAC
    flag = ' *' if pf(r) >= 2.5 else ('' if pf(r) >= 1.2 else ' X')
    print(f'  {k:<8}  {len(r):>7}  {wr(r):>6.1f}%  {pf(r):>7.2f}  '
          f'{r.mean():>+9.3f}R  GBP{k_daily:>6,.0f}{flag}')

# ── SECTION 2: WALK-FORWARD ───────────────────────────────────────────────────
print()
print('=' * 70)
print('  SECTION 2 — WALK-FORWARD  |  Year by Year  |  TP = 4R')
print('=' * 70)
print(f'  {"Year":>6}  {"Trades":>7}  {"WR":>7}  {"PF":>7}  '
      f'{"Exp daily R":>12}  {"Status":>10}')
print(f'  {"-"*60}')

yearly_pf = []
for yr in range(2018, 2026):
    t_yr = [t for t in all_trades_all if t['year'] == yr]
    r = np.asarray([t['r_net'] for t in t_yr], float)
    if len(r) < 20:
        if len(r) > 0:
            print(f'  {yr:>6}  {len(r):>7}  (insufficient data)')
        continue
    td = 252
    dr = r.mean() * (len(r) / td)
    p = pf(r)
    yearly_pf.append(p)
    label = 'IS' if yr < 2022 else 'OOS'
    status = 'POSITIVE' if p >= 1.5 else ('MARGINAL' if p >= 1.0 else 'NEGATIVE')
    print(f'  {yr:>6}  {len(r):>7}  {wr(r):>6.1f}%  {p:>7.2f}  '
          f'{dr:>+11.4f}R  [{label}] {status}')

if yearly_pf:
    print()
    print(f'  Years with PF > 1.0:  {sum(1 for p in yearly_pf if p > 1.0)}/{len(yearly_pf)}')
    print(f'  Worst year PF:        {min(yearly_pf):.2f}')
    print(f'  Best year PF:         {max(yearly_pf):.2f}')
    oos_pfs = [p for yr_idx, p in enumerate(yearly_pf) if yearly_pf.index(p) >= (len(yearly_pf) - 4)]

# ── SECTION 3: MONTE CARLO ────────────────────────────────────────────────────
print()
print('=' * 70)
print('  SECTION 3 — MONTE CARLO  |  FTMO GBP70k Challenge')
print('=' * 70)
print(f'  Input stats from OOS 2022-2025 backtest:')
print(f'    Win rate:     {wr(r_oos):.1f}%')
print(f'    Trades/day:   {tpd:.2f}')
print(f'    Expectancy:   {exp_trade:+.3f}R per trade')
print(f'    Risk:         {RISK_FRAC*100:.1f}% per trade')
print(f'  FTMO: Target GBP{FTMO_TARGET:,} | Floor GBP{FTMO_FLOOR:,} | Daily cap GBP{FTMO_DAILY:,}')
print(f'\n  Running {N_SIMS:,} simulations...')

RNG = np.random.default_rng(42)
oos_wr_frac = wr(r_oos) / 100

# Compute win/loss sizes from OOS distribution
wins   = r_oos[r_oos > 0]
losses = r_oos[r_oos <= 0]
avg_win  = float(wins.mean())   if len(wins)   > 0 else TP_R - 0.18
avg_loss = float(losses.mean()) if len(losses) > 0 else -(1.0 + 0.18)

def mc_sim(start_bal):
    balance = start_bal
    days = 0
    while True:
        days += 1
        if days > 500:
            return 'timeout', days
        n = int(RNG.poisson(tpd))
        day_pnl = 0.0
        for _ in range(n):
            risk = balance * RISK_FRAC
            outcome = avg_win * risk if RNG.random() < oos_wr_frac else avg_loss * risk
            balance += outcome
            day_pnl += outcome
            if balance <= FTMO_FLOOR:
                return 'blown', days
            if balance >= FTMO_TARGET:
                return 'pass', days
        if day_pnl <= -FTMO_DAILY:
            return 'blown', days

results_new = [mc_sim(ACCOUNT) for _ in range(N_SIMS)]
outcomes = np.array([r[0] for r in results_new])
days_arr  = np.array([r[1] for r in results_new], float)

passes   = np.sum(outcomes == 'pass')
blows    = np.sum(outcomes == 'blown')
timeouts = np.sum(outcomes == 'timeout')
pct_pass = passes / N_SIMS * 100
pct_blow = blows  / N_SIMS * 100

pass_days = days_arr[outcomes == 'pass']

print()
print(f'  Pass:    {pct_pass:.1f}%')
print(f'  Blow:    {pct_blow:.1f}%')
if timeouts > 0:
    print(f'  Timeout: {timeouts/N_SIMS*100:.1f}%  (edge may be weaker than modelled)')
print()
print(f'  Days to pass (when passing):')
print(f'    Best case  (p10): {np.percentile(pass_days, 10):.0f} days')
print(f'    Median     (p50): {np.median(pass_days):.0f} days')
print(f'    Mean:             {np.mean(pass_days):.0f} days')
print(f'    Slow run   (p90): {np.percentile(pass_days, 90):.0f} days')
print(f'    Worst case (p99): {np.percentile(pass_days, 99):.0f} days')

buffer_r = (ACCOUNT - FTMO_FLOOR) / (ACCOUNT * RISK_FRAC)
gain_r   = (FTMO_TARGET - ACCOUNT) / (ACCOUNT * RISK_FRAC)
print()
print(f'  Buffer before blow:  GBP{ACCOUNT - FTMO_FLOOR:,}  ({buffer_r:.0f} x 1R losses)')
print(f'  Gain needed to pass: GBP{FTMO_TARGET - ACCOUNT:,}  ({gain_r:.0f} x 1R wins)')

print()
print(f'  VERDICT')
print(f'  {"-"*50}')
if pct_pass >= 80:
    print(f'  {pct_pass:.0f}% pass rate — strong system, high confidence to pass.')
elif pct_pass >= 65:
    print(f'  {pct_pass:.0f}% pass rate — solid edge, likely to pass.')
elif pct_pass >= 50:
    print(f'  {pct_pass:.0f}% pass rate — marginal. Stick to 0.5% risk, stay patient.')
else:
    print(f'  {pct_pass:.0f}% pass rate — system needs review before continuing.')

print('=' * 70)
print('Done.')
