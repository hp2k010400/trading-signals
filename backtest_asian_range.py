"""
backtest_asian_range.py  -  Asian Range Breakout strategy
=========================================================
Asian session: 00:00-07:00 UTC defines the range
London open:   07:00-10:00 UTC is the entry window (first break of range)
SL: other side of Asian range
Tests all 6 exit methods on M1 data.
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'UK100': 'UK100_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST = {'DAX':0.07,'UK100':0.07,'EURUSD':0.08,'GBPUSD':0.08,'GOLD':0.08}
EXITS = [('Trail_0.05','trail',0.05),('Trail_5.0','trail',5.0),
         ('TP_1R','tp',1.0),('TP_1.5R','tp',1.5),('TP_2R','tp',2.0),('TP_3R','tp',3.0)]

_m1={}
def load_m1(k):
    if k in _m1: return _m1[k]
    fn=FILES[k]
    if not os.path.exists(fn): print(f'MISSING {fn}'); _m1[k]=None; return None
    df=pd.read_csv(fn); df['time']=pd.to_datetime(df['time'],unit='s',utc=True)
    df=df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k]=df.dropna(); return _m1[k]

def sim(m1,ep,d,entry,sl,method,val,max_bars=4800):
    sl_d=abs(entry-sl)
    if sl_d<=0: return -1.0
    rows=m1.iloc[ep+1:ep+1+max_bars]
    if method=='tp':
        tp=entry+sl_d*val if d==1 else entry-sl_d*val
        for _,b in rows.iterrows():
            if d==1:
                if b['low']<=sl: return -1.0
                if b['high']>=tp: return val
            else:
                if b['high']>=sl: return -1.0
                if b['low']<=tp: return val
    else:
        tr=sl_d*val;cs=sl;bst=entry;be=False
        for _,b in rows.iterrows():
            if d==1:
                if b['low']<=cs: return (cs-entry)/sl_d
                bst=max(bst,b['high'])
                if not be and bst>=entry+sl_d: be=True;cs=entry
                if be:
                    ns=bst-tr
                    if ns>cs: cs=ns
            else:
                if b['high']>=cs: return (entry-cs)/sl_d
                bst=min(bst,b['low'])
                if not be and bst<=entry-sl_d: be=True;cs=entry
                if be:
                    ns=bst+tr
                    if ns<cs: cs=ns
    lp=m1.iloc[min(ep+max_bars,len(m1)-1)]['close']
    return ((lp-entry) if d==1 else (entry-lp))/sl_d

def mpos(m1,ts):
    p=m1.index.searchsorted(ts); return int(p) if p<len(m1) else -1

def signals_arb(key, asian_end=7, entry_start=7, entry_end=10, min_range_pct=0.0002):
    m1=load_m1(key)
    if m1 is None: return []
    cost=COST[key]*1.5; sigs=[]
    dates=sorted(set(m1.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek==4: continue  # skip Friday
        # Asian session range
        asian=m1[(m1.index>=day)&(m1.index<day+pd.Timedelta(hours=asian_end))]
        if len(asian)<10: continue
        rhi=asian['high'].max(); rlo=asian['low'].min()
        rng=rhi-rlo
        mid=(rhi+rlo)/2
        if rng/mid < min_range_pct: continue  # range too small
        if rng/mid > min_range_pct*20: continue  # range too large (choppy day)
        # Entry window
        edf=m1[(m1.index>=day+pd.Timedelta(hours=entry_start))&
               (m1.index<day+pd.Timedelta(hours=entry_end))]
        if len(edf)==0: continue
        triggered=False
        for j in range(len(edf)):
            b=edf.iloc[j]
            if b['high']>rhi: d,entry,sl=1,rhi,rlo
            elif b['low']<rlo: d,entry,sl=-1,rlo,rhi
            else: continue
            ep=mpos(m1,edf.index[j])
            if ep<0: continue
            sigs.append((m1,ep,d,entry,sl,cost))
            triggered=True; break
        _ = triggered
    return sigs

def pf(r):
    w=r[r>0];l=r[r<=0]
    return w.sum()/abs(l.sum()) if len(l) and l.sum()!=0 else float('inf')
def wr(r): return len(r[r>0])/len(r)*100 if len(r) else 0
def aw(r): return r[r>0].mean() if len(r[r>0]) else 0
def al(r): return r[r<=0].mean() if len(r[r<=0]) else 0

print('Loading M1 data...')
for k in FILES: load_m1(k)
loaded=[k for k in FILES if _m1.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}\n')

print('Collecting Asian Range Breakout signals...')
STRATS={k: signals_arb(k) for k in loaded}
for k,s in STRATS.items(): print(f'  {k}: {len(s)} signals')

print('\nSimulating...')
res={lbl:{k:[] for k in loaded} for lbl,_,_ in EXITS}
for k,sigs in STRATS.items():
    for m1,ep,d,entry,sl,cost in sigs:
        for lbl,meth,val in EXITS:
            res[lbl][k].append(sim(m1,ep,d,entry,sl,meth,val)-cost)

W=11
hdr=f'{"Instrument":<12}'+''.join(f'{lbl:>{W}}' for lbl,_,_ in EXITS)
print('\n'+'='*len(hdr))
print('  ASIAN RANGE BREAKOUT — PF BY EXIT METHOD')
print('='*len(hdr))
print(hdr); print('-'*len(hdr))
sys_r={lbl:[] for lbl,_,_ in EXITS}
for k in loaded:
    row=f'{k:<12}'
    for lbl,_,_ in EXITS:
        r=np.array(res[lbl][k]); sys_r[lbl].extend(r)
        row+=f'{pf(r):>{W}.2f}' if len(r) else f'{"—":>{W}}'
    print(row)
print('-'*len(hdr))
row=f'{"SYSTEM":<12}'
for lbl,_,_ in EXITS:
    r=np.array(sys_r[lbl]); row+=f'{pf(r):>{W}.2f}'
print(row)
print('='*len(hdr))

best=max(EXITS,key=lambda x:pf(np.array(sys_r[x[0]])))[0]
print(f'\nBest exit: {best}\n')
print(f'{"Instrument":<12}{"Trades":>7}{"WR":>7}{"PF":>7}{"AvgW":>8}{"AvgL":>8}')
print('-'*50)
for k in loaded:
    r=np.array(res[best][k])
    if not len(r): continue
    mark='  DROP' if pf(r)<1.0 else ('  GOOD' if pf(r)>1.5 else '')
    print(f'{k:<12}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{mark}')
print('-'*50)
r=np.array(sys_r[best])
print(f'{"SYSTEM":<12}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R')
print('='*50)
