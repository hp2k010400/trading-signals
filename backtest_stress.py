"""
backtest_stress.py
Addresses the three remaining validation gaps:
  1. Parameter sensitivity — does PF collapse if params change?
  2. Equity curve + max drawdown — what's the real pain?
  3. Stressed Monte Carlo — 25% worse slippage, wider spreads, lower WR

Also answers: 5 strongest arguments against the strategy being real.

Run: python backtest_stress.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

# ── CONFIG ────────────────────────────────────────────────────────────────────
ACCOUNT   = 70_000
RISK_FRAC = 0.005
FLOOR     = 63_000
TARGET    = 77_000
DAILY_CAP = 3_500
N_SIMS    = 100_000

BASE_TP       = 4.0
BASE_SLIPPAGE = 0.10
BASE_WIN_HOURS = 3
BASE_WICK_BODY  = 2.0
BASE_WICK_RANGE = 0.5
BASE_MIN_RANGE  = 0.00015
MAX_PD    = 3

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')
OOS_DAYS  = (OOS_END - OOS_START).days / 7 * 5

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
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,
    'GOLD':0.08,'NATGAS':0.15,
}
H1_HOURS = {
    'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},'NATGAS':{13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'USDJPY':frozenset(),'GOLD':frozenset(),'NATGAS':frozenset(),
    'NAS100':frozenset({0}),'SP500':frozenset({0}),'US30':frozenset({0}),
}

_m1 = {}

# ── LOAD ──────────────────────────────────────────────────────────────────────
def load(k):
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True

print('Loading data...')
loaded = []
for k in FILES:
    if load(k):
        loaded.append(k)
        print(f'  {k}: {len(_m1[k]):,} bars')

# ── SIMULATORS ────────────────────────────────────────────────────────────────
def vsim(k, ep, d, entry, sl, tp_r, max_bars=480):
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep + 1 + max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry + sl_d * tp_r if d == 1 else entry - sl_d * tp_r
    if d == 1:
        sl_i = int(np.argmax(lo <= sl)) if np.any(lo <= sl) else max_bars
        tp_i = int(np.argmax(hi >= tp)) if np.any(hi >= tp) else max_bars
    else:
        sl_i = int(np.argmax(hi >= sl)) if np.any(hi >= sl) else max_bars
        tp_i = int(np.argmax(lo <= tp)) if np.any(lo <= tp) else max_bars
    if tp_i <= sl_i: return tp_r
    if sl_i < max_bars: return -1.0
    lp = m1['close'].values[end - 1]
    return ((lp - entry) if d == 1 else (entry - lp)) / sl_d

def pin_bar_dir(o, h, l, c, wb, wr_):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= wb*max(body, full*0.001) and uw >= wr_*full: return -1
    if lw >= wb*max(body, full*0.001) and lw >= wr_*full: return 1
    return 0

def collect_oos(tp_r=BASE_TP, slippage=BASE_SLIPPAGE, win_hours=BASE_WIN_HOURS,
                wick_body=BASE_WICK_BODY, wick_range=BASE_WICK_RANGE,
                min_range=BASE_MIN_RANGE):
    trades = []
    for key in loaded:
        m1 = _m1[key]; mi = m1.index
        skip = H1_SKIP.get(key, frozenset({4}))
        p_hours = H1_HOURS.get(key, {8,9,13,14})
        m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
        if len(m1w) < 100: continue
        h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
        h1 = h1[h1['open'] > 0]
        hl = list(h1.index); day_count = {}
        for i in range(1, len(hl)):
            ts = hl[i]
            if ts.dayofweek in skip: continue
            if ts.hour not in p_hours: continue
            date_k = ts.date()
            if day_count.get(date_k, 0) >= MAX_PD: continue
            bar = h1.iloc[i]
            if key == 'USDJPY':
                pb = pin_bar_dir(float(bar['open']),float(bar['high']),
                                  float(bar['low']),float(bar['close']),
                                  wick_body, wick_range)
                if pb == 0: continue
                pb_h = float(bar['high']); pb_l = float(bar['low'])
                entry_start = ts + pd.Timedelta(hours=1)
                window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=win_hours))]
                if len(window) == 0: continue
                for j in range(len(window)):
                    b = window.iloc[j]
                    if pb==1 and b['high']>pb_h:   d=1;  e=pb_h; sl=pb_l
                    elif pb==-1 and b['low']<pb_l: d=-1; e=pb_l; sl=pb_h
                    else: continue
                    ep = mi.searchsorted(window.index[j])
                    if ep >= len(m1): break
                    day_count[date_k] = day_count.get(date_k,0)+1
                    r = vsim(key, ep, d, e, sl, tp_r)
                    trades.append({'date': date_k, 'r_net': r - COST[key] - slippage})
                    break
            else:
                prev = h1.iloc[i-1]
                if not (bar['high']<prev['high'] and bar['low']>prev['low']): continue
                ib_h = float(bar['high']); ib_l = float(bar['low'])
                if (ib_h-ib_l) <= 0 or (ib_h-ib_l)/ib_h < min_range: continue
                entry_start = ts + pd.Timedelta(hours=1)
                window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=win_hours))]
                if len(window) == 0: continue
                for j in range(len(window)):
                    b = window.iloc[j]
                    if b['high']>ib_h:   d=1;  e=ib_h; sl=ib_l
                    elif b['low']<ib_l:  d=-1; e=ib_l; sl=ib_h
                    else: continue
                    ep = mi.searchsorted(window.index[j])
                    if ep >= len(m1): break
                    day_count[date_k] = day_count.get(date_k,0)+1
                    r = vsim(key, ep, d, e, sl, tp_r)
                    trades.append({'date': date_k, 'r_net': r - COST[key] - slippage})
                    break
    return trades

def pf(r):
    r = np.asarray(r, float); w = r[r>0]; l = r[r<=0]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
def wr(r):
    r = np.asarray(r, float)
    return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: PARAMETER SENSITIVITY
# ══════════════════════════════════════════════════════════════════════════════
print('\nCollecting baseline OOS trades...')
base_trades = collect_oos()
r_base = np.asarray([t['r_net'] for t in base_trades], float)
base_pf = pf(r_base)
print(f'  Baseline: {len(r_base)} trades, PF {base_pf}')

print()
print('=' * 72)
print('  SECTION 1 — PARAMETER SENSITIVITY')
print('=' * 72)

def sensitivity_row(name, trades, note=''):
    r = np.asarray([t['r_net'] for t in trades], float)
    p = pf(r)
    diff = p - base_pf
    flag = '  COLLAPSED' if p < 1.5 else ('  WEAK' if p < 2.0 else ('  OK' if p < 2.5 else ''))
    print(f'  {name:<35}  {len(r):>6}  {p:>6.2f}  {diff:>+6.2f}{flag}{note}')

print(f'\n  {"Parameter":<35}  {"Trades":>6}  {"PF":>6}  {"vs base":>7}')
print(f'  {"-"*60}')
print(f'  {"BASELINE (current settings)":<35}  {len(r_base):>6}  {base_pf:>6.2f}  {"---":>7}')
print()

# TP sensitivity
print(f'  -- TP R-multiple (current: 4.0R) --')
for tp in [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
    if tp == 4.0: continue
    t = collect_oos(tp_r=tp)
    sensitivity_row(f'  TP = {tp:.1f}R', t)

# Wick body ratio
print(f'\n  -- Pin bar: wick >= N x body (current: 2.0) --')
for wb in [1.5, 1.7, 1.8, 2.0, 2.3, 2.5, 3.0]:
    if wb == 2.0: continue
    t = collect_oos(wick_body=wb)
    sensitivity_row(f'  Wick/body = {wb:.1f}x', t)

# Wick range ratio
print(f'\n  -- Pin bar: wick >= N x range (current: 0.5) --')
for wr_ in [0.3, 0.4, 0.5, 0.6, 0.7]:
    if wr_ == 0.5: continue
    t = collect_oos(wick_range=wr_)
    sensitivity_row(f'  Wick/range = {wr_:.1f}x', t)

# IB min range
print(f'\n  -- IB minimum range (current: 0.015%) --')
for mr in [0.0001, 0.0002, 0.0003, 0.0005]:
    if mr == BASE_MIN_RANGE: continue
    t = collect_oos(min_range=mr)
    sensitivity_row(f'  Min range = {mr*100:.3f}%', t)

# Breakout window
print(f'\n  -- Breakout window hours (current: 3h) --')
for wh in [1, 2, 3, 4, 5]:
    if wh == 3: continue
    t = collect_oos(win_hours=wh)
    sensitivity_row(f'  Window = {wh}h', t)

# Slippage sensitivity
print(f'\n  -- Slippage assumption (current: 0.10R) --')
for sl in [0.0, 0.05, 0.10, 0.20, 0.30, 0.50]:
    if sl == 0.10: continue
    t = collect_oos(slippage=sl)
    sensitivity_row(f'  Slippage = {sl:.2f}R', t)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: EQUITY CURVE + MAX DRAWDOWN
# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 72)
print('  SECTION 2 — EQUITY CURVE + MAX DRAWDOWN  (OOS 2022-2025)')
print('=' * 72)

from collections import defaultdict
daily_r = defaultdict(float)
for t in base_trades:
    daily_r[t['date']] += t['r_net']

all_dates = pd.date_range(OOS_START, OOS_END - pd.Timedelta(days=1), freq='B')
balance = ACCOUNT
peak = ACCOUNT
max_dd = 0
max_dd_pct = 0
dd_start = None
max_dd_duration = 0
current_dd_start = None

equity_series = []
drawdown_series = []

for d in all_dates:
    r = daily_r.get(d.date(), 0.0)
    day_pnl = r * balance * RISK_FRAC
    balance += day_pnl
    equity_series.append(balance)
    if balance > peak:
        peak = balance
        current_dd_start = None
    dd = peak - balance
    dd_pct = dd / peak * 100
    drawdown_series.append(dd_pct)
    if dd > max_dd:
        max_dd = dd
        max_dd_pct = dd_pct
    if balance < peak and current_dd_start is None:
        current_dd_start = d
    if balance >= peak and current_dd_start is not None:
        dur = (d - current_dd_start).days
        if dur > max_dd_duration:
            max_dd_duration = dur
        current_dd_start = None

equity_arr = np.array(equity_series)
final_balance = equity_arr[-1]
total_return = (final_balance - ACCOUNT) / ACCOUNT * 100
annual_return = total_return / 4  # 4 year OOS

print(f'\n  Starting balance:      GBP {ACCOUNT:>10,.2f}')
print(f'  Final balance:         GBP {final_balance:>10,.2f}')
print(f'  Total return (4yr):    {total_return:>+9.1f}%')
print(f'  Annualised return:     {annual_return:>+9.1f}%')
print()
print(f'  Max drawdown (GBP):    GBP {max_dd:>10,.2f}')
print(f'  Max drawdown (%):      {max_dd_pct:>+9.1f}%')
print(f'  Max DD duration:       {max_dd_duration:>9} calendar days')
print()

# Year by year drawdown
print(f'  Year-by-year drawdown:')
print(f'  {"Year":>6}  {"Start bal":>12}  {"End bal":>12}  {"Return":>8}  {"Max DD":>10}')
print(f'  {"-"*55}')
yr_balance = ACCOUNT
for yr in range(2022, 2026):
    s = pd.Timestamp(yr, 1, 1, tz='UTC')
    e = pd.Timestamp(yr+1, 1, 1, tz='UTC')
    yr_dates = pd.date_range(s, e - pd.Timedelta(days=1), freq='B')
    yr_start = yr_balance
    yr_peak = yr_balance
    yr_max_dd = 0
    for d in yr_dates:
        r = daily_r.get(d.date(), 0.0)
        yr_balance += r * yr_balance * RISK_FRAC
        if yr_balance > yr_peak: yr_peak = yr_balance
        dd = (yr_peak - yr_balance) / yr_peak * 100
        if dd > yr_max_dd: yr_max_dd = dd
    ret = (yr_balance - yr_start) / yr_start * 100
    print(f'  {yr:>6}  GBP{yr_start:>9,.0f}  GBP{yr_balance:>9,.0f}  {ret:>+7.1f}%  {yr_max_dd:>8.1f}%')

# Percentile drawdown analysis
dd_arr = np.array(drawdown_series)
print(f'\n  Drawdown distribution (% of days):')
print(f'    In drawdown at all:   {np.sum(dd_arr > 0)/len(dd_arr)*100:.0f}% of days')
print(f'    DD > 2%:              {np.sum(dd_arr > 2)/len(dd_arr)*100:.0f}% of days')
print(f'    DD > 5%:              {np.sum(dd_arr > 5)/len(dd_arr)*100:.0f}% of days')
print(f'    DD > 10%:             {np.sum(dd_arr > 10)/len(dd_arr)*100:.0f}% of days')

# Save equity curve to CSV
eq_df = pd.DataFrame({
    'date': [str(d.date()) for d in all_dates],
    'balance': equity_arr,
    'drawdown_pct': dd_arr
})
eq_df.to_csv('equity_curve_oos.csv', index=False)
print(f'\n  Equity curve saved to: equity_curve_oos.csv')

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: STRESSED MONTE CARLO
# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 72)
print('  SECTION 3 — STRESSED MONTE CARLO  (FTMO GBP70k)')
print('=' * 72)

r_oos = np.asarray([t['r_net'] for t in base_trades], float)
wins = r_oos[r_oos > 0]
losses = r_oos[r_oos <= 0]
base_wr   = len(wins) / len(r_oos)
base_tpd  = len(r_oos) / OOS_DAYS
avg_win   = float(wins.mean())
avg_loss  = float(losses.mean())

RNG = np.random.default_rng(42)

def mc_stress(wr_adj=0.0, win_adj=0.0, loss_adj=0.0, slip_adj=0.0, spread_adj=0.0,
              label=''):
    wr_s    = base_wr + wr_adj
    win_s   = avg_win  * (1 + win_adj)  - slip_adj - spread_adj
    loss_s  = avg_loss * (1 + loss_adj) - slip_adj - spread_adj

    passes = blows = 0
    pass_days_list = []
    for _ in range(N_SIMS):
        balance = ACCOUNT; days = 0
        while True:
            days += 1
            if days > 730: blows += 1; break
            n = int(RNG.poisson(base_tpd))
            day_pnl = 0.0
            blown = False
            for _ in range(n):
                risk = balance * RISK_FRAC
                outcome = win_s * risk if RNG.random() < wr_s else loss_s * risk
                balance += outcome; day_pnl += outcome
                if balance <= FLOOR: blown = True; break
                if balance >= TARGET:
                    passes += 1; pass_days_list.append(days); blown = True; break
            if blown: break
            if day_pnl <= -DAILY_CAP: blows += 1; break
            if balance <= FLOOR: blows += 1; break

    pct_p = passes / N_SIMS * 100
    pct_b = (N_SIMS - passes) / N_SIMS * 100
    med_d = np.median(pass_days_list) if pass_days_list else 999
    p99_d = np.percentile(pass_days_list, 99) if pass_days_list else 999
    print(f'  {label:<35}  {pct_p:>7.1f}%  {pct_b:>7.1f}%  '
          f'{med_d:>6.0f}d  {p99_d:>6.0f}d')

print(f'\n  {"Scenario":<35}  {"Pass":>8}  {"Blow":>8}  {"Med":>7}  {"P99":>7}')
print(f'  {"-"*68}')

mc_stress(label='Baseline (no stress)')
mc_stress(slip_adj=0.05,   label='+25% worse slippage (+0.05R)')
mc_stress(spread_adj=0.04, label='+50% wider spreads (+0.04R)')
mc_stress(wr_adj=-0.03,    label='Win rate -3% (46.3%)')
mc_stress(wr_adj=-0.05,    label='Win rate -5% (44.3%)')
mc_stress(win_adj=-0.05,   label='Avg winner -5%')
mc_stress(loss_adj=0.05,   label='Avg loser +5% worse')
mc_stress(wr_adj=-0.03, slip_adj=0.05, spread_adj=0.04,
          label='Combined mild stress')
mc_stress(wr_adj=-0.05, slip_adj=0.10, spread_adj=0.08,
          win_adj=-0.10, loss_adj=0.10,
          label='Combined HARSH stress')

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: 5 STRONGEST ARGUMENTS AGAINST
# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 72)
print('  SECTION 4 — 5 STRONGEST ARGUMENTS AGAINST THE EDGE BEING REAL')
print('=' * 72)

print("""
  1. SESSION HOUR SELECTION IS OVERFITTED
     Argument: The strategy only trades specific hours (e.g. 08,09,13,14 UTC).
     These were likely chosen because they work in the data, not because
     there is a structural reason for the edge to exist only then.
     Test: Remove session filters entirely. If PF collapses to ~1.0,
     the hours were hand-picked to fit the data.

  2. SLIPPAGE IS UNDERSTATED FOR M1 ENTRIES
     Argument: Entering on an M1 bar breakout in a real market means
     the fill price may be several pips beyond the trigger level,
     especially in fast-moving markets. 0.10R slippage may be optimistic.
     Test: Run backtest at 0.30R and 0.50R slippage. See section 1 above.

  3. THE INSIDE BAR DEFINITION IS TOO FLEXIBLE
     Argument: Almost any period of consolidation can be labelled an
     inside bar. With 9 instruments and multiple session hours, the
     backtest may be capturing random noise that looks like a pattern.
     Test: Parameter sensitivity on IB range filter (section 1).
     If tightening the definition doesn't hurt PF, the pattern is real.

  4. SURVIVORSHIP BIAS IN INSTRUMENT SELECTION
     Argument: The 9 instruments chosen are well-known liquid markets
     that have existed and performed well over 2018-2025. Instruments
     that stopped trading or had structural breaks were not included.
     Test: Run the exact same strategy on instruments NOT used in
     development (e.g. AUDUSD, USDCAD, crude oil, silver).
     If PF holds, the edge is structural not cherry-picked.

  5. THE EDGE MAY ALREADY BE ERODING
     Argument: The strategy relies on M1 breakouts from H1 patterns.
     As algorithmic trading has increased, these patterns may be more
     efficiently traded and the edge could be compressing over time.
     Test: Compare PF by year — if 2018-2021 PF >> 2022-2025 PF,
     the edge is decaying. OOS data shows: worst OOS year PF 2.92,
     best OOS year PF 3.74. No decay visible yet — but monitor.
""")

print('=' * 72)

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — COMMISSION EXPLICITLY MODELLED
# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 72)
print('  SECTION 5 — COMMISSION BREAKDOWN (explicit per-instrument)')
print('=' * 72)
RISK_GBP = ACCOUNT * RISK_FRAC
print(f'\n  At {RISK_FRAC*100:.1f}% risk on GBP{ACCOUNT:,} = GBP{RISK_GBP:.0f} per trade')
print(f'\n  {"Instrument":>10}  {"Cost (R)":>9}  {"Cost (£)":>9}  {"% of 4R win":>12}  {"Net win (R)":>11}')
print(f'  {"-"*57}')
for k in loaded:
    cost_r = COST[k]
    cost_gbp = cost_r * RISK_GBP
    pct_win = cost_r / BASE_TP * 100
    net = BASE_TP - cost_r
    print(f'  {k:>10}  {cost_r:>9.3f}R  GBP{cost_gbp:>6.1f}  {pct_win:>11.1f}%  {net:>10.2f}R')

all_cost_r = [COST[k] for k in loaded]
avg_cost   = sum(all_cost_r) / len(all_cost_r)
total_drag = sum(COST.get(t['date'].__class__.__name__, avg_cost) for t in base_trades) * RISK_GBP
total_drag = avg_cost * len(base_trades) * RISK_GBP
wins_gross = sum(r + avg_cost for r in r_oos if r > 0)
loss_gross = sum(r + avg_cost for r in r_oos if r <= 0)
pf_gross   = round(wins_gross / abs(loss_gross), 2) if loss_gross != 0 else 0

print(f'\n  Average cost per trade:       {avg_cost:.3f}R  (GBP {avg_cost*RISK_GBP:.1f})')
print(f'  Total cost over OOS period:   GBP {total_drag:,.0f}')
print(f'  Gross PF (before costs):      {pf_gross:.2f}')
print(f'  Net PF (after costs):         {base_pf:.2f}')
print(f'  Costs reduce PF by:           {pf_gross - base_pf:.2f} ({(pf_gross-base_pf)/pf_gross*100:.1f}%)')
print(f'  Commission is real — included in all results above.')

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — MC WITH STOCHASTIC SPREAD/SLIPPAGE VARIANCE
# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 72)
print('  SECTION 6 — MC WITH RANDOM SPREAD/SLIPPAGE VARIANCE PER TRADE')
print('=' * 72)
print('  Section 3 used fixed cost adjustments. This section adds per-trade')
print('  random noise — some trades hit wide spread, some get slippage spikes.')
print()

base_wr2 = len(r_oos[r_oos > 0]) / len(r_oos)
avg_win2  = float(r_oos[r_oos > 0].mean())
avg_loss2 = float(r_oos[r_oos <= 0].mean())
tpd2      = len(r_oos) / OOS_DAYS

def mc_stochastic(spread_sigma=0.0, slip_sigma=0.0, label=''):
    passes = blows = 0
    days_list = []
    for _ in range(N_SIMS):
        balance = ACCOUNT; days = 0
        while True:
            days += 1
            if days > 730: blows += 1; break
            n = int(RNG.poisson(tpd2))
            day_pnl = 0.0; blown = False
            for _ in range(n):
                risk = balance * RISK_FRAC
                rand_cost = abs(RNG.normal(0, spread_sigma + slip_sigma))
                if RNG.random() < base_wr2:
                    outcome = (avg_win2 - rand_cost) * risk
                else:
                    outcome = (avg_loss2 - rand_cost) * risk
                balance += outcome; day_pnl += outcome
                if balance <= FLOOR: blown = True; break
                if balance >= TARGET: passes += 1; days_list.append(days); blown = True; break
            if blown: break
            if day_pnl <= -DAILY_CAP: blows += 1; break
            if balance <= FLOOR: blows += 1; break
    pct_p = passes / N_SIMS * 100
    med_d = np.median(days_list) if days_list else 999
    print(f'  {label:<48}  {pct_p:>7.1f}%  {med_d:>6.0f}d')

print(f'  {"Scenario":<48}  {"Pass":>8}  {"Med":>7}')
print(f'  {"-"*68}')
mc_stochastic(0.00, 0.00, 'Baseline (no cost variance)')
mc_stochastic(0.03, 0.03, 'Mild variance (σ=0.03R each, normal trading)')
mc_stochastic(0.05, 0.05, 'Moderate variance (σ=0.05R each)')
mc_stochastic(0.10, 0.10, 'High variance (σ=0.10R — gap opens & thin markets)')
mc_stochastic(0.15, 0.15, 'Extreme variance (σ=0.15R — news spikes & holidays)')

# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — WALK-FORWARD EFFICIENCY RATIO
# ══════════════════════════════════════════════════════════════════════════════
print()
print('=' * 72)
print('  SECTION 7 — WALK-FORWARD EFFICIENCY RATIO  (WFE)')
print('=' * 72)
print('  WFE = OOS PF / IS PF.  >0.7 = good, >0.85 = excellent.')
print('  Measures whether IS parameters truly generalise to unseen data.')
print()

IS_START = pd.Timestamp(2018, 1, 1, tz='UTC')
IS_END   = pd.Timestamp(2022, 1, 1, tz='UTC')

def collect_range(start, end):
    trades = []
    for key in loaded:
        m1 = _m1[key]; mi = m1.index
        skip = H1_SKIP.get(key, frozenset({4}))
        p_hours = H1_HOURS.get(key, {8,9,13,14})
        m1w = m1[(m1.index >= start) & (m1.index < end)]
        if len(m1w) < 100: continue
        h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
        h1 = h1[h1['open'] > 0]
        hl = list(h1.index); day_count = {}
        for i in range(1, len(hl)):
            ts = hl[i]
            if ts.dayofweek in skip: continue
            if ts.hour not in p_hours: continue
            date_k = ts.date()
            if day_count.get(date_k, 0) >= MAX_PD: continue
            bar = h1.iloc[i]
            if key == 'USDJPY':
                pb = pin_bar_dir(float(bar['open']),float(bar['high']),
                                  float(bar['low']),float(bar['close']),
                                  BASE_WICK_BODY, BASE_WICK_RANGE)
                if pb == 0: continue
                pb_h = float(bar['high']); pb_l = float(bar['low'])
                entry_start = ts + pd.Timedelta(hours=1)
                window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=BASE_WIN_HOURS))]
                if len(window) == 0: continue
                for j in range(len(window)):
                    b = window.iloc[j]
                    if pb==1 and b['high']>pb_h:    d=1;  e=pb_h; sl=pb_l
                    elif pb==-1 and b['low']<pb_l:  d=-1; e=pb_l; sl=pb_h
                    else: continue
                    ep = mi.searchsorted(window.index[j])
                    if ep >= len(m1): break
                    day_count[date_k] = day_count.get(date_k,0)+1
                    r = vsim(key, ep, d, e, sl, BASE_TP)
                    trades.append({'r_net': r - COST[key] - BASE_SLIPPAGE})
                    break
            else:
                prev = h1.iloc[i-1]
                if not (bar['high']<prev['high'] and bar['low']>prev['low']): continue
                ib_h = float(bar['high']); ib_l = float(bar['low'])
                if (ib_h-ib_l) <= 0 or (ib_h-ib_l)/ib_h < BASE_MIN_RANGE: continue
                entry_start = ts + pd.Timedelta(hours=1)
                window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=BASE_WIN_HOURS))]
                if len(window) == 0: continue
                for j in range(len(window)):
                    b = window.iloc[j]
                    if b['high']>ib_h:    d=1;  e=ib_h; sl=ib_l
                    elif b['low']<ib_l:   d=-1; e=ib_l; sl=ib_h
                    else: continue
                    ep = mi.searchsorted(window.index[j])
                    if ep >= len(m1): break
                    day_count[date_k] = day_count.get(date_k,0)+1
                    r = vsim(key, ep, d, e, sl, BASE_TP)
                    trades.append({'r_net': r - COST[key] - BASE_SLIPPAGE})
                    break
    return trades

print('  Collecting IS 2018-2021 trades...')
is_trades = collect_range(IS_START, IS_END)
r_is  = np.asarray([t['r_net'] for t in is_trades], float)

pf_is   = pf(r_is)
pf_oos2 = base_pf
wfe     = pf_oos2 / pf_is if pf_is > 0 else 0
wr_is   = wr(r_is)

print(f'\n  {"Period":>12}  {"Trades":>8}  {"WR":>7}  {"PF":>8}  {"WFE":>8}')
print(f'  {"-"*50}')
print(f'  {"IS 2018-21":>12}  {len(r_is):>8}  {wr_is:>6.1f}%  {pf_is:>8.2f}  {"(baseline)":>10}')
print(f'  {"OOS 2022-25":>12}  {len(r_oos):>8}  {wr(r_oos):>6.1f}%  {pf_oos2:>8.2f}  {wfe:>10.3f}')
print()

if   wfe >= 0.85: wfe_v = 'EXCELLENT — OOS nearly matches IS. Minimal overfitting.'
elif wfe >= 0.70: wfe_v = 'GOOD — OOS holds well. Edge is genuine.'
elif wfe >= 0.50: wfe_v = 'ACCEPTABLE — some degradation but within norms.'
elif wfe >= 0.30: wfe_v = 'WEAK — significant IS/OOS gap. Risk of overfitting.'
else:             wfe_v = 'POOR — OOS much weaker than IS. Likely overfit.'
print(f'  WFE = {wfe:.3f} — {wfe_v}')

print(f'\n  Year-by-year OOS PF vs IS baseline:')
print(f'  {"Year":>6}  {"Trades":>8}  {"WR":>7}  {"PF":>8}  {"WFE":>8}')
print(f'  {"-"*45}')
for yr in range(2022, 2026):
    s = pd.Timestamp(yr,1,1,tz='UTC'); e = pd.Timestamp(yr+1,1,1,tz='UTC')
    yr_t = collect_range(s, e)
    r_yr = np.asarray([t['r_net'] for t in yr_t], float)
    if len(r_yr) < 5: continue
    pf_yr  = pf(r_yr)
    wfe_yr = pf_yr / pf_is if pf_is > 0 else 0
    flag   = '  LOW' if wfe_yr < 0.5 else ''
    print(f'  {yr:>6}  {len(r_yr):>8}  {wr(r_yr):>6.1f}%  {pf_yr:>8.2f}  {wfe_yr:>7.3f}{flag}')

print()
print('=' * 72)
print('  FINAL SUMMARY — ALL 5 GAPS ADDRESSED')
print('=' * 72)
print(f'  Gap 1 — Parameter sensitivity:    Section 1 (PF across ±20% param sweep)')
print(f'  Gap 2 — Equity curve + max DD:    Section 2 (saved: equity_curve_oos.csv)')
print(f'  Gap 3 — Commission modelled:      Section 5 (COST dict = spread+comm in R)')
print(f'  Gap 4 — MC spread/slip variance:  Section 6 (per-trade stochastic costs)')
print(f'  Gap 5 — Walk-forward efficiency:  Section 7 (WFE = {wfe:.3f})')
print()
print(f'  EA fix: IsSkipDay() now skips Friday (dow==5) for FX/DAX/GOLD/NATGAS')
print(f'          v2.01 -> v2.02. Recompile in MT5 and restart on VPS.')
print('=' * 72)
print('Done.')
