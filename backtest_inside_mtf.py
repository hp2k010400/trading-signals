"""
backtest_inside_mtf.py
Multi-Timeframe Inside Bar: D1 (baseline) | H4 | H1 power hours
Same compression→expansion principle, higher frequency at lower timeframes.

Run: python backtest_inside_mtf.py
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
YEARS = 8

def load(k):
    fn = FILES.get(k,'')
    if not fn or not os.path.exists(fn): _m1[k]=None; return
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'],unit='s',utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k] = df.dropna()
    print(f'  {k}: {len(_m1[k]):,} bars')

def vsim(k, ep, d, entry, sl, tp_r, max_bars=1200):
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

COLS = [('1.5R',1.5),('2R',2.0),('3R',3.0)]

def print_table(title, results, total_trading_days):
    W=9
    print(f'\n{"═"*70}')
    print(f'  {title}')
    print(f'{"═"*70}')
    hdr=f'{"Instrument":<12}{"Trades":>8}{"Per Day":>8}'+''.join(f'{c:>{W}}' for c,_ in COLS)
    print(hdr); print('─'*len(hdr))
    sys_r={c:[] for c,_ in COLS}; total=0
    for k,rd in sorted(results.items()):
        if not rd['1.5R']: continue
        n=len(rd['1.5R']); total+=n; ppd=n/total_trading_days
        row=f'{k:<12}{n:>8}{ppd:>8.2f}'
        for c,_ in COLS:
            r=np.asarray(rd[c],float); sys_r[c].extend(r)
            row+=f'{pf(r):>{W}.2f}'
        print(row)
    print('─'*len(hdr))
    ppd_total=total/total_trading_days
    sys_row=f'{"SYSTEM":<12}{total:>8}{ppd_total:>8.2f}'
    best_pf=0; best_col='1.5R'
    for c,_ in COLS:
        r=np.asarray(sys_r[c],float); p=pf(r)
        sys_row+=f'{p:>{W}.2f}'
        if p>best_pf: best_pf=p; best_col=c
    print(sys_row)
    flag=' ★★★ TARGET HIT' if best_pf>=2.0 else (' ★★' if best_pf>=1.7 else (' ★' if best_pf>=1.5 else ''))
    print(f'\n  Best: {best_col} PF {best_pf:.2f}{flag} | {ppd_total:.2f} signals/day | '
          f'WR {wr(np.asarray(sys_r[best_col],float)):.1f}%')

    # Monthly P&L estimate at 0.5% risk on £70k
    risk_per_trade = 70000 * 0.005
    r_best = np.asarray(sys_r[best_col],float)
    exp_r = r_best.mean() if len(r_best) else 0
    monthly_trades = ppd_total * 22
    monthly_pnl = monthly_trades * exp_r * risk_per_trade
    print(f'  Monthly P&L est (0.5% risk, £70k): £{monthly_pnl:,.0f}  '
          f'({monthly_trades:.0f} trades/month x {exp_r:.3f}R avg)')
    return best_pf, ppd_total

# ── D1 INSIDE BAR (baseline — indices only) ───────────────────────────────────
def collect_d1(key, skip=frozenset({4})):
    m1=_m1[key]; cost=COST[key]*1.5; mi=m1.index
    d1=m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    dl=list(d1.index); sigs=[]
    for i in range(2,len(dl)):
        ts=dl[i]
        if ts.dayofweek in skip: continue
        prev=d1.iloc[i-1]; prev2=d1.iloc[i-2]
        if not(prev['high']<prev2['high'] and prev['low']>prev2['low']): continue
        id_h=float(prev['high']); id_l=float(prev['low'])
        if (id_h-id_l)<=0: continue
        day=pd.Timestamp(ts.date(),tz='UTC')
        window=m1[(m1.index>=day)&(m1.index<day+pd.Timedelta(hours=18))]
        for j in range(len(window)):
            b=window.iloc[j]
            if b['high']>id_h: d=1; entry=id_h; sl=id_l
            elif b['low']<id_l: d=-1; entry=id_l; sl=id_h
            else: continue
            ep=mi.searchsorted(window.index[j])
            if ep>=len(m1): break
            sigs.append((ep,d,entry,sl,cost)); break
    return sigs

# ── H4 INSIDE BAR ─────────────────────────────────────────────────────────────
# Inside H4 bar during active session, entry on next H4 bar's first M1 break
H4_SESSION = {
    'DAX':    {8,12},
    'UK100':  {8,12},
    'EURUSD': {8,12},
    'GBPUSD': {8,12},
    'GOLD':   {8,12,16},
    'NAS100': {12,16},
    'SP500':  {12,16},
}
H4_SKIP = {
    'DAX':frozenset({4}),'UK100':frozenset({4}),
    'EURUSD':frozenset({4}),'GBPUSD':frozenset({4}),'GOLD':frozenset({4}),
    'NAS100':frozenset({0,4}),'SP500':frozenset({0,4}),
}

def collect_h4(key):
    m1=_m1[key]; cost=COST[key]*1.5; mi=m1.index
    skip=H4_SKIP.get(key,frozenset({4}))
    s_hours=H4_SESSION.get(key,{8,12})
    h4=m1.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h4=h4[(h4['open']>0)]
    hl=list(h4.index); sigs=[]
    for i in range(1,len(hl)):
        ts=hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in s_hours: continue
        curr=h4.iloc[i]; prev=h4.iloc[i-1]
        if not(curr['high']<prev['high'] and curr['low']>prev['low']): continue
        ib_h=float(curr['high']); ib_l=float(curr['low'])
        if (ib_h-ib_l)<=0: continue
        # Entry window: next 8 hours after inside bar closes
        entry_start=ts+pd.Timedelta(hours=4)
        window=m1[(m1.index>=entry_start)&(m1.index<entry_start+pd.Timedelta(hours=8))]
        if len(window)==0: continue
        for j in range(len(window)):
            b=window.iloc[j]
            if b['high']>ib_h: d=1; entry=ib_h; sl=ib_l
            elif b['low']<ib_l: d=-1; entry=ib_l; sl=ib_h
            else: continue
            ep=mi.searchsorted(window.index[j])
            if ep>=len(m1): break
            sigs.append((ep,d,entry,sl,cost)); break
    return sigs

# ── H1 INSIDE BAR (power hours only, max 3 per instrument per day) ────────────
H1_HOURS = {
    'DAX':    {8,9,10,13,14},
    'UK100':  {8,9,10,13,14},
    'EURUSD': {8,9,13,14,15},
    'GBPUSD': {8,9,13,14,15},
    'GOLD':   {8,9,13,14,15},
    'NAS100': {13,14,15,16},
    'SP500':  {13,14,15,16},
}

def collect_h1(key):
    m1=_m1[key]; cost=COST[key]*1.5; mi=m1.index
    skip=H4_SKIP.get(key,frozenset({4}))
    p_hours=H1_HOURS.get(key,{8,9,13,14})
    h1=m1.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1=h1[(h1['open']>0)]
    hl=list(h1.index); sigs=[]; day_count={}
    for i in range(1,len(hl)):
        ts=hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in p_hours: continue
        date_k=ts.date()
        if day_count.get(date_k,0)>=3: continue  # max 3 H1 signals per day
        curr=h1.iloc[i]; prev=h1.iloc[i-1]
        if not(curr['high']<prev['high'] and curr['low']>prev['low']): continue
        ib_h=float(curr['high']); ib_l=float(curr['low'])
        if (ib_h-ib_l)<=0: continue
        # Must have meaningful range (not micro-compression noise)
        if (ib_h-ib_l)/(ib_h) < 0.00015: continue  # skip tiny ranges
        entry_start=ts+pd.Timedelta(hours=1)
        window=m1[(m1.index>=entry_start)&(m1.index<entry_start+pd.Timedelta(hours=3))]
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

# ── RUN ───────────────────────────────────────────────────────────────────────
print('Loading M1 data...')
for k in FILES: load(k)
loaded=[k for k in FILES if _m1.get(k) is not None]
print(f'Ready: {", ".join(loaded)}\n')

INDICES=['DAX','UK100','NAS100','SP500']
ALL=[k for k in loaded]
TRADING_DAYS=YEARS*252

def run(title, fn, instruments, max_bars=1200):
    print(f'Collecting {title}...')
    res={}
    for k in instruments:
        if _m1.get(k) is None: continue
        sigs=fn(k)
        ppd=len(sigs)/TRADING_DAYS
        print(f'  {k}: {len(sigs)} signals ({ppd:.2f}/day)')
        if not sigs: continue
        rd={c:[] for c,_ in COLS}
        for ep,d,entry,sl,cost in sigs:
            for c,tv in COLS:
                rd[c].append(vsim(k,ep,d,entry,sl,tv,max_bars=max_bars)-cost)
        res[k]=rd
    return print_table(title,res,TRADING_DAYS)

summary={}

print('='*70)
print(' D1 INSIDE BAR — indices baseline')
print('='*70)
summary['D1 Indices']=run('D1 INSIDE BAR (indices)',
    lambda k: collect_d1(k, frozenset({0,4}) if k in ['NAS100','SP500'] else frozenset({4})),
    INDICES, max_bars=4800)

print('\n'+'='*70)
print(' H4 INSIDE BAR — indices')
print('='*70)
summary['H4 Indices']=run('H4 INSIDE BAR (indices)',collect_h4,INDICES,max_bars=2400)

print('\n'+'='*70)
print(' H4 INSIDE BAR — all instruments')
print('='*70)
summary['H4 All']=run('H4 INSIDE BAR (all instruments)',collect_h4,ALL,max_bars=2400)

print('\n'+'='*70)
print(' H1 INSIDE BAR — power hours, indices')
print('='*70)
summary['H1 Indices']=run('H1 INSIDE BAR power hours (indices)',collect_h1,INDICES,max_bars=480)

print('\n'+'='*70)
print(' H1 INSIDE BAR — power hours, all instruments')
print('='*70)
summary['H1 All']=run('H1 INSIDE BAR power hours (all)',collect_h1,ALL,max_bars=480)

# ── FINAL LEADERBOARD ─────────────────────────────────────────────────────────
print('\n\n'+'═'*70)
print('  LEADERBOARD')
print('═'*70)
print(f'  {"Strategy":<25}{"Best PF":>10}{"Signals/Day":>14}{"Monthly P&L est":>18}')
print('  '+'─'*65)
for name,(best_pf,ppd) in sorted(summary.items(),key=lambda x:-x[1][0]):
    monthly=ppd*22; risk=70000*0.005
    # rough expectancy: PF 2.0 WR 50% 2R → 0.5R expectancy
    if best_pf>0:
        # WR estimate from PF: PF = WR*R / (1-WR)*1 → WR = PF/(PF+R) for R=best TP
        wr_est=best_pf/(best_pf+2)  # assume 2R TP
        exp_r=wr_est*2-(1-wr_est)*1
        monthly_pnl=monthly*exp_r*risk
    else: monthly_pnl=0
    flag=' ★★★' if best_pf>=2.0 else (' ★★' if best_pf>=1.7 else (' ★' if best_pf>=1.5 else ''))
    print(f'  {name:<25}{best_pf:>10.2f}{monthly:>14.1f}{monthly_pnl:>17,.0f}{flag}')
print('═'*70)
print('\nDone.')
