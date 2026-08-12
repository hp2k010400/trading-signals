"""
backtest_gap_fill.py  -  Fade overnight session gaps
=========================================================================
Hypothesis: index gaps between one session's close and the next session's
open fill back toward the prior close a large % of the time. Fade the gap
direction, target = prior close, tight stop = a fraction of the gap itself.

DAX:    prior close = 16:00 UTC (prev day)  |  open = 08:00 UTC
NAS/SP5: prior close = 20:00 UTC (prev day)  |  open = 14:30 UTC

Direction: gap UP -> SHORT back to prior close. gap DOWN -> LONG back to prior close.
SL:  entry +/- (gap_size * SL_FRAC)   [risk a fraction of the gap to target the full fill]
Bands tested separately since a huge gap and a tiny gap likely behave differently.
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

FILES = {'DAX':'GER40_M1_oanda.csv','NAS100':'US100_M1_oanda.csv','SP500':'US500_M1_oanda.csv'}
COST  = {'DAX':0.07,'NAS100':0.06,'SP500':0.06}
GAP_DEFS = {
    'DAX':    dict(prior_close_h=16.0, open_h=8.0),
    'NAS100': dict(prior_close_h=20.0, open_h=14.5),
    'SP500':  dict(prior_close_h=20.0, open_h=14.5),
}
BANDS = [('Small',0.0005,0.0015), ('Medium',0.0015,0.0035), ('Large',0.0035,0.01)]
SL_FRAC = 0.4
MAX_BARS = 600   # ~10hrs of M1 — rest of the session, don't hold gap fades overnight

# ── Data loading ─────────────────────────────────────────────────────────────
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

def slc(k,ep,mb=MAX_BARS):
    a=prep(k)
    if a is None: return None,None,None
    s=ep+1; e=min(s+mb,len(a['h']))
    return a['h'][s:e],a['l'][s:e],a['c'][s:e]

def mpos(k,ts):
    a=prep(k)
    if a is None: return -1
    p=a['idx'].searchsorted(ts)
    return int(p) if p<len(a['idx']) else -1

def sim_gap(h,l,c,d,entry,sl,tp):
    """Fixed target = prior close (not an R-multiple of SL). Win = distance to tp in R, loss = -1R."""
    sl_d=abs(entry-sl)
    if sl_d==0 or h is None or len(h)==0: return -1.0
    if d==1: sh=l<=sl; th=h>=tp
    else:    sh=h>=sl; th=l<=tp
    si=int(np.argmax(sh)) if sh.any() else len(l)
    ti=int(np.argmax(th)) if th.any() else len(h)
    if ti<si: return abs(tp-entry)/sl_d
    if si<len(l): return -1.0
    return ((c[-1]-entry) if d==1 else (entry-c[-1]))/sl_d

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
def sig_gap_fill(key, band_lo, band_hi, sl_frac=SL_FRAC):
    m1 = load_m1(key)
    if m1 is None: return []
    cfg = GAP_DEFS[key]; cost = COST[key]*1.5
    dates = sorted(set(m1.index.normalize().date))
    sigs=[]
    for i in range(1,len(dates)):
        day = pd.Timestamp(dates[i], tz='UTC'); prev = pd.Timestamp(dates[i-1], tz='UTC')
        pc_bar = m1[m1.index==prev+pd.Timedelta(hours=cfg['prior_close_h'])]
        op_bar = m1[m1.index==day +pd.Timedelta(hours=cfg['open_h'])]
        if len(pc_bar)==0 or len(op_bar)==0: continue
        prior_close = pc_bar.iloc[0]['close']; today_open = op_bar.iloc[0]['open']
        if prior_close==0: continue
        gap = today_open - prior_close
        gap_pct = abs(gap)/prior_close
        if not (band_lo<=gap_pct<band_hi): continue
        entry, tp = today_open, prior_close
        buf = abs(gap)*sl_frac
        if buf<=0: continue
        if gap>0: d,sl = -1, entry+buf
        else:      d,sl =  1, entry-buf
        ep = mpos(key, day+pd.Timedelta(hours=cfg['open_h']))
        if ep<0: continue
        sigs.append((key,ep,d,entry,sl,tp,cost,day.dayofweek,day.year))
    return sigs

# ── Run ──────────────────────────────────────────────────────────────────────
print('Loading OANDA M1 data...')
for k in FILES: load_m1(k); prep(k)
loaded=[k for k in FILES if _arr.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}\n')

print('Collecting gap-fill signals by band...')
SIGS = {}   # (key,band_name) -> sigs
for k in loaded:
    for bname,blo,bhi in BANDS:
        SIGS[(k,bname)] = sig_gap_fill(k,blo,bhi)
        print(f'  {k:8} {bname:8}: {len(SIGS[(k,bname)]):>5} signals')
print()

RES  = {(k,b):[] for k in loaded for b,_,_ in BANDS}
META = {(k,b):[] for k in loaded for b,_,_ in BANDS}
for (k,bname),sigs in SIGS.items():
    for key,ep,d,entry,sl,tp,cost,wd,yr in sigs:
        h,l,c = slc(key,ep)
        if h is None or len(h)==0: continue
        r = sim_gap(h,l,c,d,entry,sl,tp)-cost
        RES[(k,bname)].append(r)
        META[(k,bname)].append((r,wd,yr))

def div(c='=',n=80): print(c*n)

div(); print('  GAP FILL — PF BY INSTRUMENT x GAP SIZE BAND'); div()
print(f'{"Instrument":<10}'+''.join(f'{b:>22}' for b,_,_ in BANDS))
sub=''.join(f'{"Trd":>6}{"WR":>7}{"PF":>9}' for _ in BANDS)
print(f'{"":<10}{sub}')
div('-')
sys_r={b:[] for b,_,_ in BANDS}
for k in loaded:
    row=f'{k:<10}'
    for bname,_,_ in BANDS:
        r=np.array(RES[(k,bname)]); sys_r[bname].extend(r)
        row+= f'{len(r):>6}{wr(r):>6.1f}%{pf(r):>9.2f}' if len(r) else f'{"—":>6}{"—":>7}{"—":>9}'
    print(row)
div('-')
row=f'{"SYSTEM":<10}'
for bname,_,_ in BANDS:
    r=np.array(sys_r[bname])
    row+= f'{len(r):>6}{wr(r):>6.1f}%{pf(r):>9.2f}' if len(r) else f'{"—":>6}{"—":>7}{"—":>9}'
print(row)
div()

best_band = max(BANDS, key=lambda b: pf(np.array(sys_r[b[0]])))[0]
print(f'\nBest band: {best_band}\n')
print(f'{"Instrument":<10}{"Trades":>7}{"WR":>7}{"PF":>7}{"AvgW":>8}{"AvgL":>8}{"Sharpe":>8}')
div('-',55)
for k in loaded:
    r=np.array(RES[(k,best_band)])
    if not len(r): continue
    mark=' DROP' if pf(r)<1.0 else (' GOOD' if pf(r)>1.5 else '')
    print(f'{k:<10}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}{mark}')
r=np.array(sys_r[best_band])
div('-',55)
print(f'{"SYSTEM":<10}{len(r):>7}{wr(r):>6.1f}%{pf(r):>7.2f}{aw(r):>7.2f}R{al(r):>7.2f}R{sharpe(r):>7.2f}')
div()

DAYS=['Mon','Tue','Wed','Thu','Fri']
print(f'\n  PF BY DAY OF WEEK ({best_band} band, all instruments)\n')
all_meta = [m for k in loaded for m in META[(k,best_band)]]
if all_meta:
    arr=np.array(all_meta)
    row=''
    for i in range(5):
        r=arr[arr[:,1]==i,0]
        row+=f'{DAYS[i]}:{pf(r):>6.2f} ({len(r)}t)   ' if len(r)>3 else f'{DAYS[i]}: —   '
    print(row)
div()

print(f'\n  PF BY YEAR ({best_band} band, all instruments)\n')
years=sorted(set(int(m[2]) for m in all_meta)) if all_meta else []
for y in years:
    r=arr[arr[:,2]==y,0] if all_meta else np.array([])
    if len(r)>3: print(f'  {y}: PF {pf(r):.2f}  ({len(r)} trades)')
div()
print('\nAll done.')
