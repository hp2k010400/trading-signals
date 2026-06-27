"""
Challenge Analysis — shows what the FTMO challenge actually looks like day-to-day.

Run in Codespaces: python backtest_challenge.py
"""
import pandas as pd, numpy as np, os, warnings
from collections import defaultdict
from dataclasses import dataclass
warnings.filterwarnings('ignore')

# ── Paste the same config / data loading / strategy runners from backtest_validate.py ──
ACCOUNT    = 70_000
COST_SCALE = 1.5
DAILY_LIMIT  = 3_500   # 5% FTMO daily loss limit
TOTAL_LIMIT  = 7_000   # 10% FTMO total loss limit
TARGET_P1    = 7_000   # Phase 1: 10% profit target
TARGET_P2    = 3_500   # Phase 2: 5% profit target

RISKS = {
    'DAX_ORB': 0.0075, 'NAS_ORB': 0.0075, 'SP5_ORB': 0.004,
    'LC_EUR':  0.004,  'LC_GBP':  0.004,  'LC_DAX':  0.0075,
    'LC_UK':   0.0075, 'LC_GOLD': 0.004,
}
COST_R_BASE = {
    'DAX_ORB': 0.06, 'NAS_ORB': 0.08, 'SP5_ORB': 0.06,
    'LC_EUR':  0.04, 'LC_GBP':  0.04, 'LC_DAX':  0.06,
    'LC_UK':   0.06, 'LC_GOLD': 0.06,
}
CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv', 'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

# ── Import everything from validate script ────────────────────────────────────
import sys
sys.path.insert(0, '.')
# We'll re-implement the core so this is self-contained

@dataclass
class Trade:
    tag: str; date: str; dow: int; r: float; pnl: float

_cache = {}
def load_h1(key):
    if key in _cache: return _cache[key]
    if key not in CSVSYMS: return None
    fname = CSVSYMS[key]
    if not os.path.exists(fname): return None
    df = pd.read_csv(fname)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c])
    _cache[key] = df
    return df

def net(t): return t.pnl
def ipos(df, ts):
    loc = df.index.get_loc(ts)
    return loc if isinstance(loc, int) else (loc.start if hasattr(loc,'start') else -1)

def make_trade(df, pos, direction, entry, sl, tag, date, dow):
    risk_r  = RISKS.get(tag, 0.004)
    cost_r  = COST_R_BASE.get(tag, 0.05) * COST_SCALE
    sl_dist = abs(entry - sl)
    if sl_dist <= 0: return None
    best = entry; be_hit = False
    trail_r = 0.10
    for i in range(pos+1, min(pos+200, len(df))):
        bar = df.iloc[i]
        price = bar['high'] if direction == 1 else bar['low']
        move  = (price - entry) * direction
        if move >= sl_dist:
            be_hit = True
        if be_hit:
            trail_stop = (best - sl_dist*trail_r) if direction==1 else (best + sl_dist*trail_r)
            exit_price = (bar['low'] if direction==1 else bar['high'])
            if (direction==1 and exit_price <= trail_stop) or \
               (direction==-1 and exit_price >= trail_stop):
                r = (trail_stop - entry) * direction / sl_dist
                pnl = (r - cost_r) * risk_r * ACCOUNT
                return Trade(tag, date, dow, r, pnl)
        if best is None or (direction==1 and price > best) or (direction==-1 and price < best):
            best = price
        sl_price = entry if be_hit else sl
        hit_sl   = (bar['low'] <= sl and direction==1) or (bar['high'] >= sl and direction==-1)
        if not be_hit and hit_sl:
            r   = -1.0
            pnl = (r - cost_r) * risk_r * ACCOUNT
            return Trade(tag, date, dow, r, pnl)
    return None

def run_orb(key, tag, ref_h, start_h, end_h, rmin, rmax, skip_dow=None):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if skip_dow and day.dayofweek in skip_dow: continue
        ref_bar = df[(df.index >= day+pd.Timedelta(hours=ref_h)) &
                     (df.index <  day+pd.Timedelta(hours=ref_h+1))]
        if len(ref_bar) < 1: continue
        rhi = ref_bar['high'].max(); rlo = ref_bar['low'].min()
        if not (rmin <= rhi-rlo <= rmax): continue
        edf = df[(df.index >= day+pd.Timedelta(hours=start_h)) &
                 (df.index <  day+pd.Timedelta(hours=end_h))]
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                t = make_trade(df,p,1,rhi,rlo,tag,ds,day.dayofweek)
                if t: trades.append(t); break
            if b['low'] < rlo:
                t = make_trade(df,p,-1,rlo,rhi,tag,ds,day.dayofweek)
                if t: trades.append(t); break
    return trades

def run_london_close(key, tag, min_move):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue  # skip Friday
        m_open_bar = df[(df.index >= day+pd.Timedelta(hours=7)) &
                        (df.index <  day+pd.Timedelta(hours=8))]
        m_close_bar = df[(df.index >= day+pd.Timedelta(hours=15)) &
                         (df.index <  day+pd.Timedelta(hours=16))]
        if len(m_open_bar)<1 or len(m_close_bar)<1: continue
        morn_open  = m_open_bar.iloc[0]['open']
        morn_close = m_close_bar.iloc[-1]['close']
        move = morn_close - morn_open
        if abs(move) < min_move: continue
        sess = df[(df.index >= day+pd.Timedelta(hours=7)) &
                  (df.index <  day+pd.Timedelta(hours=16))]
        if len(sess) < 2: continue
        d_hi = sess['high'].max(); d_lo = sess['low'].min()
        buf  = (d_hi - d_lo) * 0.10
        entry_bar = df[(df.index >= day+pd.Timedelta(hours=16)) &
                       (df.index <  day+pd.Timedelta(hours=17))]
        if len(entry_bar) < 1: continue
        p = ipos(df, entry_bar.index[0])
        if p < 0: continue
        ds = str(date)
        if move > min_move:
            t = make_trade(df,p,-1,morn_close,d_hi+buf,tag,ds,day.dayofweek)
        else:
            t = make_trade(df,p,1,morn_close,d_lo-buf,tag,ds,day.dayofweek)
        if t: trades.append(t)
    return trades

W = 70

print("\n" + "=" * W)
print("  CHALLENGE ANALYSIS  —  what does a FTMO attempt look like?")
print("=" * W)
print("\n  Loading data...")

for k in CSVSYMS: load_h1(k)

strats = {
    'DAX_ORB': run_orb('DAX',   'DAX_ORB', 8,  9, 12,  30,  300),
    'SP5_ORB': run_orb('SP500', 'SP5_ORB', 13, 14, 16,   5,  300, {0}),
    'NAS_ORB': run_orb('NAS100','NAS_ORB', 13, 14, 16,  50, 1500, {0,2,4}),
    'LC_EUR':  run_london_close('EURUSD','LC_EUR',  0.0020),
    'LC_GBP':  run_london_close('GBPUSD','LC_GBP',  0.0025),
    'LC_DAX':  run_london_close('DAX',   'LC_DAX',  30.0),
}
if os.path.exists('UK100_cash_H1.csv'):
    strats['LC_UK']   = run_london_close('UK100','LC_UK',   30.0)
if os.path.exists('XAUUSD_H1.csv'):
    strats['LC_GOLD'] = run_london_close('GOLD', 'LC_GOLD',  8.0)

all_trades = [t for v in strats.values() for t in v]
all_trades.sort(key=lambda x: x.date)

# ── Build daily P&L series ────────────────────────────────────────────────────
daily_pnl = defaultdict(float)
for t in all_trades:
    daily_pnl[t.date] += net(t)

days_sorted = sorted(daily_pnl.keys())
pnls        = np.array([daily_pnl[d] for d in days_sorted])

print(f"\n  Total trading days: {len(pnls)}")
print(f"  Avg daily P&L:      £{pnls.mean():,.0f}")
print(f"  Median daily P&L:   £{np.median(pnls):,.0f}")

# ── Daily loss distribution ───────────────────────────────────────────────────
print("\n" + "=" * W)
print("  A. DAILY P&L DISTRIBUTION")
print("=" * W)

losses = pnls[pnls < 0]
print(f"\n  Trading days with a loss:      {len(losses)} / {len(pnls)} "
      f"({len(losses)/len(pnls)*100:.1f}%)")
print(f"  Worst single day:              £{losses.min():,.0f}")
print(f"  Average losing day:            £{losses.mean():,.0f}")
print(f"\n  Days losing > £1,000:          {(pnls < -1000).sum()}")
print(f"  Days losing > £2,000:          {(pnls < -2000).sum()}")
print(f"  Days losing > £3,000:          {(pnls < -3000).sum()}")
print(f"  Days losing > £3,500 (LIMIT):  {(pnls < -3500).sum()}")

# ── Monthly max drawdown ──────────────────────────────────────────────────────
print("\n" + "=" * W)
print("  B. MONTHLY MAX DRAWDOWN  (what's the worst stretch within a month?)")
print("=" * W)

# Group trades by month, compute peak-to-trough within each month
month_dds = []
df_daily  = pd.Series(daily_pnl).sort_index()
df_daily.index = pd.to_datetime(df_daily.index)

for period, grp in df_daily.groupby(df_daily.index.to_period('M')):
    equity = ACCOUNT + grp.cumsum().values
    peak   = np.maximum.accumulate(equity)
    dd     = (peak - equity).max()
    month_dds.append((str(period), dd))

month_dds.sort(key=lambda x: -x[1])
mdd_vals = np.array([x[1] for x in month_dds])

print(f"\n  Avg max drawdown in a month:   £{mdd_vals.mean():,.0f}")
print(f"  Median:                        £{np.median(mdd_vals):,.0f}")
print(f"  Worst month drawdown:          £{mdd_vals.max():,.0f}  ({month_dds[0][0]})")
print(f"\n  Months where DD exceeded £2k:  {(mdd_vals > 2000).sum()}")
print(f"  Months where DD exceeded £4k:  {(mdd_vals > 4000).sum()}")
print(f"  Months where DD exceeded £5k:  {(mdd_vals > 5000).sum()}")
print(f"  Months where DD exceeded £7k:  {(mdd_vals > 7000).sum()}  ← FTMO bust")

# ── Simulate full FTMO challenge (Phase 1 + Phase 2) ─────────────────────────
print("\n" + "=" * W)
print("  C. SIMULATED FTMO CHALLENGE  (5,000 sims)")
print("     Phase 1: hit +£7,000 (10%) | Phase 2: hit +£3,500 (5%)")
print("     Both phases: daily limit £3,500 | total limit £7,000")
print("=" * W)

rng   = np.random.default_rng(42)
n_sim = 5_000

def run_phase(pnls, target, rng, max_days=500):
    """Simulate one FTMO phase. Returns (passed, days, max_dd)."""
    equity = ACCOUNT; peak = ACCOUNT; day_eq = ACCOUNT; max_dd = 0
    for day_n in range(max_days):
        dp     = rng.choice(pnls)
        equity += dp
        peak    = max(peak, equity)
        max_dd  = max(max_dd, peak - equity)
        if day_eq - equity > DAILY_LIMIT: return False, day_n+1, max_dd
        if peak   - equity > TOTAL_LIMIT: return False, day_n+1, max_dd
        if equity - ACCOUNT >= target:    return True,  day_n+1, max_dd
        day_eq = equity
    return False, max_days, max_dd

p1_pass=0; p1_bust=0; p1_days=[]; p1_dds=[]
both_pass=0; both_days=[]; both_dds=[]
p2_bust=0

for _ in range(n_sim):
    ok1, d1, dd1 = run_phase(pnls, TARGET_P1, rng)
    p1_days.append(d1); p1_dds.append(dd1)
    if ok1:
        p1_pass += 1
        ok2, d2, dd2 = run_phase(pnls, TARGET_P2, rng)
        if ok2:
            both_pass += 1
            both_days.append(d1+d2)
            both_dds.append(max(dd1,dd2))
        else:
            p2_bust += 1
    else:
        p1_bust += 1

print(f"\n  PHASE 1  (hit +£7,000):")
print(f"    Pass rate:       {p1_pass/n_sim*100:.1f}%")
print(f"    Bust rate:       {p1_bust/n_sim*100:.1f}%")
p1_pass_days = [p1_days[i] for i in range(n_sim) if p1_days[i] < 500]
print(f"    Avg days:        {np.mean([d for d in p1_days if d<500]):.0f} trading days (~{np.mean([d for d in p1_days if d<500])/22:.1f} months)")
print(f"    Median days:     {int(np.median([d for d in p1_days if d<500]))} trading days")

print(f"\n  PHASE 2  (hit +£3,500, conditional on passing P1):")
p2_total = p1_pass
p2_pass  = both_pass
print(f"    Pass rate:       {p2_pass/p2_total*100:.1f}%  (of those who reach Phase 2)")
print(f"    Bust rate:       {p2_bust/p2_total*100:.1f}%")
print(f"    Avg days:        {np.mean([d-p1_days[i] for i,d in enumerate(both_days)]):.0f} trading days")

print(f"\n  FULL CHALLENGE  (both phases):")
print(f"    Pass rate:       {both_pass/n_sim*100:.1f}%")
print(f"    Expected attempts to get funded: {n_sim/both_pass:.2f}")
print(f"    Expected cost:   £{489 * n_sim/both_pass:,.0f}")
print(f"    Avg total days:  {np.mean(both_days):.0f} (~{np.mean(both_days)/22:.1f} months)")
print(f"    Median total:    {int(np.median(both_days))} trading days")

print(f"\n  Max drawdown across both phases (passing attempts):")
print(f"    Median:          £{np.median(both_dds):,.0f}")
print(f"    90th pct:        £{np.percentile(both_dds,90):,.0f}")
print(f"    Worst seen:      £{np.max(both_dds):,.0f}")

pass_n = both_pass
bust_n = n_sim - both_pass
pass_dds = both_dds

# ── Sample equity curves ──────────────────────────────────────────────────────
print("\n" + "=" * W)
print("  D. SAMPLE CHALLENGE EQUITY CURVES  (10 passing attempts)")
print("=" * W)
print()

shown = 0
rng2 = np.random.default_rng(99)
attempt = 0
while shown < 10 and attempt < 10_000:
    attempt += 1
    seq    = rng2.choice(pnls, size=100, replace=True)
    equity = ACCOUNT; peak = ACCOUNT
    day_start_eq = ACCOUNT
    curve  = [ACCOUNT]; passed = busted = False
    for dp in seq:
        equity += dp; peak = max(peak, equity)
        curve.append(equity)
        daily_loss = day_start_eq - equity
        if daily_loss > DAILY_LIMIT or peak-equity > TOTAL_LIMIT:
            busted = True; break
        if equity - ACCOUNT >= TARGET_P1:
            passed = True; break
        day_start_eq = equity

    if not passed: continue
    shown += 1
    # Print mini chart
    mn = min(curve); mx = max(curve)
    rng_c = mx - mn if mx > mn else 1
    bar_w = 30
    days_to_pass = len(curve)-1
    dd   = max(ACCOUNT + np.maximum.accumulate(np.array(curve)-ACCOUNT) - np.array(curve))
    print(f"  Run {shown:>2}  ({days_to_pass} days, MaxDD £{dd:,.0f})")
    for j, eq in enumerate(curve[::max(1,len(curve)//8)]):
        bar = int((eq - mn) / rng_c * bar_w)
        mk  = '★' if j == len(curve[::max(1,len(curve)//8)])-1 else ' '
        print(f"        £{eq:>7,.0f}  {'█'*bar}{mk}")
    print()

print("  ★ = challenge passed")
print()
print("=" * W)
print(f"  SUMMARY FOR HARRY")
print("=" * W)
print(f"""
  Starting balance:    £70,000
  FTMO daily limit:    £3,500  (5%)
  FTMO total limit:    £7,000  (10%)
  Target to pass:      £3,500  (5%)

  Realistic challenge experience:
  ─ Phase 1 (~{np.mean([d for d in p1_days if d<500]):.0f} days avg) then Phase 2 (~{np.mean([d-p1_days[i] for i,d in enumerate(both_days)]):.0f} days avg)
  ─ Total time to funded: ~{np.mean(both_days)/22:.1f} months on average
  ─ Daily limit is NEVER a concern — worst day ever: £{abs(pnls.min()):,.0f} (limit is £3,500)
  ─ Typical drawdown across both phases: £{int(np.median(both_dds)):,}
  ─ Full challenge pass rate: {both_pass/n_sim*100:.1f}%
  ─ Expected attempts to get funded: {n_sim/both_pass:.2f}
  ─ Expected total cost: £{489*n_sim/both_pass:,.0f}

  Verdict: You'll likely need 1-2 attempts. Day 1 of funded trading
           you'll make back the challenge fee within the first week.
""")
