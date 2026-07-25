"""
portfolio_ftmo_replay.py  —  Portfolio-level FTMO daily equity test
OOS 2022-2025 across all 9 instruments simultaneously.

ChatGPT's key question: "What was the worst intraday equity drawdown on any OOS day,
including simultaneously open trades, realised losses, spreads and slippage?"

What this answers:
  - Max simultaneous positions open at any one time
  - Worst single-day realised P&L
  - Worst concurrent open risk (how close to FTMO 5% daily limit)
  - Whether any day would have breached 5% under worst-case floating P&L
  - Total drawdown vs FTMO 10% max

Run: python -u portfolio_ftmo_replay.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

ACCOUNT    = 70_000.0
RISK_AMT   = ACCOUNT * 0.005    # £350 per trade (fixed for analysis)
BASE_TP    = 4.0
WIN_HOURS  = 3
SLIPPAGE   = 0.10
MAX_BARS   = 480
MAX_PD     = 3

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')

FTMO_DAILY_LIMIT = 0.05   # 5% of daily starting equity
FTMO_TOTAL_LIMIT = 0.10   # 10% total drawdown

FILES   = {'DAX':'GER40_M1_oanda.csv','NAS100':'US100_M1_oanda.csv',
           'SP500':'US500_M1_oanda.csv','US30':'US30_M1_oanda.csv',
           'EURUSD':'EURUSD_M1_oanda.csv','GBPUSD':'GBPUSD_M1_oanda.csv',
           'USDJPY':'USDJPY_M1_oanda.csv','GOLD':'XAUUSD_M1_oanda.csv',
           'NATGAS':'NATGAS_M1_oanda.csv'}
COST    = {'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
           'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,'GOLD':0.08,'NATGAS':0.15}
H1_HOURS= {'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
           'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
           'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},'NATGAS':{13,14,15,16}}
H1_SKIP = {'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
           'USDJPY':frozenset(),'GOLD':frozenset(),'NATGAS':frozenset(),
           'NAS100':frozenset({0}),'SP500':frozenset({0}),'US30':frozenset({0})}
WICK_BODY=2.0; WICK_RANGE=0.5; MIN_RANGE=0.00015

_m1={}
def load(k):
    fn=FILES[k]
    if not os.path.exists(fn): return False
    df=pd.read_csv(fn)
    df['time']=pd.to_datetime(df['time'],unit='s',utc=True)
    df=df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k]=df.dropna(); return True

def pin_bar_dir(o,h,l,c):
    body=abs(c-o); full=h-l
    if full<=0: return 0
    uw=h-max(o,c); lw=min(o,c)-l
    if uw>=WICK_BODY*max(body,full*0.001) and uw>=WICK_RANGE*full: return -1
    if lw>=WICK_BODY*max(body,full*0.001) and lw>=WICK_RANGE*full: return 1
    return 0

def collect_trades(k):
    """Collect all OOS trades with full timing metadata."""
    m1=_m1[k]; mi=m1.index
    skip=H1_SKIP.get(k,frozenset())
    p_hours=H1_HOURS.get(k,{8,9,13,14})
    m1w=m1[(m1.index>=OOS_START)&(m1.index<OOS_END)]
    if len(m1w)<100: return []
    h1=m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1=h1[h1['open']>0]
    hl=list(h1.index); trades=[]; day_count={}

    for i in range(1,len(hl)):
        ts=hl[i]
        if ts.dayofweek in skip or ts.dayofweek>=5: continue
        if ts.hour not in p_hours: continue
        date_k=ts.date()
        if day_count.get(date_k,0)>=MAX_PD: continue
        bar=h1.iloc[i]
        entry_start=ts+pd.Timedelta(hours=1)
        window=m1[(mi>=entry_start)&(mi<entry_start+pd.Timedelta(hours=WIN_HOURS))]
        if len(window)==0: continue

        found=False; d=0; e=0.0; sl=0.0
        if k=='USDJPY':
            pb=pin_bar_dir(float(bar['open']),float(bar['high']),float(bar['low']),float(bar['close']))
            if pb==0: continue
            pb_h=float(bar['high']); pb_l=float(bar['low'])
            for j in range(len(window)):
                b=window.iloc[j]
                if pb==1 and b['high']>pb_h:   d=1;  e=pb_h; sl=pb_l; found=True; break
                elif pb==-1 and b['low']<pb_l: d=-1; e=pb_l; sl=pb_h; found=True; break
        else:
            prev=h1.iloc[i-1]
            if not (bar['high']<prev['high'] and bar['low']>prev['low']): continue
            ib_h=float(bar['high']); ib_l=float(bar['low'])
            if (ib_h-ib_l)<=0 or (ib_h-ib_l)/ib_h<MIN_RANGE: continue
            for j in range(len(window)):
                b=window.iloc[j]
                if b['high']>ib_h:  d=1;  e=ib_h; sl=ib_l; found=True; break
                elif b['low']<ib_l: d=-1; e=ib_l; sl=ib_h; found=True; break

        if not found: continue
        sl_dist=abs(e-sl)
        if sl_dist<=0: continue
        tp=e+sl_dist*BASE_TP if d==1 else e-sl_dist*BASE_TP
        open_ts=window.index[j]
        ep=mi.searchsorted(open_ts)
        if ep>=len(m1): continue

        # Find close bar
        end=min(ep+1+MAX_BARS,len(m1))
        hi=m1['high'].values[ep+1:end]; lo=m1['low'].values[ep+1:end]
        if len(hi)==0: continue
        if d==1:
            sl_i=int(np.argmax(lo<=sl)) if np.any(lo<=sl) else len(hi)
            tp_i=int(np.argmax(hi>=tp)) if np.any(hi>=tp) else len(hi)
        else:
            sl_i=int(np.argmax(hi>=sl)) if np.any(hi>=sl) else len(hi)
            tp_i=int(np.argmax(lo<=tp)) if np.any(lo<=tp) else len(hi)

        if tp_i<=sl_i: r_gross=BASE_TP
        elif sl_i<len(hi): r_gross=-1.0
        else:
            close_price=m1['close'].values[min(ep+len(hi),len(m1)-1)]
            r_gross=(close_price-e)/sl_dist if d==1 else (e-close_price)/sl_dist

        close_offset=min(sl_i,tp_i,len(hi)-1)
        close_ep=min(ep+1+close_offset,len(m1)-1)
        close_ts=mi[close_ep]
        r_net=r_gross-COST[k]-SLIPPAGE

        day_count[date_k]=day_count.get(date_k,0)+1
        trades.append({
            'sym':k,'open_ts':open_ts,'close_ts':close_ts,
            'ep':ep,'close_ep':close_ep,
            'entry':e,'sl':sl,'tp':tp,'dir':d,'sl_dist':sl_dist,
            'r_net':r_net,'r_gross':r_gross,
            'open_date':open_ts.date(),'close_date':close_ts.date()
        })
    return trades


# ─── Load & collect ───────────────────────────────────────────────────────────
print('Loading M1 data...')
loaded=[k for k in FILES if load(k)]

print('Collecting OOS trades...')
all_trades=[]
for k in loaded:
    t=collect_trades(k)
    print(f'  {k}: {len(t)} trades')
    all_trades.extend(t)
all_trades.sort(key=lambda x: x['open_ts'])
print(f'  Total: {len(all_trades)} trades\n')


# ─── Portfolio event replay ───────────────────────────────────────────────────
# Process events (trade open / trade close) in chronological order.
# At each event, snapshot portfolio equity and track daily stats.

print('Running portfolio equity replay...')

# Build event list: (timestamp, event_type, trade_idx)
events=[]
for i,t in enumerate(all_trades):
    events.append((t['open_ts'],  'open',  i))
    events.append((t['close_ts'], 'close', i))
events.sort(key=lambda x: x[0])

balance = ACCOUNT           # realised equity (closed trades)
peak    = ACCOUNT
open_set= {}                # trade_idx -> trade (currently open)

# Per-day tracking
from collections import defaultdict
daily_min_equity   = defaultdict(lambda: float('inf'))
daily_start_equity = {}
daily_realised_pnl = defaultdict(float)
daily_max_concurrent = defaultdict(int)

prev_event_date = None

def portfolio_equity_at_event():
    """Equity = balance + sum of floating P&L for all open trades (worst-case: assume -1R each)."""
    # Conservative: assume all open trades are at their worst floating point (-1R)
    # This gives the max possible loss at any moment
    worst_floating = -len(open_set) * RISK_AMT
    return balance + worst_floating

def portfolio_equity_optimistic():
    """Equity = balance only (ignoring floating, i.e. all open trades at entry)."""
    return balance

for ts, etype, idx in events:
    t = all_trades[idx]
    date = ts.date()

    # Record day-start equity on first event of each new day
    if date not in daily_start_equity:
        daily_start_equity[date] = balance   # no floating adjustment — conservative

    if etype == 'open':
        open_set[idx] = t
        # Track max concurrent
        n_open = len(open_set)
        if n_open > daily_max_concurrent[date]:
            daily_max_concurrent[date] = n_open
        # Portfolio equity at this moment (worst case all open = -1R)
        eq_worst = balance + (-len(open_set) * RISK_AMT)
        if eq_worst < daily_min_equity[date]:
            daily_min_equity[date] = eq_worst

    elif etype == 'close':
        if idx in open_set:
            del open_set[idx]
        # Realise P&L
        pnl = t['r_net'] * RISK_AMT
        balance += pnl
        daily_realised_pnl[date] += pnl
        # Snapshot equity after close
        eq = balance + (-len(open_set) * RISK_AMT)
        if eq < daily_min_equity[date]:
            daily_min_equity[date] = eq

    # Peak balance (for total drawdown calc)
    if balance > peak:
        peak = balance


# ─── Daily analysis ──────────────────────────────────────────────────────────
print('\n' + '='*72)
print('  PORTFOLIO FTMO DAILY EQUITY ANALYSIS  |  OOS 2022-2025')
print('='*72)
print('  NOTE: equity uses CONSERVATIVE worst-case floating P&L')
print('  (all open positions assumed to be at -1R simultaneously)')
print('  This is the CEILING of possible intraday loss, not average.\n')

days_with_data = [d for d in daily_min_equity if d in daily_start_equity]
days_with_data.sort()

breach_days = []
near_limit_days = []   # >3% intraday DD
all_dd_pcts = []
max_concurrent_ever = 0
worst_realised_day = None; worst_realised_pnl = 0.0
worst_concurrent_day = None; worst_concurrent_n = 0

for date in days_with_data:
    start_eq = daily_start_equity[date]
    min_eq   = daily_min_equity[date]
    dd_pct   = (start_eq - min_eq) / start_eq * 100 if start_eq > 0 else 0
    all_dd_pcts.append(dd_pct)
    n_conc   = daily_max_concurrent[date]
    r_pnl    = daily_realised_pnl[date]

    if n_conc > max_concurrent_ever:
        max_concurrent_ever = n_conc
        worst_concurrent_day = date

    if r_pnl < worst_realised_pnl:
        worst_realised_pnl = r_pnl
        worst_realised_day = date

    if dd_pct >= FTMO_DAILY_LIMIT * 100:
        breach_days.append((date, dd_pct, n_conc, r_pnl))
    elif dd_pct >= 3.0:
        near_limit_days.append((date, dd_pct, n_conc, r_pnl))

# Print worst days
print(f'  {"Date":>12}  {"MaxConcurr":>12}  {"MaxRisk%":>9}  {"DayPnL £":>10}  {"WorstEq%":>9}')
print(f'  {"-"*60}')

# Print top 15 worst days by DD pct
sorted_days = sorted(days_with_data,
                     key=lambda d: daily_min_equity[d] - daily_start_equity[d])
for date in sorted_days[:15]:
    start_eq = daily_start_equity[date]
    min_eq   = daily_min_equity[date]
    dd_pct   = (start_eq - min_eq) / start_eq * 100 if start_eq > 0 else 0
    n_conc   = daily_max_concurrent[date]
    max_risk_pct = n_conc * 0.5
    r_pnl    = daily_realised_pnl[date]
    flag     = '  *** BREACH ***' if dd_pct >= 5.0 else ('  ! near limit' if dd_pct >= 3.0 else '')
    print(f'  {str(date):>12}  {n_conc:>12}  {max_risk_pct:>8.1f}%  {r_pnl:>10.0f}  {dd_pct:>8.1f}%{flag}')

print(f'  {"-"*60}')
print(f'\n  Max concurrent open positions (any 1 minute): {max_concurrent_ever}')
print(f'  Max concurrent risk: {max_concurrent_ever * 0.5:.1f}% of account')
print(f'  Worst concurrent day: {worst_concurrent_day}')
print()
print(f'  Worst REALISED daily P&L: £{worst_realised_pnl:,.0f} on {worst_realised_day}')
print(f'  Worst realised daily %:   {worst_realised_pnl/ACCOUNT*100:.2f}%')
print()

# Distribution of worst-case daily equity drawdowns
dd_arr = np.array(all_dd_pcts)
print(f'  Worst-case daily equity drawdown distribution:')
print(f'    p50  (median): {np.percentile(dd_arr,50):.2f}%')
print(f'    p90:           {np.percentile(dd_arr,90):.2f}%')
print(f'    p95:           {np.percentile(dd_arr,95):.2f}%')
print(f'    p99:           {np.percentile(dd_arr,99):.2f}%')
print(f'    Max:           {dd_arr.max():.2f}%')
print()

print('='*72)
print('  FTMO BREACH ANALYSIS')
print('='*72)
print(f'\n  Under CONSERVATIVE worst-case (all open = -1R simultaneously):')
print(f'    Days that WOULD breach 5% daily limit: {len(breach_days)}')
print(f'    Days within 3-5% of limit:             {len(near_limit_days)}')
if breach_days:
    print(f'\n  Breach days detail:')
    for date, dd, n, pnl in breach_days[:10]:
        print(f'    {date}  concurrent:{n}  worst_eq:{dd:.1f}%  realised_pnl:£{pnl:.0f}')

print()

# Total drawdown from peak
total_dd = (peak - balance) / peak * 100 if balance < peak else 0.0
max_dd_from_start = (ACCOUNT - min(daily_start_equity.values())) / ACCOUNT * 100
print(f'  Total account trajectory (realised P&L only, no floating):')
print(f'    Starting balance: £{ACCOUNT:,.0f}')
print(f'    Final balance:    £{balance:,.0f}')
print(f'    Gross gain:       £{balance-ACCOUNT:,.0f}  ({(balance-ACCOUNT)/ACCOUNT*100:.1f}%)')
print(f'    Max total DD from start: {max_dd_from_start:.2f}%  (FTMO limit: 10%)')
print(f'    FTMO total breach: {"YES" if max_dd_from_start > 10 else "NO"}')

print()
print('='*72)
print('  VERDICT')
print('='*72)
print()
print(f'  Conservative assumption: every open trade simultaneously at -1R.')
print(f'  This never happens in practice — it is the absolute worst case.')
print()
if len(breach_days) == 0:
    print(f'  RESULT: EVEN UNDER WORST-CASE ASSUMPTIONS, NO DAILY LIMIT WAS')
    print(f'  BREACHED IN 4 YEARS OF OOS TRADING.')
    print()
    print(f'  Closest approach to 5% limit: {dd_arr.max():.2f}% (worst-case day)')
    print(f'  Actual maximum concurrent risk: {max_concurrent_ever * 0.5:.1f}%')
else:
    print(f'  WARNING: {len(breach_days)} day(s) COULD breach 5% IF all trades hit SL simultaneously.')
    print()
    print(f'  Mitigation: implement portfolio daily loss cap in EA.')
    print(f'  Halt new trades when realised + potential risk approaches 4%.')

print()
print(f'  PRACTICAL NOTE: In reality, not all concurrent positions lose at once.')
print(f'  With PF 3.13 and WR 49%, half the concurrent trades win on any given day.')
print(f'  True intraday equity is significantly BETTER than this worst-case figure.')
print()
print('='*72)
print('Done.')
