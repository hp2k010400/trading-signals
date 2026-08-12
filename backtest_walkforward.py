"""
backtest_walkforward.py
H1 Inside Bar — year-by-year and walk-forward validation
Shows if the edge is consistent or just a bull-market artefact.

Run: python backtest_walkforward.py
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'UK100': 'UK100_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST = {'DAX':0.07,'UK100':0.07,'NAS100':0.06,'SP500':0.06,
        'EURUSD':0.08,'GBPUSD':0.08,'GOLD':0.08}
_m1 = {}

def load(k):
    fn = FILES.get(k,'')
    if not fn or not os.path.exists(fn): _m1[k]=None; return
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'],unit='s',utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k] = df.dropna()
    print(f'  {k}: {len(_m1[k]):,} bars')

def vsim(k, ep, d, entry, sl, tp_r, max_bars=480):
    m1=_m1[k]; sl_d=abs(entry-sl)
    if sl_d<=0: return -1.0
    end=min(ep+1+max_bars,len(m1))
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

def pf(r):
    r=np.asarray(r,float); w=r[r>0]; l=r[r<=0]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
def wr(r):
    r=np.asarray(r,float)
    return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0
def sharpe(r):
    r=np.asarray(r,float)
    return round(r.mean()/r.std()*np.sqrt(252),2) if r.std()>0 else 0.0

H1_HOURS = {
    'DAX':    {8,9,10,13,14},
    'UK100':  {8,9,10,13,14},
    'EURUSD': {8,9,13,14,15},
    'GBPUSD': {8,9,13,14,15},
    'GOLD':   {8,9,13,14,15},
    'NAS100': {13,14,15,16},
    'SP500':  {13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset({4}),'UK100':frozenset({4}),
    'EURUSD':frozenset({4}),'GBPUSD':frozenset({4}),'GOLD':frozenset({4}),
    'NAS100':frozenset({0,4}),'SP500':frozenset({0,4}),
}

def collect_h1_window(key, start_dt=None, end_dt=None):
    """Collect H1 inside bar signals, optionally filtered to a date window."""
    m1=_m1[key]; cost=COST[key]*1.5; mi=m1.index
    skip=H1_SKIP.get(key,frozenset({4}))
    p_hours=H1_HOURS.get(key,{8,9,13,14})

    # Filter M1 to window
    m1w = m1
    if start_dt: m1w = m1w[m1w.index >= start_dt]
    if end_dt:   m1w = m1w[m1w.index <  end_dt]
    if len(m1w) < 100: return []

    h1=m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1=h1[(h1['open']>0)]
    hl=list(h1.index); sigs=[]; day_count={}

    for i in range(1,len(hl)):
        ts=hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in p_hours: continue
        date_k=ts.date()
        if day_count.get(date_k,0)>=3: continue
        curr=h1.iloc[i]; prev=h1.iloc[i-1]
        if not(curr['high']<prev['high'] and curr['low']>prev['low']): continue
        ib_h=float(curr['high']); ib_l=float(curr['low'])
        if (ib_h-ib_l)<=0: continue
        if (ib_h-ib_l)/ib_h < 0.00015: continue
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
            sigs.append((ep,d,entry,sl,cost)); break
    return sigs

TP_R = 3.0  # best exit from MTF test

# ── LOAD ──────────────────────────────────────────────────────────────────────
print('Loading M1 data...')
for k in FILES: load(k)
loaded=[k for k in FILES if _m1.get(k) is not None]
print(f'Ready: {", ".join(loaded)}\n')

YEARS = list(range(2018, 2026))

# ══════════════════════════════════════════════════════════════════════════════
# YEAR-BY-YEAR BREAKDOWN
# ══════════════════════════════════════════════════════════════════════════════
print('═'*75)
print('  YEAR-BY-YEAR PF (H1 Inside Bar, 3R TP)')
print('═'*75)

W=7
hdr=f'{"Year":<6}{"Trades":>7}{"WR":>7}{"PF":>7}{"Sharpe":>8}{"NetR":>8}{"£@0.5%":>10}'
print(hdr); print('─'*len(hdr))

year_results={}
for yr in YEARS:
    s=pd.Timestamp(yr,1,1,tz='UTC'); e=pd.Timestamp(yr+1,1,1,tz='UTC')
    all_r=[]
    for k in loaded:
        sigs=collect_h1_window(k,s,e)
        for ep,d,entry,sl,cost in sigs:
            r=vsim(k,ep,d,entry,sl,TP_R)-cost
            all_r.append(r)
    if not all_r:
        print(f'{yr:<6}{"—":>7}'); continue
    r=np.asarray(all_r,float)
    net_r=r.sum(); monthly_pnl=net_r/12*70000*0.005
    flag=' ★' if pf(r)>=2.0 else (' ✗' if pf(r)<1.0 else '')
    print(f'{yr:<6}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{sharpe(r):>8.2f}'
          f'{net_r:>8.1f}R{monthly_pnl:>9,.0f}{flag}')
    year_results[yr]={'n':len(r),'pf':pf(r),'wr':wr(r),'net_r':net_r}

print('─'*len(hdr))
# All years combined
all_r_total=[]
for k in loaded:
    sigs=collect_h1_window(k)
    for ep,d,entry,sl,cost in sigs:
        all_r_total.append(vsim(k,ep,d,entry,sl,TP_R)-cost)
r_tot=np.asarray(all_r_total,float)
print(f'{"ALL":<6}{len(r_tot):>7}{wr(r_tot):>6.1f}%{pf(r_tot):>7.2f}'
      f'{sharpe(r_tot):>8.2f}{r_tot.sum():>8.1f}R{r_tot.sum()/8/12*70000*0.005:>9,.0f}')
print('═'*len(hdr))

# ══════════════════════════════════════════════════════════════════════════════
# PER-INSTRUMENT YEAR-BY-YEAR
# ══════════════════════════════════════════════════════════════════════════════
print('\n\n' + '═'*75)
print('  PER-INSTRUMENT YEAR-BY-YEAR PF')
print('═'*75)
W=7
yr_hdr=f'{"Instr":<8}'+''.join(f'{y:>{W}}' for y in YEARS)+f'{"ALL":>{W}}'
print(yr_hdr); print('─'*len(yr_hdr))

for k in loaded:
    row=f'{k:<8}'
    all_k=[]
    for yr in YEARS:
        s=pd.Timestamp(yr,1,1,tz='UTC'); e=pd.Timestamp(yr+1,1,1,tz='UTC')
        sigs=collect_h1_window(k,s,e)
        if not sigs: row+=f'{"—":>{W}}'; continue
        r=np.asarray([vsim(k,ep,d,entry,sl,TP_R)-cost for ep,d,entry,sl,cost in sigs],float)
        all_k.extend(r)
        p=pf(r)
        tag='+' if p>=2.0 else ('×' if p<1.0 else ' ')
        row+=f'{tag}{p:>{W-1}.2f}'
    if all_k:
        r_all=np.asarray(all_k,float)
        row+=f'{pf(r_all):>{W}.2f}'
    print(row)
print('─'*len(yr_hdr))
print('  + = PF≥2.0    × = PF<1.0    blank = 1.0-2.0')

# ══════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD: 2018-2022 IN-SAMPLE | 2022-2026 OUT-OF-SAMPLE
# ══════════════════════════════════════════════════════════════════════════════
print('\n\n' + '═'*75)
print('  WALK-FORWARD: IN-SAMPLE 2018-2022 vs OUT-OF-SAMPLE 2022-2026')
print('═'*75)

IS_START=pd.Timestamp(2018,1,1,tz='UTC')
IS_END  =pd.Timestamp(2022,1,1,tz='UTC')
OOS_START=pd.Timestamp(2022,1,1,tz='UTC')
OOS_END  =pd.Timestamp(2026,1,1,tz='UTC')

for label,s,e in [('IN-SAMPLE  (2018-2022)',IS_START,IS_END),
                   ('OUT-OF-SAMPLE (2022-2026)',OOS_START,OOS_END)]:
    all_r=[]
    inst_r={}
    for k in loaded:
        sigs=collect_h1_window(k,s,e)
        r=np.asarray([vsim(k,ep,d,entry,sl,TP_R)-cost for ep,d,entry,sl,cost in sigs],float)
        all_r.extend(r); inst_r[k]=r

    r=np.asarray(all_r,float)
    n_days=(e-s).days/365*252
    ppd=len(r)/n_days if n_days>0 else 0
    monthly_pnl=r.mean()*ppd*22*70000*0.005 if len(r) else 0
    print(f'\n  {label}')
    print(f'  Trades: {len(r):,}  |  {ppd:.2f}/day  |  WR: {wr(r):.1f}%  |  '
          f'PF: {pf(r):.2f}  |  Sharpe: {sharpe(r):.2f}')
    print(f'  Est monthly P&L @ 0.5% risk £70k: £{monthly_pnl:,.0f}')
    print(f'  Per instrument:')
    for k,ri in sorted(inst_r.items()):
        if not len(ri): continue
        flag=' ★' if pf(ri)>=2.0 else (' ✗' if pf(ri)<1.0 else '')
        print(f'    {k:<8} {len(ri):>5} trades  WR {wr(ri):>5.1f}%  PF {pf(ri):.2f}{flag}')

# ══════════════════════════════════════════════════════════════════════════════
# DRAWDOWN ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
print('\n\n' + '═'*75)
print('  DRAWDOWN ANALYSIS (full period, 0.5% risk £70k)')
print('═'*75)

# Rebuild full trade list with timestamps for drawdown calc
all_trades=[]
for k in loaded:
    sigs=collect_h1_window(k)
    m1=_m1[k]
    for ep,d,entry,sl,cost in sigs:
        r=vsim(k,ep,d,entry,sl,TP_R)-cost
        ts=m1.index[ep] if ep<len(m1) else None
        if ts: all_trades.append((ts,r))

all_trades.sort(key=lambda x:x[0])
if all_trades:
    r_arr=np.array([t[1] for t in all_trades])*70000*0.005
    cum=np.cumsum(r_arr)
    peak=np.maximum.accumulate(cum)
    dd=cum-peak
    max_dd=dd.min()
    max_dd_pct=max_dd/70000*100

    # Longest losing streak
    results_seq=[t[1] for t in all_trades]
    max_streak=cur_streak=0
    for r in results_seq:
        if r<0: cur_streak+=1; max_streak=max(max_streak,cur_streak)
        else: cur_streak=0

    # Consecutive losing days
    daily_r={}
    for ts,r in all_trades:
        dk=ts.date()
        daily_r[dk]=daily_r.get(dk,0)+r*70000*0.005
    daily_vals=sorted(daily_r.items())
    max_day_loss=min(v for _,v in daily_vals) if daily_vals else 0
    days_above_ftmo_limit=sum(1 for _,v in daily_vals if v<-3500)

    print(f'  Total net P&L:      £{cum[-1]:>10,.0f}')
    print(f'  Max drawdown:       £{max_dd:>10,.0f}  ({max_dd_pct:.1f}% of £70k)')
    print(f'  Worst single trade: £{min(r_arr):>10,.0f}')
    print(f'  Best single trade:  £{max(r_arr):>10,.0f}')
    print(f'  Max losing streak:  {max_streak:>4} trades in a row')
    print(f'  Worst single day:   £{max_day_loss:>10,.0f}')
    print(f'  Days breaching FTMO -£3,500 daily limit: {days_above_ftmo_limit}')
    print(f'\n  FTMO Safety: {"⚠ REVIEW POSITION SIZING" if days_above_ftmo_limit>0 else "✓ Daily limit respected at 0.5% risk"}')

print('\n' + '═'*75)
print('  VERDICT')
print('═'*75)
oos_r=[]
for k in loaded:
    sigs=collect_h1_window(k,OOS_START,OOS_END)
    for ep,d,entry,sl,cost in sigs:
        oos_r.append(vsim(k,ep,d,entry,sl,TP_R)-cost)
oos_pf=pf(np.asarray(oos_r,float))

if oos_pf>=2.0:
    print(f'  ✓ OOS PF {oos_pf:.2f} — EDGE IS REAL. Build the EA.')
elif oos_pf>=1.5:
    print(f'  ~ OOS PF {oos_pf:.2f} — Edge degrades but still profitable. Add filters.')
elif oos_pf>=1.2:
    print(f'  ⚠ OOS PF {oos_pf:.2f} — Marginal. More research needed.')
else:
    print(f'  ✗ OOS PF {oos_pf:.2f} — Edge does not survive OOS. Do not trade.')
print('═'*75)
print('\nDone.')
