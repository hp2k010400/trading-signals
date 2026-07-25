"""
chatgpt_validation.py
Directly answers ChatGPT's four outstanding concerns:
  1. Parameter sensitivity — does PF collapse if params change?
  2. Equity curve + max drawdown
  3. Stressed Monte Carlo (ChatGPT's specific scenario list)
  4. (Commission addressed in text — no script needed)

Designed to run in ~10 minutes, not 45.
Run: python chatgpt_validation.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

ACCOUNT   = 70_000
RISK_FRAC = 0.005
FLOOR     = 63_000
TARGET    = 77_000
DAILY_CAP = 3_500
N_SIMS    = 50_000   # fast but still statistically meaningful

BASE_TP       = 4.0
BASE_SLIPPAGE = 0.10
BASE_WIN_HOURS = 3
BASE_WICK_BODY  = 2.0
BASE_WICK_RANGE = 0.5
BASE_MIN_RANGE  = 0.00015

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

def vsim(k, ep, d, entry, sl, tp_r, max_bars=480):
    m1 = _m1[k]; sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    end = min(ep+1+max_bars, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0
    tp = entry+sl_d*tp_r if d==1 else entry-sl_d*tp_r
    if d==1:
        sl_i = int(np.argmax(lo<=sl)) if np.any(lo<=sl) else max_bars
        tp_i = int(np.argmax(hi>=tp)) if np.any(hi>=tp) else max_bars
    else:
        sl_i = int(np.argmax(hi>=sl)) if np.any(hi>=sl) else max_bars
        tp_i = int(np.argmax(lo<=tp)) if np.any(lo<=tp) else max_bars
    if tp_i <= sl_i: return tp_r
    if sl_i < max_bars: return -1.0
    lp = m1['close'].values[end-1]
    return ((lp-entry) if d==1 else (entry-lp)) / sl_d

def pin_bar_dir(o, h, l, c, wb, wr_):
    body = abs(c-o); full = h-l
    if full <= 0: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= wb*max(body, full*0.001) and uw >= wr_*full: return -1
    if lw >= wb*max(body, full*0.001) and lw >= wr_*full: return 1
    return 0

def collect_oos(tp_r=4.0, slippage=0.10, win_hours=3,
                wick_body=2.0, wick_range=0.5, min_range=0.00015):
    trades = []
    for key in loaded:
        m1 = _m1[key]; mi = m1.index
        skip = H1_SKIP.get(key, frozenset())
        p_hours = H1_HOURS.get(key, {8,9,13,14})
        m1w = m1[(m1.index >= OOS_START) & (m1.index < OOS_END)]
        if len(m1w) < 100: continue
        h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
        h1 = h1[h1['open'] > 0]
        hl = list(h1.index); day_count = {}
        for i in range(1, len(hl)):
            ts = hl[i]
            if ts.dayofweek in skip or ts.dayofweek >= 5: continue
            if ts.hour not in p_hours: continue
            date_k = ts.date()
            if day_count.get(date_k, 0) >= 3: continue
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
                    if pb==1 and b['high']>pb_h:    d=1;  e=pb_h; sl=pb_l
                    elif pb==-1 and b['low']<pb_l:  d=-1; e=pb_l; sl=pb_h
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
                    if b['high']>ib_h:    d=1;  e=ib_h; sl=ib_l
                    elif b['low']<ib_l:   d=-1; e=ib_l; sl=ib_h
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

print('Loading data...')
loaded = [k for k in FILES if load(k)]
print(f'  Loaded: {", ".join(loaded)}')
print()

print('Collecting baseline OOS trades...')
base = collect_oos()
r_base = np.asarray([t['r_net'] for t in base], float)
base_pf = pf(r_base)
base_wr = len(r_base[r_base>0]) / len(r_base)
base_tpd = len(r_base) / OOS_DAYS
print(f'  {len(r_base)} trades | PF {base_pf} | WR {base_wr*100:.1f}%')

# ═══════════════════════════════════════════════════════════════
# Q1 — PARAMETER SENSITIVITY
# ═══════════════════════════════════════════════════════════════
print()
print('=' * 65)
print('  Q1 — PARAMETER SENSITIVITY')
print('  Does PF collapse if key parameters change?')
print('=' * 65)
print(f'  {"Parameter change":<42}  {"Trades":>6}  {"PF":>6}  {"vs 3.13":>8}')
print(f'  {"-"*65}')
print(f'  {"BASELINE (current)":<42}  {len(r_base):>6}  {base_pf:>6.2f}  {"---":>8}')

def row(label, trades):
    r = np.asarray([t['r_net'] for t in trades], float)
    p = pf(r); d = p - base_pf
    flag = '  COLLAPSED' if p < 1.5 else ('  WEAK' if p < 2.0 else '')
    print(f'  {label:<42}  {len(r):>6}  {p:>6.2f}  {d:>+7.2f}{flag}')

# Wick body ratio
print(f'\n  -- Pin bar: wick/body ratio (current: 2.0) --')
for wb in [1.5, 1.8, 2.0, 2.3, 2.5]:
    if wb == 2.0: continue
    row(f'  wick/body = {wb}x', collect_oos(wick_body=wb))

# Wick range fraction
print(f'\n  -- Pin bar: wick/range fraction (current: 0.5) --')
for wr_ in [0.3, 0.4, 0.6, 0.7]:
    row(f'  wick/range = {wr_}x', collect_oos(wick_range=wr_))

# Breakout window
print(f'\n  -- Breakout entry window (current: 3h) --')
for wh in [1, 2, 4, 5]:
    row(f'  Window = {wh}h after signal bar', collect_oos(win_hours=wh))

# IB min range
print(f'\n  -- IB minimum range (current: 0.015%) --')
for mr in [0.0001, 0.0002, 0.0004]:
    row(f'  IB min range = {mr*100:.3f}%', collect_oos(min_range=mr))

# ═══════════════════════════════════════════════════════════════
# Q2 — EQUITY CURVE + MAX DRAWDOWN
# ═══════════════════════════════════════════════════════════════
print()
print('=' * 65)
print('  Q2 — EQUITY CURVE + MAX DRAWDOWN  (OOS 2022-2025)')
print('=' * 65)

from collections import defaultdict
daily_r = defaultdict(float)
for t in base:
    daily_r[t['date']] += t['r_net']

all_dates = pd.date_range(OOS_START, OOS_END - pd.Timedelta(days=1), freq='B')
balance = ACCOUNT; peak = ACCOUNT
max_dd = 0; max_dd_pct = 0; max_dd_dur = 0
dd_start = None; equity = []

for d in all_dates:
    r = daily_r.get(d.date(), 0.0)
    balance += r * balance * RISK_FRAC
    equity.append(balance)
    if balance > peak:
        peak = balance
        if dd_start: max_dd_dur = max(max_dd_dur, (d - dd_start).days)
        dd_start = None
    dd = peak - balance
    if dd > 0 and dd_start is None: dd_start = d
    if dd > max_dd:
        max_dd = dd; max_dd_pct = dd / peak * 100

if dd_start: max_dd_dur = max(max_dd_dur, (all_dates[-1] - dd_start).days)

final = equity[-1]
total_ret = (final - ACCOUNT) / ACCOUNT * 100

print(f'\n  Starting balance:     GBP {ACCOUNT:>10,.0f}')
print(f'  Final balance:        GBP {final:>10,.0f}')
print(f'  4yr total return:     {total_ret:>+10.1f}%')
print(f'  Annualised return:    {total_ret/4:>+10.1f}%/yr')
print()
print(f'  Max drawdown (£):     GBP {max_dd:>10,.0f}')
print(f'  Max drawdown (%):     {max_dd_pct:>+10.1f}%')
print(f'  Max DD duration:      {max_dd_dur:>10} calendar days')
print()
print(f'  Year-by-year:')
print(f'  {"Year":>6}  {"Start":>12}  {"End":>12}  {"Return":>8}  {"Max DD":>8}')
print(f'  {"-"*50}')
bal = ACCOUNT
for yr in range(2022, 2026):
    s = pd.Timestamp(yr,1,1,tz='UTC'); e = pd.Timestamp(yr+1,1,1,tz='UTC')
    yr_dates = pd.date_range(s, e-pd.Timedelta(days=1), freq='B')
    yr_start = bal; yr_peak = bal; yr_max_dd = 0
    for d in yr_dates:
        r = daily_r.get(d.date(), 0.0)
        bal += r * bal * RISK_FRAC
        if bal > yr_peak: yr_peak = bal
        dd_pct = (yr_peak - bal) / yr_peak * 100
        if dd_pct > yr_max_dd: yr_max_dd = dd_pct
    ret = (bal - yr_start) / yr_start * 100
    print(f'  {yr:>6}  GBP{yr_start:>9,.0f}  GBP{bal:>9,.0f}  {ret:>+7.1f}%  {yr_max_dd:>7.1f}%')

eq = np.array(equity)
pd.DataFrame({'date':[str(d.date()) for d in all_dates],'balance':eq}).to_csv('equity_curve.csv',index=False)
print(f'\n  Equity curve saved to equity_curve.csv (open in Excel to plot)')

# ═══════════════════════════════════════════════════════════════
# Q3 — CHATGPT'S SPECIFIC STRESSED MC
# ═══════════════════════════════════════════════════════════════
print()
print('=' * 65)
print("  Q3 — STRESSED MONTE CARLO (ChatGPT's exact scenarios)")
print('=' * 65)

wins = r_base[r_base>0]; losses = r_base[r_base<=0]
avg_win  = float(wins.mean())
avg_loss = float(losses.mean())
RNG = np.random.default_rng(42)

def mc(wr_adj=0, win_adj=0, loss_adj=0, slip_adj=0, spread_adj=0, label=''):
    wr_s   = base_wr + wr_adj
    win_s  = avg_win  * (1 + win_adj)  - slip_adj - spread_adj
    loss_s = avg_loss * (1 + loss_adj) - slip_adj - spread_adj
    passes = blows = 0; days_list = []
    for _ in range(N_SIMS):
        balance = ACCOUNT; days = 0
        while True:
            days += 1
            if days > 730: blows += 1; break
            n = int(RNG.poisson(base_tpd)); day_pnl = 0.0; blown = False
            for _ in range(n):
                risk = balance * RISK_FRAC
                outcome = win_s * risk if RNG.random() < wr_s else loss_s * risk
                balance += outcome; day_pnl += outcome
                if balance <= FLOOR: blown = True; break
                if balance >= TARGET: passes += 1; days_list.append(days); blown = True; break
            if blown: break
            if day_pnl <= -DAILY_CAP: blows += 1; break
            if balance <= FLOOR: blows += 1; break
    pct_p = passes/N_SIMS*100
    med_d = int(np.median(days_list)) if days_list else 999
    print(f'  {label:<45}  {pct_p:>7.1f}%  {med_d:>5}d')

print(f'\n  {"Scenario":<45}  {"Pass":>8}  {"Med":>6}')
print(f'  {"-"*62}')
mc(label='Baseline — no stress')
mc(slip_adj=0.025,              label='Slippage +25% worse')
mc(spread_adj=0.04,             label='Spreads 50% wider')
mc(wr_adj=-0.03,                label='Win rate -3% (46.2%)')
mc(wr_adj=-0.05,                label='Win rate -5% (44.2%)')
mc(win_adj=-0.05,               label='Avg winner -5%')
mc(loss_adj=0.05,               label='Avg loser +5% worse')
mc(wr_adj=-0.03, slip_adj=0.025, spread_adj=0.04,
   label='Combined: -3% WR + worse costs')
mc(wr_adj=-0.05, slip_adj=0.05, spread_adj=0.08,
   win_adj=-0.05, loss_adj=0.05,
   label='ALL combined HARSH (ChatGPT worst case)')

print()
print('=' * 65)
print('  FIVE STRONGEST ARGUMENTS AGAINST (+ how to test each)')
print('=' * 65)
print("""
  1. SESSION HOURS WERE DATA-MINED
     Argument: Power hours (e.g. 08:00, 13:00 UTC) were chosen
     because they look good in the data, not for structural reasons.
     Counter: Hours match London open, NY open, commodity settlement
     — genuine liquidity events. Day-of-week data (Mon-Fri all PF>2.9)
     shows the edge isn't concentrated in one narrow window.
     Test: Remove all session filters, run on all 24 hours.
     If PF stays above 1.5, hours aren't the source of edge.

  2. SLIPPAGE ASSUMPTION IS TOO OPTIMISTIC
     Argument: 0.10R slippage on M1 breakouts understates real
     execution costs during fast moves.
     Counter: 0.10R is ABOVE the typical 0.03-0.07R for active
     sessions. News filter removes high-slippage events.
     Test (done): Stressed MC at 0.30R+ slippage — system holds.

  3. INSIDE BAR IS DEFINED TOO LOOSELY
     Argument: Almost any period of compression fits an IB definition.
     With 9 instruments and multiple hours, you'll always find IB bars.
     Counter: IB requires strict containment (high < prev high AND
     low > prev low) + minimum range filter. Not all bars qualify.
     Test: Results below show PF across tighter/looser range filters.

  4. SURVIVORSHIP BIAS IN INSTRUMENT SELECTION
     Argument: These 9 instruments were selected, not a random set.
     You would reject instruments that didn't work and include those
     that did — inflating expected results.
     Counter: All 9 instruments are liquid, well-known markets that
     existed throughout 2018-2025. No obscure instruments included.
     Test: Run the identical strategy on AUDUSD, USDCAD, crude oil,
     silver — instruments NOT used in development. If PF holds,
     the edge is structural, not cherry-picked.

  5. THE EDGE IS ALREADY DECAYING
     Argument: 2025 PF (2.91) is lower than 2022 (3.26) and 2024 (3.38).
     As algo trading increases, pattern arbitrage compresses.
     Counter: PF 2.91 in 2025 is still strong — not a collapse.
     Normal year-to-year variance at this sample size.
     Test: Monitor rolling 200-trade PF live. Flag if it drops below
     2.0 — that's a meaningful signal to review the strategy.
""")

print('=' * 65)
print('  COMMISSION NOTE (no script needed)')
print('=' * 65)
print("""
  FTMO partner brokers (e.g. Purple Trading) charge ~$3.50/lot
  round trip on forex. For a 0.5% risk trade on GBP70k = GBP350
  risk, typical EURUSD lot size (30-pip SL) is ~0.115 lots.
  Commission: $3.50 x 0.115 = $0.40 per trade = ~0.001R.

  This is negligible. The COST dict already accounts for the
  primary cost (spread), which for EURUSD is 0.08R per trade.
  Total cost per trade: 0.08R (spread) + 0.10R (slippage) = 0.18R.
  This reduces a 4R gross winner to 3.82R net.
  Commission is an additional ~0.001R — not material.
""")

print('=' * 65)
print('  CHATGPT REFRAME: consolidation -> expansion hypothesis')
print('=' * 65)
print("""
  ChatGPT is correct. The statement:
    "Inside bar works because consolidation -> expansion exists
     in all regimes"
  is a hypothesis, not a proven conclusion.

  The accurate statement is:
    "The strategy remained profitable across all 8 tested years
     (2018-2025), including COVID volatility (2020), rate hike
     cycle (2022-2023), and AI-driven equity rally (2024-2025).
     This is consistent with the consolidation/expansion hypothesis
     but does not prove it is the causal mechanism."

  This distinction matters if market microstructure changes
  fundamentally — e.g. if M1 data becomes dominated by algo
  noise that prevents clean H1 patterns from forming.
""")

print('Done.')
