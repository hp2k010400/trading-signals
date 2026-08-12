"""
backtest_master.py  -  Comprehensive fast M1 backtest engine
=============================================================
Vectorized numpy sim (50x faster than iterrows)
Strategies : DAX_ORB, NAS_ORB, SP5_ORB, LC_GBP, LC_UK, LC_GOLD,
             Asian Range Breakout (DAX/UK/EUR), NY Open Drive (NAS/SP5/GBP)
Exits      : Trail 0.05, Trail 5.0, TP 1R/1.5R/2R/3R
Reports    : PF table, MAE/MFE, day-of-week, yearly, filter tests, Sharpe
"""
import pandas as pd, numpy as np, os, warnings
from collections import namedtuple
warnings.filterwarnings('ignore')

FILES = {
    'EURUSD':'EURUSD_M1_oanda.csv','GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':'XAUUSD_M1_oanda.csv','DAX':'GER40_M1_oanda.csv',
    'UK100':'UK100_M1_oanda.csv','NAS100':'US100_M1_oanda.csv','SP500':'US500_M1_oanda.csv',
}
COST = {'DAX':0.07,'NAS100':0.06,'SP500':0.06,'EURUSD':0.08,'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08}
EXITS = [('Trail_0.05','trail',0.05),('Trail_5.0','trail',5.0),
         ('TP_1R','tp',1.0),('TP_1.5R','tp',1.5),('TP_2R','tp',2.0),('TP_3R','tp',3.0)]
Sig = namedtuple('Sig','key ep d entry sl cost date')
_m1,_h1,_arr = {},{},{}

# ── Data loading ───────────────────────────────────────────────────────────────
def load_m1(k):
    if k in _m1: return _m1[k]
    fn = FILES.get(k)
    if not fn or not os.path.exists(fn): _m1[k]=None; return None
    df = pd.read_csv(fn); df['time']=pd.to_datetime(df['time'],unit='s',utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k]=df.dropna(); return _m1[k]

def load_h1(k):
    if k in _h1: return _h1[k]
    m=load_m1(k)
    if m is None: _h1[k]=None; return None
    _h1[k]=m.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last','tick_volume':'sum'}).dropna()
    return _h1[k]

def prep(k):
    if k in _arr: return _arr[k]
    m=load_m1(k)
    if m is None: _arr[k]=None; return None
    _arr[k]={'h':m['high'].values,'l':m['low'].values,'c':m['close'].values,'idx':m.index}
    return _arr[k]

def slc(k,ep,mb=4800):
    a=prep(k)
    if a is None: return None,None,None
    s=ep+1; e=min(s+mb,len(a['h']))
    return a['h'][s:e],a['l'][s:e],a['c'][s:e]

def mpos(k,ts):
    a=prep(k)
    if a is None: return -1
    p=a['idx'].searchsorted(ts)
    return int(p) if p<len(a['idx']) else -1

# ── Vectorized simulation ──────────────────────────────────────────────────────
def sim(h,l,c,d,entry,sl,method,val):
    sl_d=abs(entry-sl)
    if sl_d==0 or h is None or len(h)==0: return -1.0
    if method=='tp':
        tp=entry+sl_d*val if d==1 else entry-sl_d*val
        if d==1: sh=l<=sl; th=h>=tp
        else:    sh=h>=sl; th=l<=tp
        si=int(np.argmax(sh)) if sh.any() else len(l)
        ti=int(np.argmax(th)) if th.any() else len(h)
        if ti<si: return val
        if si<len(l): return -1.0
        return ((c[-1]-entry) if d==1 else (entry-c[-1]))/sl_d
    trail=sl_d*val
    if d==1:
        rm=np.maximum.accumulate(h); be=rm>=entry+sl_d
        ts=np.where(be,np.maximum(entry,rm-trail),sl); hit=l<=ts
    else:
        rm=np.minimum.accumulate(l); be=rm<=entry-sl_d
        ts=np.where(be,np.minimum(entry,rm+trail),sl); hit=h>=ts
    if hit.any():
        i=int(np.argmax(hit))
        return (ts[i]-entry)/sl_d if d==1 else (entry-ts[i])/sl_d
    return (ts[-1]-entry)/sl_d if d==1 else (entry-ts[-1])/sl_d

def maemfe(h,l,d,entry,sl):
    sl_d=abs(entry-sl)
    if sl_d==0 or h is None or len(h)==0: return 0.0,0.0
    if d==1: return (entry-l.min())/sl_d,(h.max()-entry)/sl_d
    return (h.max()-entry)/sl_d,(entry-l.min())/sl_d

# ── Stats ──────────────────────────────────────────────────────────────────────
def pf(r):
    r=np.asarray(r,float); w=r[r>0]; l=r[r<=0]
    return float(w.sum()/abs(l.sum())) if len(l) and l.sum()!=0 else float('inf')
def wr(r): r=np.asarray(r,float); return len(r[r>0])/len(r)*100 if len(r) else 0
def aw(r): r=np.asarray(r,float); w=r[r>0]; return float(w.mean()) if len(w) else 0
def al(r): r=np.asarray(r,float); l=r[r<=0]; return float(l.mean()) if len(l) else 0
def sharpe(r):
    r=np.asarray(r,float)
    return float((r.mean()/r.std())*np.sqrt(252)) if len(r)>1 and r.std()>0 else 0.0

# ── ATR ────────────────────────────────────────────────────────────────────────
def atr14(h1):
    hi=h1['high']; lo=h1['low']; pc=h1['close'].shift()
    tr=pd.concat([hi-lo,(hi-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(span=14,adjust=False).mean()

# ── Signal generators ──────────────────────────────────────────────────────────
def sig_orb(key,rh,es,ee,rmin,rmax,skip=frozenset(),trend=False,vol=False,atr_f=False):
    h1=load_h1(key)
    if h1 is None: return []
    cost=COST[key]*1.5
    atr=atr14(h1) if atr_f else None
    ma =h1['close'].rolling(50).mean() if trend else None
    va =h1['tick_volume'].rolling(20).mean() if vol else None
    sigs=[]
    for date in sorted(set(h1.index.normalize().date)):
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip: continue
        rb=h1[h1.index==day+pd.Timedelta(hours=rh)]
        if len(rb)==0: continue
        rhi=rb.iloc[0]['high']; rlo=rb.iloc[0]['low']; rng=rhi-rlo
        if not (rmin<=rng<=rmax): continue
        edf=h1[(h1.index>=day+pd.Timedelta(hours=es))&(h1.index<day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b=edf.iloc[j]; ts=edf.index[j]
            if b['high']>rhi: d,entry,sl=1,rhi,rlo
            elif b['low']<rlo: d,entry,sl=-1,rlo,rhi
            else: continue
            if trend and ma is not None and ts in ma.index:
                mv=float(ma[ts])
                if d==1 and entry<mv: continue
                if d==-1 and entry>mv: continue
            if vol and va is not None and ts in va.index:
                if va[ts]>0 and b['tick_volume']<va[ts]*1.5: continue
            if atr_f and atr is not None and ts in atr.index:
                av=float(atr[ts])
                if av>0 and not (0.5<=rng/av<=3.0): continue
            ep=mpos(key,ts)
            if ep<0: continue
            sigs.append(Sig(key,ep,d,entry,sl,cost,date)); break
    return sigs

def sig_lc(key,min_move):
    h1=load_h1(key)
    if h1 is None: return []
    cost=COST[key]*1.5; sigs=[]
    for date in sorted(set(h1.index.normalize().date)):
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek==4: continue
        ob=h1[h1.index==day+pd.Timedelta(hours=7)]
        cb=h1[h1.index==day+pd.Timedelta(hours=15)]
        if len(ob)==0 or len(cb)==0: continue
        move=cb.iloc[0]['close']-ob.iloc[0]['open']
        if abs(move)<min_move: continue
        sess=h1[(h1.index>=day+pd.Timedelta(hours=7))&(h1.index<=day+pd.Timedelta(hours=16))]
        if len(sess)==0: continue
        dh=sess['high'].max(); dl=sess['low'].min(); buf=(dh-dl)*0.03
        p16=h1[h1.index==day+pd.Timedelta(hours=16)]
        if len(p16)==0: continue
        entry=p16.iloc[0]['open']; d=-1 if move>0 else 1
        sl=(dh+buf) if d==-1 else (dl-buf)
        if d==-1 and sl<=entry: continue
        if d==1 and sl>=entry: continue
        ep=mpos(key,day+pd.Timedelta(hours=16))
        if ep<0: continue
        sigs.append(Sig(key,ep,d,entry,sl,cost,date))
    return sigs

def sig_asian(key,ae=7,es=7,ee=10,mnp=0.0002,mxp=0.004):
    m1=load_m1(key)
    if m1 is None: return []
    cost=COST.get(key,0.08)*1.5; sigs=[]
    for date in sorted(set(m1.index.normalize().date)):
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek==4: continue
        as_=m1[(m1.index>=day)&(m1.index<day+pd.Timedelta(hours=ae))]
        if len(as_)<10: continue
        rhi=as_['high'].max(); rlo=as_['low'].min(); mid=(rhi+rlo)/2
        if mid==0: continue
        rng=(rhi-rlo)/mid
        if not (mnp<=rng<=mxp): continue
        edf=m1[(m1.index>=day+pd.Timedelta(hours=es))&(m1.index<day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b=edf.iloc[j]
            if b['high']>rhi: d,entry,sl=1,rhi,rlo
            elif b['low']<rlo: d,entry,sl=-1,rlo,rhi
            else: continue
            ep=mpos(key,edf.index[j])
            if ep<0: continue
            sigs.append(Sig(key,ep,d,entry,sl,cost,date)); break
    return sigs

def sig_ny(key,rs=13,re=14,ee=16,mnp=0.0001,mxp=0.0025):
    m1=load_m1(key)
    if m1 is None: return []
    cost=COST.get(key,0.07)*1.5; sigs=[]
    for date in sorted(set(m1.index.normalize().date)):
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek==4: continue
        rb=m1[(m1.index>=day+pd.Timedelta(hours=rs))&(m1.index<day+pd.Timedelta(hours=re+0.5))]
        if len(rb)<10: continue
        rhi=rb['high'].max(); rlo=rb['low'].min(); mid=(rhi+rlo)/2
        if mid==0: continue
        rng=(rhi-rlo)/mid
        if not (mnp<=rng<=mxp): continue
        edf=m1[(m1.index>=day+pd.Timedelta(hours=re+0.5))&(m1.index<day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b=edf.iloc[j]
            if b['high']>rhi: d,entry,sl=1,rhi,rlo
            elif b['low']<rlo: d,entry,sl=-1,rlo,rhi
            else: continue
            ep=mpos(key,edf.index[j])
            if ep<0: continue
            sigs.append(Sig(key,ep,d,entry,sl,cost,date)); break
    return sigs

# ── Load everything ────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
for k in FILES: load_h1(k); prep(k)
loaded=[k for k in FILES if _arr.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}\n')

# ── Collect signals ────────────────────────────────────────────────────────────
print('Collecting signals...')
STRATS = {
    # Existing (confirmed positive)
    'DAX_ORB': sig_orb('DAX',  8, 10,12,  20, 200),
    'NAS_ORB': sig_orb('NAS100',14,16,18, 30,1000, frozenset({0,2,4})),
    'SP5_ORB': sig_orb('SP500',14, 16,19,  3, 150,  frozenset({0})),
    'LC_GBP':  sig_lc('GBPUSD', 0.0025),
    'LC_UK':   sig_lc('UK100',  30.0),
    'LC_GOLD': sig_lc('GOLD',   4.0),
    # New strategies
    'ARB_DAX': sig_asian('DAX'),
    'ARB_UK':  sig_asian('UK100'),
    'ARB_EUR': sig_asian('EURUSD'),
    'NY_NAS':  sig_ny('NAS100'),
    'NY_SP5':  sig_ny('SP500'),
    'NY_GBP':  sig_ny('GBPUSD'),
}
for n,s in STRATS.items(): print(f'  {n:12}: {len(s):>5} signals')
total_sigs = sum(len(s) for s in STRATS.values())
print(f'  {"TOTAL":12}: {total_sigs:>5}\n')

# ── Run fast vectorized simulation ────────────────────────────────────────────
print('Simulating (vectorized)...')
EXIT_R   = {lbl:{n:[] for n in STRATS} for lbl,_,_ in EXITS}
META     = {n:[] for n in STRATS}  # (mae, mfe, r_default, weekday, month, year)
DEFAULT  = 'Trail_0.05'

for name,sigs in STRATS.items():
    for s in sigs:
        h,l,c = slc(s.key, s.ep)
        if h is None or len(h)==0: continue
        mae,mfe = maemfe(h,l,s.d,s.entry,s.sl)
        r_def = None
        for lbl,meth,val in EXITS:
            r = sim(h,l,c,s.d,s.entry,s.sl,meth,val) - s.cost
            EXIT_R[lbl][name].append(r)
            if lbl==DEFAULT: r_def=r
        META[name].append((mae,mfe,r_def,s.date.weekday(),s.date.month,s.date.year))
print('Done.\n')

# ── Helper: print section ──────────────────────────────────────────────────────
def div(c='=',n=80): print(c*n)

# ── REPORT 1: PF by exit method ────────────────────────────────────────────────
W=10
hdr=f'{"Strategy":<12}'+''.join(f'{lbl:>{W}}' for lbl,_,_ in EXITS)
div(); print('  PF BY EXIT METHOD'); div()
print(hdr); div('-')
sys_r={lbl:[] for lbl,_,_ in EXITS}
for name in STRATS:
    row=f'{name:<12}'
    for lbl,_,_ in EXITS:
        r=np.array(EXIT_R[lbl][name]); sys_r[lbl].extend(r)
        row+=f'{pf(r):>{W}.2f}' if len(r) else f'{"—":>{W}}'
    print(row)
div('-')
print(f'{"SYSTEM":<12}'+''.join(f'{pf(np.array(sys_r[lbl])):>{W}.2f}' for lbl,_,_ in EXITS))
div()

# ── REPORT 2: Best exit detail ─────────────────────────────────────────────────
best_lbl = max(EXITS, key=lambda x: pf(np.array(sys_r[x[0]])))[0]
print(f'\nBest exit: {best_lbl}\n')
print(f'{"Strategy":<12}{"Trades":>7}{"WR":>7}{"PF":>7}{"AvgW":>8}{"AvgL":>8}{"Sharpe":>8}')
div('-',57)
for name in STRATS:
    r=np.array(EXIT_R[best_lbl][name])
    if not len(r): continue
    mark=' DROP' if pf(r)<1.0 else (' GOOD' if pf(r)>1.5 else '')
    print(f'{name:<12}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}{mark}')
r=np.array(sys_r[best_lbl])
div('-',57)
print(f'{"SYSTEM":<12}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}')
div()

# ── REPORT 3: MAE/MFE ─────────────────────────────────────────────────────────
print(f'\n  MAE/MFE (Trail_0.05)  —  how far trades move before exit\n')
print(f'{"Strategy":<12}{"MAE p50":>9}{"MAE p90":>9}{"MFE p50":>9}{"MFE p90":>9}{"Win MFE50":>10}')
div('-',50)
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    maes=arr[:,0]; mfes=arr[:,1]; rs=arr[:,2]
    win_mfe=mfes[rs>0] if len(rs)==len(mfes) else mfes
    print(f'{name:<12}{np.percentile(maes,50):>8.2f}R{np.percentile(maes,90):>8.2f}R'
          f'{np.percentile(mfes,50):>8.2f}R{np.percentile(mfes,90):>8.2f}R'
          f'{np.percentile(win_mfe,50) if len(win_mfe) else 0:>9.2f}R')
div()

# ── REPORT 4: Day-of-week ─────────────────────────────────────────────────────
DAYS=['Mon','Tue','Wed','Thu','Fri']
print(f'\n  PF BY DAY OF WEEK (Trail_0.05)\n')
print(f'{"Strategy":<12}'+''.join(f'{d:>8}' for d in DAYS))
div('-',52)
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    row=f'{name:<12}'
    for i in range(5):
        r=arr[arr[:,3]==i,2]
        row+=f'{pf(r):>8.2f}' if len(r)>5 else f'{"—":>8}'
    print(row)
div()

# ── REPORT 5: Yearly breakdown ────────────────────────────────────────────────
print(f'\n  PF BY YEAR (Trail_0.05)\n')
years=sorted(set(int(x[5]) for n in STRATS for x in META[n]))
print(f'{"Strategy":<12}'+''.join(f'{y:>8}' for y in years))
div('-',12+8*len(years))
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    row=f'{name:<12}'
    for y in years:
        r=arr[arr[:,5]==y,2]
        row+=f'{pf(r):>8.2f}' if len(r)>5 else f'{"—":>8}'
    print(row)
yr_sys={y:[] for y in years}
for name in STRATS:
    for m in META[name]:
        if m[2] is not None: yr_sys[int(m[5])].append(m[2])
div('-',12+8*len(years))
print(f'{"SYSTEM":<12}'+''.join(f'{pf(np.array(yr_sys[y])):>8.2f}' if yr_sys[y] else f'{"—":>8}' for y in years))
div()

# ── REPORT 6: Filter tests (ORB strategies) ────────────────────────────────────
print(f'\n  ORB FILTER TESTS (Trail_0.05)\n')
print(f'{"Config":<30}{"Sigs":>6}{"WR":>7}{"PF":>7}{"AvgW":>8}{"Sharpe":>8}')
div('-',66)
ORB_KEYS=[('DAX',8,10,12,20,200,frozenset()),
          ('NAS100',14,16,18,30,1000,frozenset({0,2,4})),
          ('SP500',14,16,19,3,150,frozenset({0}))]

for desc,kwargs in [
    ('No filters',            dict(trend=False,vol=False,atr_f=False)),
    ('+ Trend (MA50)',        dict(trend=True, vol=False,atr_f=False)),
    ('+ Volume (1.5x avg)',   dict(trend=False,vol=True, atr_f=False)),
    ('+ ATR regime (0.5-3x)', dict(trend=False,vol=False,atr_f=True)),
    ('+ All filters',         dict(trend=True, vol=True, atr_f=True)),
]:
    all_sigs=[]
    for key,rh,es,ee,rmin,rmax,skip in ORB_KEYS:
        all_sigs+=sig_orb(key,rh,es,ee,rmin,rmax,skip,**kwargs)
    r_all=[]
    for s in all_sigs:
        h,l,c=slc(s.key,s.ep)
        if h is not None and len(h)>0:
            r_all.append(sim(h,l,c,s.d,s.entry,s.sl,'trail',0.05)-s.cost)
    r=np.array(r_all)
    if len(r):
        print(f'{desc:<30}{len(r):>6}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{sharpe(r):>7.2f}')
div()

print('\nAll done.')
