"""
backtest_extended.py
H1 Inside Bar — slippage sensitivity + new instruments
OOS 2022-2026 only (honest numbers).

Tests:
  1. Original 7 instruments with explicit slippage model (0, 0.05, 0.10, 0.15R)
  2. New instruments: NatGas, Oil, Silver, GBPJPY, EURJPY, AUDJPY
  3. Combined system stats — what does the full universe look like?
  4. Updated FTMO pass rate estimate at realistic slippage

Run: python backtest_extended.py
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')
TP_R      = 3.0
ACCOUNT   = 70_000
RISK_FRAC = 0.005
N_SIMS    = 5_000

# ── Instrument config — original 7 ────────────────────────────────────────────
ORIG = {
    'DAX':    {'file':'GER40_M1_oanda.csv',  'cost':0.07, 'hours':{8,9,10,13,14}, 'skip':frozenset({4})},
    'UK100':  {'file':'UK100_M1_oanda.csv',  'cost':0.07, 'hours':{8,9,10,13,14}, 'skip':frozenset({4})},
    'NAS100': {'file':'US100_M1_oanda.csv',  'cost':0.06, 'hours':{13,14,15,16},  'skip':frozenset({0,4})},
    'SP500':  {'file':'US500_M1_oanda.csv',  'cost':0.06, 'hours':{13,14,15,16},  'skip':frozenset({0,4})},
    'EURUSD': {'file':'EURUSD_M1_oanda.csv', 'cost':0.08, 'hours':{8,9,13,14,15}, 'skip':frozenset({4})},
    'GBPUSD': {'file':'GBPUSD_M1_oanda.csv', 'cost':0.08, 'hours':{8,9,13,14,15}, 'skip':frozenset({4})},
    'GOLD':   {'file':'XAUUSD_M1_oanda.csv', 'cost':0.08, 'hours':{8,9,13,14,15}, 'skip':frozenset({4})},
}

# ── New instruments ────────────────────────────────────────────────────────────
NEW = {
    'SILVER': {'file':'XAGUSD_M1_oanda.csv',  'cost':0.10, 'hours':{8,9,13,14,15}, 'skip':frozenset({4})},
    'OIL':    {'file':'OIL_M1_oanda.csv',     'cost':0.12, 'hours':{13,14,15,16},  'skip':frozenset({4})},
    'NATGAS': {'file':'NATGAS_M1_oanda.csv',  'cost':0.15, 'hours':{13,14,15,16},  'skip':frozenset({4})},
    'GBPJPY': {'file':'GBPJPY_M1_oanda.csv',  'cost':0.10, 'hours':{8,9,10,13,14}, 'skip':frozenset({4})},
    'EURJPY': {'file':'EURJPY_M1_oanda.csv',  'cost':0.10, 'hours':{8,9,10,13,14}, 'skip':frozenset({4})},
    'AUDJPY': {'file':'AUDJPY_M1_oanda.csv',  'cost':0.10, 'hours':{0,1,8,9,13,14},'skip':frozenset({4})},
}

ALL_INSTR = {**ORIG, **NEW}
_m1 = {}

def load(k, cfg):
    fn = cfg['file']
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True

def vsim(k, ep, d, entry, sl, tp_r, max_bars=480):
    m1=_m1[k]; sl_d=abs(entry-sl)
    if sl_d<=0: return -1.0
    end=min(ep+1+max_bars, len(m1))
    hi=m1['high'].values[ep+1:end]; lo=m1['low'].values[ep+1:end]
    if len(hi)==0: return -1.0
    tp=entry+sl_d*tp_r if d==1 else entry-sl_d*tp_r
    if d==1:
        sl_i=int(np.argmax(lo<=sl)) if np.any(lo<=sl) else max_bars
        tp_i=int(np.argmax(hi>=tp)) if np.any(hi>=tp) else max_bars
    else:
        sl_i=int(np.argmax(hi>=sl)) if np.any(hi>=sl) else max_bars
        tp_i=int(np.argmax(lo<=tp)) if np.any(lo<=tp) else max_bars
    if tp_i<=sl_i: return tp_r
    if sl_i<max_bars: return -1.0
    lp=m1['close'].values[end-1]
    return ((lp-entry) if d==1 else (entry-lp))/sl_d

def collect_oos(key, cfg):
    m1=_m1[key]; mi=m1.index
    spread_cost = cfg['cost'] * 1.5
    skip   = cfg['skip']
    p_hours= cfg['hours']
    m1w = m1[(m1.index>=OOS_START)&(m1.index<OOS_END)]
    if len(m1w)<100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open']>0]
    hl  = list(h1.index); out=[]; day_count={}
    for i in range(1, len(hl)):
        ts=hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in p_hours: continue
        date_k=ts.date()
        if day_count.get(date_k,0)>=3: continue
        curr=h1.iloc[i]; prev=h1.iloc[i-1]
        if not(curr['high']<prev['high'] and curr['low']>prev['low']): continue
        ib_h=float(curr['high']); ib_l=float(curr['low'])
        if (ib_h-ib_l)<=0 or (ib_h-ib_l)/ib_h<0.00015: continue
        entry_start=ts+pd.Timedelta(hours=1)
        window=m1[(mi>=entry_start)&(mi<entry_start+pd.Timedelta(hours=3))]
        if len(window)==0: continue
        for j in range(len(window)):
            b=window.iloc[j]
            if b['high']>ib_h: d=1; entry=ib_h; sl=ib_l
            elif b['low']<ib_l: d=-1; entry=ib_l; sl=ib_h
            else: continue
            ep=mi.searchsorted(window.index[j])
            if ep>=len(m1): break
            day_count[date_k]=day_count.get(date_k,0)+1
            r_gross = vsim(key,ep,d,entry,sl,TP_R)
            out.append({'date':date_k, 'r_gross':r_gross, 'spread':spread_cost})
            break
    return out

def pf(r): r=np.asarray(r,float); w=r[r>0]; l=r[r<=0]; return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
def wr(r): r=np.asarray(r,float); return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

# ── Load ──────────────────────────────────────────────────────────────────────
print('Loading instruments...')
loaded_orig=[]; loaded_new=[]
for k,cfg in ORIG.items():
    if load(k,cfg): loaded_orig.append(k); print(f'  {k}: {len(_m1[k]):,} bars')
    else: print(f'  {k}: FILE NOT FOUND — {cfg["file"]}')
for k,cfg in NEW.items():
    if load(k,cfg): loaded_new.append(k); print(f'  {k}: {len(_m1[k]):,} bars')
    else: print(f'  {k}: not available (run download_new.py first)')

# ── Collect OOS trades ────────────────────────────────────────────────────────
print('\nCollecting OOS trades (2022-2026)...')
trades_orig={}; trades_new={}
for k in loaded_orig:
    trades_orig[k]=collect_oos(k,ORIG[k]); print(f'  {k}: {len(trades_orig[k])} trades')
for k in loaded_new:
    trades_new[k]=collect_oos(k,NEW[k]); print(f'  {k}: {len(trades_new[k])} trades')

OOS_DAYS = (OOS_END-OOS_START).days / 7 * 5  # approx trading days

SLIP_LEVELS = [0.00, 0.05, 0.10, 0.15]

# ════════════════════════════════════════════════════════════════════════════
# SECTION 1: SLIPPAGE SENSITIVITY — ORIGINAL 7 INSTRUMENTS
# ════════════════════════════════════════════════════════════════════════════
print(f'\n{"═"*72}')
print('  SLIPPAGE SENSITIVITY — ORIGINAL 7 INSTRUMENTS (OOS 2022-2026)')
print(f'{"═"*72}')

all_orig = [t for k in loaded_orig for t in trades_orig[k]]
n_orig   = len(all_orig)
ppd_orig = n_orig / OOS_DAYS

print(f'\n  {"Slippage":>10}  {"Trades":>8}  {"WR":>7}  {"PF":>7}  {"Expect":>9}  '
      f'{"Daily P&L":>11}  {"Monthly":>10}')
print('  '+'─'*68)
for slip in SLIP_LEVELS:
    r_net = np.asarray([t['r_gross']-t['spread']-slip for t in all_orig], float)
    exp_r = r_net.mean()
    daily_pnl = ppd_orig * exp_r * ACCOUNT * RISK_FRAC
    monthly   = daily_pnl * 22
    flag = ' ← realistic' if slip==0.10 else (' ← no slippage' if slip==0.00 else '')
    print(f'  {slip:>9.2f}R  {len(r_net):>8,}  {wr(r_net):>6.1f}%  {pf(r_net):>7.2f}  '
          f'{exp_r:>8.4f}R  £{daily_pnl:>9,.0f}  £{monthly:>8,.0f}{flag}')

# Per instrument at 0.10R slippage
print(f'\n  Per instrument at 0.10R slippage:')
print(f'  {"Instr":<8}  {"Trades":>6}  {"Per Day":>8}  {"WR":>7}  {"PF":>7}  {"Monthly":>10}')
print('  '+'─'*54)
for k in loaded_orig:
    tl=trades_orig[k]
    if not tl: continue
    r=np.asarray([t['r_gross']-t['spread']-0.10 for t in tl],float)
    ppd=len(tl)/OOS_DAYS
    monthly=ppd*r.mean()*22*ACCOUNT*RISK_FRAC
    flag=' ★' if pf(r)>=2.0 else (' ✗' if pf(r)<1.0 else '')
    print(f'  {k:<8}  {len(tl):>6,}  {ppd:>8.2f}  {wr(r):>6.1f}%  {pf(r):>7.2f}  £{monthly:>8,.0f}{flag}')

# ════════════════════════════════════════════════════════════════════════════
# SECTION 2: NEW INSTRUMENTS
# ════════════════════════════════════════════════════════════════════════════
print(f'\n\n{"═"*72}')
print('  NEW INSTRUMENTS — H1 Inside Bar OOS (2022-2026)')
print(f'{"═"*72}')

if not loaded_new:
    print('\n  No new instrument data found.')
    print('  Run: python download_new.py')
    print('  Then re-run this script.')
else:
    all_new = [t for k in loaded_new for t in trades_new[k]]
    print(f'\n  {"Instr":<8}  {"Trades":>6}  {"Per Day":>8}  {"WR":>7}  {"PF (no slip)":>14}  '
          f'{"PF (0.10R)":>11}  {"Monthly @0.10R":>15}')
    print('  '+'─'*72)
    for k in loaded_new:
        tl=trades_new[k]
        if not tl: print(f'  {k:<8}  0 trades'); continue
        r0=np.asarray([t['r_gross']-t['spread'] for t in tl],float)
        r1=np.asarray([t['r_gross']-t['spread']-0.10 for t in tl],float)
        ppd=len(tl)/OOS_DAYS
        monthly=ppd*r1.mean()*22*ACCOUNT*RISK_FRAC
        flag=' ★' if pf(r1)>=2.0 else (' ✗' if pf(r1)<1.0 else '')
        print(f'  {k:<8}  {len(tl):>6,}  {ppd:>8.2f}  {wr(r0):>6.1f}%  '
              f'{pf(r0):>14.2f}  {pf(r1):>11.2f}  £{monthly:>13,.0f}{flag}')

# ════════════════════════════════════════════════════════════════════════════
# SECTION 3: COMBINED SYSTEM (all available instruments, 0.10R slippage)
# ════════════════════════════════════════════════════════════════════════════
print(f'\n\n{"═"*72}')
print('  COMBINED SYSTEM — ALL INSTRUMENTS at 0.10R slippage (OOS 2022-2026)')
print(f'{"═"*72}')

all_combined = [t for k in (loaded_orig+loaded_new) for t in ({**trades_orig,**trades_new}[k])]
if all_combined:
    r_comb = np.asarray([t['r_gross']-t['spread']-0.10 for t in all_combined], float)
    ppd_comb = len(all_combined)/OOS_DAYS
    exp_comb = r_comb.mean()
    daily_comb   = ppd_comb * exp_comb * ACCOUNT * RISK_FRAC
    monthly_comb = daily_comb * 22

    # Group by date to build daily buckets for MC
    daily_buckets={}
    for t in all_combined:
        r_net=t['r_gross']-t['spread']-0.10
        daily_buckets.setdefault(t['date'],[]).append(r_net)
    day_r_list=[np.asarray(v) for v in daily_buckets.values()]

    print(f'\n  Total trades (OOS):  {len(r_comb):,}')
    print(f'  Trading days:        {len(day_r_list)}')
    print(f'  Trades per day:      {ppd_comb:.2f}')
    print(f'  Win rate:            {wr(r_comb):.1f}%')
    print(f'  Profit factor:       {pf(r_comb):.2f}')
    print(f'  Expectancy:          {exp_comb:.4f}R')
    print(f'  Daily P&L (exp):     £{daily_comb:,.0f}')
    print(f'  Monthly P&L (exp):   £{monthly_comb:,.0f}')
    print(f'  Monthly (80% split): £{monthly_comb*0.8:,.0f}')

    # Compare vs original 7
    r_orig7 = np.asarray([t['r_gross']-t['spread']-0.10 for t in all_orig],float)
    ppd7 = len(all_orig)/OOS_DAYS
    print(f'\n  vs Original 7 instruments:')
    print(f'  {"":20} {"Original 7":>14} {"Extended":>14} {"Change":>10}')
    print('  '+'─'*58)
    print(f'  {"Trades/day":<20} {ppd7:>14.2f} {ppd_comb:>14.2f} {ppd_comb-ppd7:>+10.2f}')
    print(f'  {"PF":<20} {pf(r_orig7):>14.2f} {pf(r_comb):>14.2f} {pf(r_comb)-pf(r_orig7):>+10.2f}')
    print(f'  {"WR":<20} {wr(r_orig7):>13.1f}% {wr(r_comb):>13.1f}% {wr(r_comb)-wr(r_orig7):>+9.1f}%')
    print(f'  {"Monthly P&L":<20} £{ppd7*r_orig7.mean()*22*ACCOUNT*RISK_FRAC:>12,.0f} '
          f'£{monthly_comb:>12,.0f} £{monthly_comb - ppd7*r_orig7.mean()*22*ACCOUNT*RISK_FRAC:>+8,.0f}')

    # ── Quick Monte Carlo at 0.10R slippage ──────────────────────────────────
    print(f'\n\n{"═"*72}')
    print('  MONTE CARLO — COMBINED SYSTEM at 0.10R slippage ({N_SIMS:,} sims)')
    print(f'{"═"*72}')

    FTMO_TARGET=7000; FTMO_TOTAL=-7000; FTMO_DAILY=-3500; MIN_DAYS=4; MAX_DAYS=30
    rng=np.random.default_rng(42)
    risk_gbp=ACCOUNT*RISK_FRAC
    n_days_mc=len(day_r_list)
    passed=0; fail_dd=0; fail_daily=0; timeout=0
    final_eq=[]; days_to_pass=[]
    for _ in range(N_SIMS):
        equity=0.0; day_num=0; done=False
        while day_num<MAX_DAYS and not done:
            day_trades=day_r_list[rng.integers(0,n_days_mc)]
            day_pnl=0.0
            for r in day_trades:
                pnl=r*risk_gbp; day_pnl+=pnl; equity+=pnl
                if equity<=FTMO_TOTAL: fail_dd+=1; done=True; break
                if day_pnl<=FTMO_DAILY: fail_daily+=1; done=True; break
                if equity>=FTMO_TARGET and day_num+1>=MIN_DAYS:
                    passed+=1; days_to_pass.append(day_num+1); done=True; break
            day_num+=1
        if not done: timeout+=1
        final_eq.append(equity)
    fe=np.asarray(final_eq,float)
    dtp=np.asarray(days_to_pass)
    print(f'\n  At 0.10R slippage per trade, 0.5% risk:')
    print(f'  Pass rate:        {passed/N_SIMS*100:.1f}%')
    print(f'  Fail total DD:    {fail_dd/N_SIMS*100:.1f}%')
    print(f'  Fail daily limit: {fail_daily/N_SIMS*100:.1f}%')
    print(f'  Timeout:          {timeout/N_SIMS*100:.1f}%')
    if len(dtp): print(f'  Median days:      {np.median(dtp):.0f} days to pass')
    print(f'  p5 outcome:       £{np.percentile(fe,5):,.0f}')
    print(f'  Median outcome:   £{np.median(fe):,.0f}')

# ════════════════════════════════════════════════════════════════════════════
# VERDICT
# ════════════════════════════════════════════════════════════════════════════
print(f'\n\n{"═"*72}')
print('  VERDICT')
print(f'{"═"*72}')
# Recalculate honest PF at 0.10R slippage on original 7
r_h = np.asarray([t['r_gross']-t['spread']-0.10 for t in all_orig], float)
honest_pf = pf(r_h)
if honest_pf >= 2.0:
    print(f'  Slippage-adjusted PF: {honest_pf:.2f} — still above 2.0')
    print(f'  System is real. 0.10R slippage does not kill the edge.')
    print(f'  Next step: build the MQL5 EA.')
elif honest_pf >= 1.7:
    print(f'  Slippage-adjusted PF: {honest_pf:.2f} — edge survives but narrows')
    print(f'  Consider tighter entry filter or higher TP before building EA.')
else:
    print(f'  Slippage-adjusted PF: {honest_pf:.2f} — edge is marginal with slippage')
    print(f'  Do not build EA yet — investigate slippage reduction (limit orders).')
print(f'{"═"*72}\nDone.')
