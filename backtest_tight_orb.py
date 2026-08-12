"""
backtest_tight_orb.py  -  Tight 30-min ORB with body-confirmation entry
=========================================================================
Hypothesis: the 2hr-window ORB (DAX_ORB/NAS_ORB/SP5_ORB in backtest_master.py,
PF ~1.3-1.55) lets in low-quality late breaks. Tightening the range to 30min
and requiring a CLOSE beyond the range (not just a wick) plus a volume surge
should raise signal quality at the cost of fewer trades.

Range:  DAX 08:00-08:30 UTC | NAS100/SP500 14:30-15:00 UTC
Entry:  first M1 bar whose CLOSE breaks the range AND whose volume is
        >= 1.5x its trailing 100-bar average
Window: DAX 08:30-10:30 UTC | NAS100/SP500 15:00-16:30 UTC
SL:     opposite side of the 30min range
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

FILES = {'DAX':'GER40_M1_oanda.csv','NAS100':'US100_M1_oanda.csv','SP500':'US500_M1_oanda.csv'}
COST  = {'DAX':0.07,'NAS100':0.06,'SP500':0.06}
EXITS = [('Trail_0.05','trail',0.05),('Trail_5.0','trail',5.0),
         ('TP_1R','tp',1.0),('TP_1.5R','tp',1.5),('TP_2R','tp',2.0),('TP_3R','tp',3.0)]

# range_start_h, range_end_h, entry_end_h, rmin, rmax, skip_days
RANGES = {
    'DAX':    (8.0,  8.5, 10.5, 10, 150, frozenset()),
    'NAS100': (14.5, 15.0, 16.5, 15, 700, frozenset({0,2,4})),
    'SP500':  (14.5, 15.0, 16.5,  2, 100, frozenset({0})),
}

# ── Data loading / sim engine (mirrors backtest_master.py) ──────────────────────
_m1,_arr = {},{}
def load_m1(k):
    if k in _m1: return _m1[k]
    fn = FILES.get(k)
    if not fn or not os.path.exists(fn): print(f'MISSING {fn}'); _m1[k]=None; return None
    df = pd.read_csv(fn); df['time']=pd.to_datetime(df['time'],unit='s',utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k]=df.dropna(); return _m1[k]

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

def pf(r):
    r=np.asarray(r,float); w=r[r>0]; l=r[r<=0]
    return float(w.sum()/abs(l.sum())) if len(l) and l.sum()!=0 else float('inf')
def wr(r): r=np.asarray(r,float); return len(r[r>0])/len(r)*100 if len(r) else 0
def aw(r): r=np.asarray(r,float); w=r[r>0]; return float(w.mean()) if len(w) else 0
def al(r): r=np.asarray(r,float); l=r[r<=0]; return float(l.mean()) if len(l) else 0
def sharpe(r):
    r=np.asarray(r,float)
    return float((r.mean()/r.std())*np.sqrt(252)) if len(r)>1 and r.std()>0 else 0.0

# ── Signal generator ─────────────────────────────────────────────────────────
def sig_tight_orb(key, vol_mult=1.5):
    m1 = load_m1(key)
    if m1 is None: return []
    rs,re,ee,rmin,rmax,skip = RANGES[key]
    cost = COST[key]*1.5
    volavg = m1['tick_volume'].rolling(100,min_periods=20).mean()
    sigs=[]
    for date in sorted(set(m1.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip: continue
        rb = m1[(m1.index>=day+pd.Timedelta(hours=rs)) & (m1.index<day+pd.Timedelta(hours=re))]
        if len(rb) < 10: continue
        rhi = rb['high'].max(); rlo = rb['low'].min(); rng = rhi-rlo
        if not (rmin<=rng<=rmax): continue
        edf = m1[(m1.index>=day+pd.Timedelta(hours=re)) & (m1.index<day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            ts = edf.index[j]; b = edf.iloc[j]
            va = volavg.get(ts, np.nan)
            if not (pd.notna(va) and va>0 and b['tick_volume']>=va*vol_mult): continue
            if b['close']>rhi: d,entry,sl = 1,rhi,rlo
            elif b['close']<rlo: d,entry,sl = -1,rlo,rhi
            else: continue
            ep = mpos(key, ts)
            if ep<0: continue
            sigs.append((key,ep,d,entry,sl,cost,date,day.dayofweek,day.year))
            break
    return sigs

# ── Run ──────────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
for k in FILES: load_m1(k); prep(k)
loaded=[k for k in FILES if _arr.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}\n')

print('Collecting tight-ORB signals (30min range, body confirm, 1.5x volume)...')
STRATS = {k: sig_tight_orb(k) for k in loaded}
for n,s in STRATS.items(): print(f'  {n:8}: {len(s):>5} signals')
print()

EXIT_R = {lbl:{n:[] for n in STRATS} for lbl,_,_ in EXITS}
META   = {n:[] for n in STRATS}
DEFAULT = 'Trail_0.05'
for name,sigs in STRATS.items():
    for key,ep,d,entry,sl,cost,date,wd,yr in sigs:
        h,l,c = slc(key,ep)
        if h is None or len(h)==0: continue
        r_def=None
        for lbl,meth,val in EXITS:
            r = sim(h,l,c,d,entry,sl,meth,val)-cost
            EXIT_R[lbl][name].append(r)
            if lbl==DEFAULT: r_def=r
        META[name].append((r_def,wd,yr))

def div(c='=',n=80): print(c*n)

W=10
hdr=f'{"Strategy":<10}'+''.join(f'{lbl:>{W}}' for lbl,_,_ in EXITS)
div(); print('  TIGHT ORB — PF BY EXIT METHOD'); div()
print(hdr); div('-')
sys_r={lbl:[] for lbl,_,_ in EXITS}
for name in STRATS:
    row=f'{name:<10}'
    for lbl,_,_ in EXITS:
        r=np.array(EXIT_R[lbl][name]); sys_r[lbl].extend(r)
        row+=f'{pf(r):>{W}.2f}' if len(r) else f'{"—":>{W}}'
    print(row)
div('-')
print(f'{"SYSTEM":<10}'+''.join(f'{pf(np.array(sys_r[lbl])):>{W}.2f}' for lbl,_,_ in EXITS))
div()

best_lbl = max(EXITS, key=lambda x: pf(np.array(sys_r[x[0]])))[0]
print(f'\nBest exit: {best_lbl}\n')
print(f'{"Strategy":<10}{"Trades":>7}{"WR":>7}{"PF":>7}{"AvgW":>8}{"AvgL":>8}{"Sharpe":>8}')
div('-',55)
for name in STRATS:
    r=np.array(EXIT_R[best_lbl][name])
    if not len(r): continue
    mark=' DROP' if pf(r)<1.0 else (' GOOD' if pf(r)>1.5 else '')
    print(f'{name:<10}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}{mark}')
r=np.array(sys_r[best_lbl])
div('-',55)
print(f'{"SYSTEM":<10}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}')
div()

DAYS=['Mon','Tue','Wed','Thu','Fri']
print(f'\n  PF BY DAY OF WEEK ({best_lbl})\n')
print(f'{"Strategy":<10}'+''.join(f'{d:>8}' for d in DAYS))
div('-',50)
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    row=f'{name:<10}'
    for i in range(5):
        r=arr[arr[:,1]==i,0]
        row+=f'{pf(r):>8.2f}' if len(r)>5 else f'{"—":>8}'
    print(row)
div()

print(f'\n  PF BY YEAR ({best_lbl})\n')
years=sorted(set(int(x[2]) for n in STRATS for x in META[n]))
print(f'{"Strategy":<10}'+''.join(f'{y:>7}' for y in years))
div('-',10+7*len(years))
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    row=f'{name:<10}'
    for y in years:
        r=arr[arr[:,2]==y,0]
        row+=f'{pf(r):>7.2f}' if len(r)>5 else f'{"—":>7}'
    print(row)
yr_sys={y:[] for y in years}
for name in STRATS:
    for m in META[name]: yr_sys[int(m[2])].append(m[0])
div('-',10+7*len(years))
print(f'{"SYSTEM":<10}'+''.join(f'{pf(np.array(yr_sys[y])):>7.2f}' if yr_sys[y] else f'{"—":>7}' for y in years))
div()
print('\nAll done.')
