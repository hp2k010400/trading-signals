"""
backtest_fast.py — 9 strategies, all instruments, vectorized signal collection
Weekly Breakout | LN-NY Overlap | ATR Expansion | NFP Straddle |
NatGas Storage | Oil EIA | Monday Gap | Inside Day+ATR | PDH/PDL+Trend

Run: python backtest_fast.py
"""
import pandas as pd, numpy as np, os, warnings, calendar as cal_mod
warnings.filterwarnings('ignore')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'UK100': 'UK100_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
    'OIL':   'OIL_M1_oanda.csv',
    'SILVER':'XAGUSD_M1_oanda.csv',
    'GBPJPY':'GBPJPY_M1_oanda.csv',
    'EURJPY':'EURJPY_M1_oanda.csv',
    'AUDJPY':'AUDJPY_M1_oanda.csv',
}
COST = {k:0.08 for k in FILES}
COST.update({'DAX':0.07,'UK100':0.07,'NAS100':0.06,'SP500':0.06,'NATGAS':0.12,'SILVER':0.09})

_m1 = {}; _d1 = {}; _wk = {}

# ── LOAD + PRECOMPUTE ─────────────────────────────────────────────────────────
def load(k):
    fn = FILES.get(k,'')
    if not fn or not os.path.exists(fn): _m1[k]=None; return
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'],unit='s',utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c],errors='coerce')
    _m1[k] = df.dropna()
    # Daily features
    d = _m1[k].resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    d = d[d.index.dayofweek < 5]
    hi,lo,cl = d['high'],d['low'],d['close']
    tr = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    d['atr']      = tr.ewm(span=14,adjust=False).mean()
    d['atr_ma']   = d['atr'].rolling(10).mean()
    d['ma50']     = cl.rolling(50).mean()
    d['pdh']      = hi.shift(1)
    d['pdl']      = lo.shift(1)
    d['prev_cls'] = cl.shift(1)
    _d1[k] = d
    # Weekly high/low (previous week via shift)
    wk = _m1[k].resample('W').agg({'high':'max','low':'min'})
    wk['pw_h'] = wk['high'].shift(1)
    wk['pw_l'] = wk['low'].shift(1)
    _wk[k] = wk[['pw_h','pw_l']]
    print(f'  {k}: {len(_m1[k]):,} bars')

# ── SIMULATION ────────────────────────────────────────────────────────────────
def vsim(k, ep, d, entry, sl, tp_r, max_bars=4800):
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
    return ((m1['close'].values[end-1]-entry) if d==1 else (entry-m1['close'].values[end-1]))/sl_d

def vsim_price(k, ep, d, entry, sl, tp_price, max_bars=4800):
    m1=_m1[k]; sl_d=abs(entry-sl)
    if sl_d<=0: return -1.0
    end=min(ep+1+max_bars,len(m1))
    hi=m1['high'].values[ep+1:end]; lo=m1['low'].values[ep+1:end]
    if len(hi)==0: return -1.0
    if d==1:
        sl_i=int(np.argmax(lo<=sl))       if np.any(lo<=sl)       else max_bars
        tp_i=int(np.argmax(hi>=tp_price)) if np.any(hi>=tp_price) else max_bars
    else:
        sl_i=int(np.argmax(hi>=sl))       if np.any(hi>=sl)       else max_bars
        tp_i=int(np.argmax(lo<=tp_price)) if np.any(lo<=tp_price) else max_bars
    if tp_i<=sl_i: return abs(tp_price-entry)/sl_d
    if sl_i<max_bars: return -1.0
    return ((m1['close'].values[end-1]-entry) if d==1 else (entry-m1['close'].values[end-1]))/sl_d

# ── STATS + PRINT ─────────────────────────────────────────────────────────────
def pf(r):
    r=np.asarray(r,float); w=r[r>0]; l=r[r<=0]
    return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
def wr(r):
    r=np.asarray(r,float)
    return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

TPS = [('2R',2.0),('3R',3.0)]

def print_table(title, res_by_inst):
    """res_by_inst = {k: {'2R':[...], '3R':[...]}}"""
    W=10
    print(f'\n{"═"*62}\n  {title}\n{"═"*62}')
    hdr=f'{"Instrument":<12}{"Trades":>8}'+''.join(f'{t:>{W}}' for t,_ in TPS)
    print(hdr); print('─'*len(hdr))
    sys_r={t:[] for t,_ in TPS}
    for k,rd in sorted(res_by_inst.items()):
        if not rd[TPS[0][0]]: continue
        n=len(rd[TPS[0][0]]); row=f'{k:<12}{n:>8}'
        for t,_ in TPS:
            r=np.asarray(rd[t],float); sys_r[t].extend(r); row+=f'{pf(r):>{W}.2f}'
        print(row)
    print('─'*len(hdr))
    sys_row=f'{"SYSTEM":<12}{len(sys_r[TPS[0][0]]):>8}'
    best=0
    for t,_ in TPS:
        r=np.asarray(sys_r[t],float); p=pf(r); best=max(best,p); sys_row+=f'{p:>{W}.2f}'
    print(sys_row)
    flag=' ★★★ TARGET HIT' if best>=2.0 else (' ★★' if best>=1.7 else (' ★' if best>=1.5 else ''))
    print(f'\n  System best PF {best:.2f}{flag}')
    return best

def straddle_table(title, res_by_inst):
    """Same as print_table but labels cols Nat/2R/3R for straddle strategies."""
    return print_table(title, res_by_inst)

# ══════════════════════════════════════════════════════════════════════════════
# 1. WEEKLY RANGE BREAKOUT (vectorized signal collection)
# Break above prev week high or below prev week low, Mon-Wed session
# ══════════════════════════════════════════════════════════════════════════════
def collect_weekly(k):
    m1=_m1[k]; wk=_wk[k]; cost=COST[k]*1.5; mi=m1.index
    ss,se=(8,16) if k not in ['NAS100','SP500'] else (13,18)
    # Merge prev week H/L to every M1 bar
    mg=pd.merge_asof(m1[['high','low']].reset_index(),
                     wk.reset_index().rename(columns={'time':'wk_t'}),
                     left_on='time',right_on='wk_t',direction='backward').set_index('time')
    mg=mg.dropna(subset=['pw_h'])
    h=mg.index.hour; dow=mg.index.dayofweek
    mf=mg[(dow<=2)&(h>=ss)&(h<se)].copy()
    bull=mf[mf['high']>mf['pw_h']].copy()
    bear=mf[mf['low']<mf['pw_l']].copy()
    bull[['d','entry','sl','ts']]=[1,bull['pw_h'],bull['pw_l'],bull.index.to_series()]
    bear[['d','entry','sl','ts']]=[-1,bear['pw_l'],bear['pw_h'],bear.index.to_series()]
    bull['d']=1; bull['entry']=bull['pw_h']; bull['sl']=bull['pw_l']; bull['ts']=bull.index.to_series()
    bear['d']=-1; bear['entry']=bear['pw_l']; bear['sl']=bear['pw_h']; bear['ts']=bear.index.to_series()
    combined=pd.concat([bull[['d','entry','sl','ts']],bear[['d','entry','sl','ts']]]).sort_index()
    if len(combined)==0: return []
    combined['date']=combined.index.date
    first=combined.groupby('date').first()
    sigs=[]
    for _,row in first.iterrows():
        ep=mi.searchsorted(row['ts'])
        if ep>=len(m1): continue
        sld=abs(float(row['entry'])-float(row['sl']))
        if sld<=0: continue
        sigs.append((ep,int(row['d']),float(row['entry']),float(row['sl']),cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 2. LONDON-NY OVERLAP MOMENTUM (vectorized)
# Setup: 13:00-14:00 UTC range. Entry: first break 14:00-17:00.
# ══════════════════════════════════════════════════════════════════════════════
def collect_lnny(k):
    m1=_m1[k]; cost=COST[k]*1.5; mi=m1.index
    setup=m1[(m1.index.hour>=13)&(m1.index.hour<14)]
    if len(setup)==0: return []
    rng=setup.groupby(setup.index.date).agg(sh=('high','max'),sl_=('low','min'))
    em=m1[(m1.index.hour>=14)&(m1.index.hour<17)].copy()
    em['date']=em.index.date
    em=em.merge(rng,left_on='date',right_index=True,how='left').dropna(subset=['sh'])
    em['ts']=em.index
    bull=em[em['high']>em['sh']].copy(); bull['d']=1; bull['entry']=bull['sh']; bull['sl']=bull['sl_']
    bear=em[em['low']<em['sl_']].copy(); bear['d']=-1; bear['entry']=bear['sl_']; bear['sl']=bear['sh']
    combined=pd.concat([bull[['d','entry','sl','ts','date']],
                        bear[['d','entry','sl','ts','date']]]).sort_values('ts')
    if len(combined)==0: return []
    first=combined.groupby('date').first()
    sigs=[]
    for _,row in first.iterrows():
        ep=mi.searchsorted(row['ts'])
        if ep>=len(m1): continue
        sld=abs(float(row['entry'])-float(row['sl']))
        if sld<=0: continue
        sigs.append((ep,int(row['d']),float(row['entry']),float(row['sl']),cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 3. ATR EXPANSION TREND FOLLOW
# When daily ATR > 1.3x its 10-day average: trend day. Enter next day open
# in direction of the expanding day's close vs open.
# ══════════════════════════════════════════════════════════════════════════════
def collect_atr_exp(k):
    m1=_m1[k]; d1=_d1[k]; cost=COST[k]*1.5; mi=m1.index
    qual=d1.dropna(subset=['atr','atr_ma'])
    qual=qual[qual['atr']>qual['atr_ma']*1.3].copy()
    qual['d']=(qual['close']>=qual['open']).astype(int)*2-1
    sigs=[]
    for ts,row in qual.iterrows():
        if ts.dayofweek>=4: continue
        next_day=ts+pd.Timedelta(days=1)
        # Find next trading day open bar
        ob=m1[m1.index>=next_day]
        if len(ob)==0: continue
        entry=float(ob.iloc[0]['open'])
        d=int(row['d']); atr=float(row['atr'])
        if atr<=0: continue
        sl=entry-atr if d==1 else entry+atr
        ep=mi.searchsorted(ob.index[0])
        if ep>=len(m1): continue
        sigs.append((ep,d,entry,sl,cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 4. NFP STRADDLE (first Friday each month, 13:30 UTC)
# Pre-news range 13:00-13:29. Entry on first break after 13:30.
# ══════════════════════════════════════════════════════════════════════════════
def _nfp_dates():
    out=[]
    for y in range(2018,2027):
        for mo in range(1,13):
            c=cal_mod.monthcalendar(y,mo)
            fri=next(w[4] for w in c if w[4]!=0)
            out.append(pd.Timestamp(y,mo,fri,tz='UTC'))
    return out
NFP_DATES=_nfp_dates()
NFP_INSTR=['NAS100','SP500','EURUSD','GBPUSD','GOLD']

def collect_nfp(k):
    if k not in NFP_INSTR: return []
    m1=_m1[k]; cost=COST[k]*1.5; mi=m1.index; sigs=[]
    for day in NFP_DATES:
        pre=m1[(m1.index>=day+pd.Timedelta(hours=13))&(m1.index<day+pd.Timedelta(hours=13,minutes=30))]
        if len(pre)<5: continue
        sh=pre['high'].max(); sl_=pre['low'].min()
        if (sh-sl_)<=0: continue
        post=m1[(m1.index>=day+pd.Timedelta(hours=13,minutes=30))&(m1.index<day+pd.Timedelta(hours=15))]
        if len(post)==0: continue
        d=entry=None
        for j in range(len(post)):
            b=post.iloc[j]
            if b['high']>sh: d=1; entry=sh; sl=sl_; break
            if b['low']<sl_: d=-1; entry=sl_; sl=sh; break
        if d is None: continue
        ep=mi.searchsorted(post.index[j])
        if ep>=len(m1): continue
        sigs.append((ep,d,entry,sl,cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 5. NATGAS WEEKLY STORAGE STRADDLE (every Thursday 14:30 UTC)
# ══════════════════════════════════════════════════════════════════════════════
def collect_natgas(k):
    if k!='NATGAS': return []
    m1=_m1[k]; cost=COST[k]*1.5; mi=m1.index; sigs=[]
    dates=sorted(set(m1.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek!=3: continue
        pre=m1[(m1.index>=day+pd.Timedelta(hours=14))&(m1.index<day+pd.Timedelta(hours=14,minutes=30))]
        if len(pre)<10: continue
        sh=pre['high'].max(); sl_=pre['low'].min()
        if (sh-sl_)<=0: continue
        post=m1[(m1.index>=day+pd.Timedelta(hours=14,minutes=30))&(m1.index<day+pd.Timedelta(hours=18))]
        if len(post)==0: continue
        d=entry=None
        for j in range(len(post)):
            b=post.iloc[j]
            if b['high']>sh: d=1; entry=sh; sl=sl_; break
            if b['low']<sl_: d=-1; entry=sl_; sl=sh; break
        if d is None: continue
        ep=mi.searchsorted(post.index[j])
        if ep>=len(m1): continue
        sigs.append((ep,d,entry,sl,cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 6. OIL EIA STORAGE STRADDLE (every Wednesday 14:30 UTC)
# ══════════════════════════════════════════════════════════════════════════════
def collect_oil(k):
    if k!='OIL': return []
    m1=_m1[k]; cost=COST[k]*1.5; mi=m1.index; sigs=[]
    dates=sorted(set(m1.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek!=2: continue
        pre=m1[(m1.index>=day+pd.Timedelta(hours=14))&(m1.index<day+pd.Timedelta(hours=14,minutes=30))]
        if len(pre)<10: continue
        sh=pre['high'].max(); sl_=pre['low'].min()
        if (sh-sl_)<=0: continue
        post=m1[(m1.index>=day+pd.Timedelta(hours=14,minutes=30))&(m1.index<day+pd.Timedelta(hours=18))]
        if len(post)==0: continue
        d=entry=None
        for j in range(len(post)):
            b=post.iloc[j]
            if b['high']>sh: d=1; entry=sh; sl=sl_; break
            if b['low']<sl_: d=-1; entry=sl_; sl=sh; break
        if d is None: continue
        ep=mi.searchsorted(post.index[j])
        if ep>=len(m1): continue
        sigs.append((ep,d,entry,sl,cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 7. MONDAY GAP FILL (only Monday morning gaps — weekend news = real gap)
# ══════════════════════════════════════════════════════════════════════════════
MON_CFG={'DAX':(8.0,0.0003,0.008),'UK100':(8.0,0.0003,0.008),
         'NAS100':(14.5,0.0002,0.006),'SP500':(14.5,0.0002,0.006)}

def collect_monday_gap(k):
    if k not in MON_CFG: return []
    m1=_m1[k]; d1=_d1[k]; cost=COST[k]*1.5; mi=m1.index
    oh,mn,mx=MON_CFG[k]; sigs=[]
    for ts,row in d1.iterrows():
        if ts.dayofweek!=0: continue
        prev_cls=float(row['prev_cls'])
        if prev_cls<=0 or np.isnan(prev_cls): continue
        day=pd.Timestamp(ts.date(),tz='UTC')
        ob=m1[m1.index>=day+pd.Timedelta(hours=oh)]
        if len(ob)==0: continue
        open_p=float(ob.iloc[0]['open'])
        gap=open_p-prev_cls; gap_pct=abs(gap)/prev_cls
        if gap_pct<mn or gap_pct>mx: continue
        if gap>0: d=-1; sl=open_p+abs(gap)*1.5; tp_price=prev_cls
        else:     d=1;  sl=open_p-abs(gap)*1.5; tp_price=prev_cls
        ep=mi.searchsorted(ob.index[0])
        if ep>=len(m1): continue
        sigs.append((ep,d,open_p,sl,tp_price,cost))
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# 8. INSIDE DAY + ATR CONTRACTION
# Inside day that also shows ATR contracting (genuine compression, not slow day)
# ══════════════════════════════════════════════════════════════════════════════
def collect_inside_atr(k, skip=frozenset({4})):
    m1=_m1[k]; d1=_d1[k]; cost=COST[k]*1.5; mi=m1.index
    dl=list(d1.index); sigs=[]
    for i in range(2,len(dl)):
        ts=dl[i]
        if ts.dayofweek in skip: continue
        row=d1.iloc[i]; prev=d1.iloc[i-1]; prev2=d1.iloc[i-2]
        if not(prev['high']<prev2['high'] and prev['low']>prev2['low']): continue
        atr=row.get('atr',np.nan); atr_ma=row.get('atr_ma',np.nan)
        if not np.isnan(atr) and not np.isnan(atr_ma) and atr_ma>0:
            if atr>atr_ma*0.85: continue  # skip — ATR not genuinely contracted
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

# ══════════════════════════════════════════════════════════════════════════════
# 9. PDH/PDL SWEEP + MA50 TREND FILTER
# Only take bullish sweep if price is above MA50, bearish if below.
# Trades WITH trend, not against it.
# ══════════════════════════════════════════════════════════════════════════════
PDH_CFG={
    'DAX':(8,13,frozenset({0,4})),'UK100':(8,13,frozenset({0,4})),
    'NAS100':(13,18,frozenset({0,4})),'SP500':(13,18,frozenset({0,4})),
    'EURUSD':(7,12,frozenset({4})),'GBPUSD':(7,12,frozenset({4})),
    'GOLD':(8,13,frozenset({4})),'SILVER':(8,13,frozenset({4})),
    'GBPJPY':(7,12,frozenset({4})),'EURJPY':(7,12,frozenset({4})),'AUDJPY':(7,12,frozenset({4})),
}
def collect_pdh_trend(k):
    if k not in PDH_CFG: return []
    m1=_m1[k]; d1=_d1[k]; cost=COST[k]*1.5; mi=m1.index
    lsh,leh,skip=PDH_CFG[k]; sigs=[]
    # Build daily lookup dict for speed
    d1_dict=d1[['pdh','pdl','ma50']].to_dict('index')
    dates=sorted(set(m1.index.normalize().date))
    for date in dates[1:]:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip: continue
        row=d1_dict.get(day)
        if row is None: continue
        pdh=row['pdh']; pdl=row['pdl']; ma50=row['ma50']
        if np.isnan(pdh) or np.isnan(ma50): continue
        pd_rng=pdh-pdl
        if pd_rng<=0: continue
        min_wick=pd_rng*0.001
        window=m1[(m1.index>=day+pd.Timedelta(hours=lsh))&(m1.index<day+pd.Timedelta(hours=leh))]
        if len(window)==0: continue
        for j in range(len(window)):
            b=window.iloc[j]
            body_h=max(b['open'],b['close']); body_l=min(b['open'],b['close'])
            ep=mi.searchsorted(window.index[j])
            if ep>=len(m1): break
            if b['high']>pdh and body_h<pdh and (b['high']-body_h)>=min_wick:
                if body_h>ma50: continue  # above MA50, don't short the sweep
                sigs.append((ep,-1,body_h,b['high']+pd_rng*0.05,cost)); break
            elif b['low']<pdl and body_l>pdl and (body_l-b['low'])>=min_wick:
                if body_l<ma50: continue  # below MA50, don't long the sweep
                sigs.append((ep,1,body_l,b['low']-pd_rng*0.05,cost)); break
    return sigs

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
print('Loading OANDA M1 data...')
for k in FILES: load(k)
loaded=[k for k in FILES if _m1.get(k) is not None]
print(f'Ready: {", ".join(loaded)}\n')

ALL=loaded

def run(title, collect_fn, instruments):
    res={}
    for k in instruments:
        if _m1.get(k) is None: continue
        sigs=collect_fn(k)
        if not sigs: continue
        rd={t:[] for t,_ in TPS}
        for ep,d,entry,sl,cost in sigs:
            for t,tv in TPS:
                rd[t].append(vsim(k,ep,d,entry,sl,tv)-cost)
        res[k]=rd
        print(f'  {k}: {len(sigs)} signals')
    return print_table(title,res)

def run_gap(instruments):
    res={}
    for k in instruments:
        if _m1.get(k) is None or k not in MON_CFG: continue
        sigs=collect_monday_gap(k)
        if not sigs: continue
        rd={t:[] for t,_ in TPS}
        for ep,d,entry,sl,tp_price,cost in sigs:
            rd['2R'].append(vsim_price(k,ep,d,entry,sl,tp_price)-cost)
            rd['3R'].append(vsim(k,ep,d,entry,sl,3.0)-cost)
        res[k]=rd
        print(f'  {k}: {len(sigs)} signals')
    return print_table('MONDAY GAP FILL [2R=fill to prev close, 3R=fixed]',res)

summary={}

print('=== 1. WEEKLY RANGE BREAKOUT ===')
summary['Weekly Breakout']=run('WEEKLY RANGE BREAKOUT — prev week H/L, Mon-Wed',collect_weekly,ALL)

print('\n=== 2. LONDON-NY OVERLAP MOMENTUM ===')
summary['LN-NY Overlap']=run('LONDON-NY OVERLAP MOMENTUM — 13:00 range, 14:00 break',collect_lnny,ALL)

print('\n=== 3. ATR EXPANSION TREND FOLLOW ===')
summary['ATR Expansion']=run('ATR EXPANSION TREND FOLLOW — ATR > 1.3x 10-day avg',collect_atr_exp,ALL)

print('\n=== 4. NFP STRADDLE ===')
summary['NFP Straddle']=run('NFP STRADDLE — first Friday, 13:30 UTC',collect_nfp,NFP_INSTR)

if 'NATGAS' in loaded:
    print('\n=== 5. NATGAS STORAGE (Thursday 14:30) ===')
    sigs=collect_natgas('NATGAS')
    print(f'  NATGAS: {len(sigs)} signals')
    if sigs:
        rd={t:[] for t,_ in TPS}
        for ep,d,entry,sl,cost in sigs:
            for t,tv in TPS: rd[t].append(vsim('NATGAS',ep,d,entry,sl,tv)-cost)
        summary['NatGas Storage']=print_table('NATGAS WEEKLY STORAGE STRADDLE',{'NATGAS':rd})

if 'OIL' in loaded:
    print('\n=== 6. OIL EIA STORAGE (Wednesday 14:30) ===')
    sigs=collect_oil('OIL')
    print(f'  OIL: {len(sigs)} signals')
    if sigs:
        rd={t:[] for t,_ in TPS}
        for ep,d,entry,sl,cost in sigs:
            for t,tv in TPS: rd[t].append(vsim('OIL',ep,d,entry,sl,tv)-cost)
        summary['Oil EIA']=print_table('OIL EIA STORAGE STRADDLE',{'OIL':rd})

print('\n=== 7. MONDAY GAP FILL ===')
summary['Monday Gap']=run_gap(ALL)

print('\n=== 8. INSIDE DAY + ATR CONTRACTION ===')
summary['Inside Day+ATR']=run('INSIDE DAY + ATR CONTRACTION FILTER',collect_inside_atr,ALL)

print('\n=== 9. PDH/PDL + MA50 TREND FILTER ===')
summary['PDH/PDL+Trend']=run('PDH/PDL LIQUIDITY SWEEP + MA50 TREND FILTER',collect_pdh_trend,ALL)

# ── FINAL LEADERBOARD ─────────────────────────────────────────────────────────
print('\n\n'+'═'*62)
print('  LEADERBOARD — best system PF per strategy')
print('═'*62)
for name,best in sorted(summary.items(),key=lambda x:-x[1]):
    flag=' ★★★ TARGET HIT' if best>=2.0 else (' ★★' if best>=1.7 else (' ★' if best>=1.5 else ''))
    print(f'  {name:<22} PF {best:.2f}{flag}')
print('═'*62)
print('\nDone.')
