"""
backtest_pdh_pdl.py  -  Previous Day High/Low liquidity sweep reversal
=========================================================================
Highest-conviction of the 4 new strategies. When an M1 bar wicks beyond
yesterday's high or low but CLOSES back inside it, retail stops/breakout
orders resting beyond that level have likely just been run — fade the
sweep back into range.

PDH sweep -> SHORT.  Entry = sweep bar's close.  SL = sweep bar's high + buffer.
PDL sweep -> LONG.   Entry = sweep bar's close.  SL = sweep bar's low  - buffer.
Buffer = 15% of the sweep bar's own range (room past the wick for noise).
First sweep of the day wins (either side) — restricted to main session hours.
Run across all 7 instruments.
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

FILES = {
    'EURUSD':'EURUSD_M1_oanda.csv','GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':'XAUUSD_M1_oanda.csv','DAX':'GER40_M1_oanda.csv',
    'UK100':'UK100_M1_oanda.csv','NAS100':'US100_M1_oanda.csv','SP500':'US500_M1_oanda.csv',
}
COST = {'DAX':0.07,'NAS100':0.06,'SP500':0.06,'EURUSD':0.08,'GBPUSD':0.08,'UK100':0.07,'GOLD':0.08}
EXITS = [('Trail_0.05','trail',0.05),('Trail_5.0','trail',5.0),
         ('TP_1R','tp',1.0),('TP_1.5R','tp',1.5),('TP_2R','tp',2.0),('TP_3R','tp',3.0)]
SESS_START, SESS_END = 7, 20   # UTC
BUF_FRAC = 0.15

# ── Data loading / sim engine (mirrors backtest_master.py) ──────────────────────
_m1,_arr = {},{}
def load_m1(k):
    if k in _m1: return _m1[k]
    fn = FILES.get(k)
    if not fn or not os.path.exists(fn): _m1[k]=None; return None
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
def sig_pdh_pdl(key, sess_start=SESS_START, sess_end=SESS_END, buf_frac=BUF_FRAC):
    m1 = load_m1(key)
    if m1 is None: return []
    daily = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    pdh = daily['high'].shift(1); pdl = daily['low'].shift(1)
    cost = COST[key]*1.5
    idx = daily.index
    sigs=[]
    for i in range(1,len(idx)):
        day = idx[i]
        h_lvl, l_lvl = pdh[day], pdl[day]
        if pd.isna(h_lvl) or pd.isna(l_lvl): continue
        edf = m1[(m1.index>=day+pd.Timedelta(hours=sess_start)) & (m1.index<day+pd.Timedelta(hours=sess_end))]
        for j in range(len(edf)):
            b = edf.iloc[j]
            br = b['high']-b['low']
            if br<=0: continue
            if b['high']>h_lvl and b['close']<h_lvl:
                d,entry,sl = -1, b['close'], b['high']+br*buf_frac
            elif b['low']<l_lvl and b['close']>l_lvl:
                d,entry,sl =  1, b['close'], b['low']-br*buf_frac
            else:
                continue
            ep = mpos(key, edf.index[j])
            if ep<0: continue
            sigs.append((key,ep,d,entry,sl,cost,day.dayofweek,day.year))
            break
    return sigs

# ── Run ──────────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
for k in FILES: load_m1(k); prep(k)
loaded=[k for k in FILES if _arr.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}\n')

print('Collecting PDH/PDL liquidity-sweep signals...')
STRATS = {k: sig_pdh_pdl(k) for k in loaded}
for n,s in STRATS.items(): print(f'  {n:8}: {len(s):>5} signals')
print()

EXIT_R = {lbl:{n:[] for n in STRATS} for lbl,_,_ in EXITS}
META   = {n:[] for n in STRATS}   # (r_default, weekday, year, direction)
DEFAULT = 'Trail_0.05'
for name,sigs in STRATS.items():
    for key,ep,d,entry,sl,cost,wd,yr in sigs:
        h,l,c = slc(key,ep)
        if h is None or len(h)==0: continue
        r_def=None
        for lbl,meth,val in EXITS:
            r = sim(h,l,c,d,entry,sl,meth,val)-cost
            EXIT_R[lbl][name].append(r)
            if lbl==DEFAULT: r_def=r
        META[name].append((r_def,wd,yr,d))

def div(c='=',n=80): print(c*n)

W=10
hdr=f'{"Strategy":<8}'+''.join(f'{lbl:>{W}}' for lbl,_,_ in EXITS)
div(); print('  PDH/PDL SWEEP FADE — PF BY EXIT METHOD'); div()
print(hdr); div('-')
sys_r={lbl:[] for lbl,_,_ in EXITS}
for name in STRATS:
    row=f'{name:<8}'
    for lbl,_,_ in EXITS:
        r=np.array(EXIT_R[lbl][name]); sys_r[lbl].extend(r)
        row+=f'{pf(r):>{W}.2f}' if len(r) else f'{"—":>{W}}'
    print(row)
div('-')
print(f'{"SYSTEM":<8}'+''.join(f'{pf(np.array(sys_r[lbl])):>{W}.2f}' for lbl,_,_ in EXITS))
div()

best_lbl = max(EXITS, key=lambda x: pf(np.array(sys_r[x[0]])))[0]
print(f'\nBest exit: {best_lbl}\n')
print(f'{"Strategy":<8}{"Trades":>7}{"WR":>7}{"PF":>7}{"AvgW":>8}{"AvgL":>8}{"Sharpe":>8}')
div('-',53)
for name in STRATS:
    r=np.array(EXIT_R[best_lbl][name])
    if not len(r): continue
    mark=' DROP' if pf(r)<1.0 else (' GOOD' if pf(r)>1.5 else '')
    print(f'{name:<8}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}{mark}')
r=np.array(sys_r[best_lbl])
div('-',53)
print(f'{"SYSTEM":<8}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}')
div()

print(f'\n  PDH-FADE (short) vs PDL-FADE (long)  ({best_lbl})\n')
print(f'{"Strategy":<8}{"Short Trd":>10}{"Short PF":>10}{"Long Trd":>10}{"Long PF":>10}')
div('-',48)
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    rs=arr[arr[:,3]==-1,0]; rl=arr[arr[:,3]==1,0]
    print(f'{name:<8}{len(rs):>10}{pf(rs):>10.2f}{len(rl):>10}{pf(rl):>10.2f}')
div()

DAYS=['Mon','Tue','Wed','Thu','Fri']
print(f'\n  PF BY DAY OF WEEK ({best_lbl})\n')
print(f'{"Strategy":<8}'+''.join(f'{d:>8}' for d in DAYS))
div('-',48)
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    row=f'{name:<8}'
    for i in range(5):
        r=arr[arr[:,1]==i,0]
        row+=f'{pf(r):>8.2f}' if len(r)>5 else f'{"—":>8}'
    print(row)
div()

print(f'\n  PF BY YEAR ({best_lbl})\n')
years=sorted(set(int(x[2]) for n in STRATS for x in META[n]))
print(f'{"Strategy":<8}'+''.join(f'{y:>7}' for y in years))
div('-',8+7*len(years))
for name in STRATS:
    data=META[name]
    if not data: continue
    arr=np.array(data)
    row=f'{name:<8}'
    for y in years:
        r=arr[arr[:,2]==y,0]
        row+=f'{pf(r):>7.2f}' if len(r)>5 else f'{"—":>7}'
    print(row)
yr_sys={y:[] for y in years}
for name in STRATS:
    for m in META[name]: yr_sys[int(m[2])].append(m[0])
div('-',8+7*len(years))
print(f'{"SYSTEM":<8}'+''.join(f'{pf(np.array(yr_sys[y])):>7.2f}' if yr_sys[y] else f'{"—":>7}' for y in years))
div()
print('\nAll done.')
