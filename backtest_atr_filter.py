"""
backtest_atr_filter.py
H1 Inside Bar + ATR Regime Filter
Does filtering for expansion days improve PF without killing frequency?

Tests ATR thresholds: 1.0 (no filter), 1.1, 1.2, 1.3, 1.5x 10-day avg
OOS 2022-2026 only.

Run: python backtest_atr_filter.py
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

OOS_START = pd.Timestamp(2022, 1, 1, tz='UTC')
OOS_END   = pd.Timestamp(2026, 1, 1, tz='UTC')
TP_R      = 3.0
ACCOUNT   = 70_000
RISK_FRAC = 0.005
SLIPPAGE  = 0.10
ATR_PERIOD = 10  # days

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
}
COST = {'DAX':0.07,'NAS100':0.06,'SP500':0.06,
        'EURUSD':0.08,'GBPUSD':0.08,'GOLD':0.08,'NATGAS':0.15}
H1_HOURS = {
    'DAX':    {8,9,10,13,14}, 'NAS100': {13,14,15,16},
    'SP500':  {13,14,15,16},  'EURUSD': {8,9,13,14,15},
    'GBPUSD': {8,9,13,14,15}, 'GOLD':   {8,9,13,14,15},
    'NATGAS': {13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset({4}),'EURUSD':frozenset({4}),'GBPUSD':frozenset({4}),
    'GOLD':frozenset({4}),'NATGAS':frozenset({4}),
    'NAS100':frozenset({0,4}),'SP500':frozenset({0,4}),
}
_m1 = {}
_atr = {}  # pre-computed daily ATR series per instrument

def load(k):
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True

def build_atr(k):
    m1 = _m1[k]
    d1 = m1.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    d1 = d1[d1['open'] > 0]
    # True range: max of (H-L, |H-prev_C|, |L-prev_C|)
    d1['prev_close'] = d1['close'].shift(1)
    d1['tr'] = np.maximum(
        d1['high'] - d1['low'],
        np.maximum(
            abs(d1['high'] - d1['prev_close']),
            abs(d1['low']  - d1['prev_close'])
        )
    )
    d1['atr']     = d1['tr'].rolling(ATR_PERIOD).mean()
    d1['atr_avg'] = d1['atr'].shift(1)  # use previous day's ATR vs its own 10-day avg
    _atr[k] = d1[['atr','atr_avg']].dropna()

def get_atr_ratio(k, date):
    """Return ratio of yesterday's ATR to its 10-day average. 1.0 = no filter."""
    atr_df = _atr[k]
    # Find the row for the day before the signal date
    prev_day = pd.Timestamp(date, tz='UTC') - pd.Timedelta(days=1)
    # Get closest prior ATR reading
    idx = atr_df.index.searchsorted(prev_day, side='right') - 1
    if idx < 0: return 0.0
    row = atr_df.iloc[idx]
    if row['atr_avg'] <= 0: return 0.0
    return row['atr'] / row['atr_avg']

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

def collect_oos_with_atr(key):
    """Returns list of dicts: {date, r_gross, spread, atr_ratio}"""
    m1=_m1[key]; cost=COST[key]*1.5; mi=m1.index
    skip=H1_SKIP.get(key,frozenset({4}))
    p_hours=H1_HOURS.get(key,{8,9,13,14})
    m1w=m1[(m1.index>=OOS_START)&(m1.index<OOS_END)]
    if len(m1w)<100: return []
    h1=m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1=h1[h1['open']>0]
    hl=list(h1.index); out=[]; day_count={}
    for i in range(1,len(hl)):
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
            r_gross=vsim(key,ep,d,entry,sl,TP_R)
            atr_ratio=get_atr_ratio(key,date_k)
            out.append({'date':date_k,'r_gross':r_gross,'spread':cost,'atr_ratio':atr_ratio})
            break
    return out

def pf(r): r=np.asarray(r,float); w=r[r>0]; l=r[r<=0]; return round(w.sum()/abs(l.sum()),2) if len(l) and l.sum()!=0 else 0.0
def wr(r): r=np.asarray(r,float); return round(len(r[r>0])/len(r)*100,1) if len(r) else 0.0

# ── Load ──────────────────────────────────────────────────────────────────────
print('Loading...')
loaded=[]
for k in FILES:
    if load(k):
        build_atr(k)
        loaded.append(k)
        print(f'  {k}: {len(_m1[k]):,} bars')
    else:
        print(f'  {k}: not found')

print('\nCollecting OOS signals with ATR ratios...')
all_trades=[]
for k in loaded:
    t=collect_oos_with_atr(k)
    all_trades.extend(t)
    print(f'  {k}: {len(t)} signals')

OOS_DAYS=(OOS_END-OOS_START).days/7*5
print(f'\nTotal signals: {len(all_trades)} over ~{OOS_DAYS:.0f} trading days')

# ATR ratio distribution
ratios=np.asarray([t['atr_ratio'] for t in all_trades])
print(f'\nATR ratio distribution:')
for pct in [10,25,50,75,90]:
    print(f'  p{pct}: {np.percentile(ratios,pct):.2f}x')

# ── THRESHOLD SWEEP ───────────────────────────────────────────────────────────
THRESHOLDS = [1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5]

print(f'\n{"═"*78}')
print(f'  ATR FILTER SWEEP — H1 Inside Bar OOS 2022-2026 (0.10R slippage)')
print(f'{"═"*78}')
print(f'\n  {"Threshold":>12}  {"Trades":>7}  {"Per Day":>8}  {"WR":>7}  '
      f'{"PF":>7}  {"Daily P&L":>10}  {"Monthly":>10}  {"Filtered%":>10}')
print('  '+'─'*82)

base_n = len(all_trades)
for thresh in THRESHOLDS:
    filtered=[t for t in all_trades if t['atr_ratio']>=thresh]
    if not filtered: continue
    r=np.asarray([t['r_gross']-t['spread']-SLIPPAGE for t in filtered],float)
    n=len(r); ppd=n/OOS_DAYS
    exp=r.mean(); daily=ppd*exp*ACCOUNT*RISK_FRAC; monthly=daily*22
    pct_kept=n/base_n*100; pct_filtered=100-pct_kept
    flag=' ◄ no filter' if thresh==1.0 else (' ★★' if pf(r)>=2.5 else (' ★' if pf(r)>=2.3 else ''))
    print(f'  {thresh:>10.2f}x  {n:>7,}  {ppd:>8.2f}  {wr(r):>6.1f}%  '
          f'{pf(r):>7.2f}  £{daily:>8,.0f}  £{monthly:>8,.0f}  '
          f'{pct_filtered:>8.1f}%{flag}')

# ── PER-INSTRUMENT at best threshold ─────────────────────────────────────────
# Find best threshold (highest PF with >2.0 trades/day)
best_thresh=1.0; best_score=0
for thresh in THRESHOLDS:
    filtered=[t for t in all_trades if t['atr_ratio']>=thresh]
    if not filtered: continue
    r=np.asarray([t['r_gross']-t['spread']-SLIPPAGE for t in filtered],float)
    ppd=len(r)/OOS_DAYS
    if ppd>=2.0:
        score=pf(r)*ppd  # balance PF and frequency
        if score>best_score: best_score=score; best_thresh=thresh

print(f'\n\n{"═"*78}')
print(f'  PER INSTRUMENT — ATR filter at {best_thresh:.2f}x (best PF × frequency)')
print(f'{"═"*78}')
print(f'\n  {"Instr":<8}  {"No filter":>12}  {"With filter":>13}  '
      f'{"PF gain":>9}  {"Trades kept":>12}')
print('  '+'─'*62)

# Re-collect per instrument
inst_trades={k:[] for k in loaded}
for k in loaded:
    inst_trades[k]=collect_oos_with_atr(k)

for k in loaded:
    tl=inst_trades[k]
    if not tl: continue
    r_base=np.asarray([t['r_gross']-t['spread']-SLIPPAGE for t in tl],float)
    r_filt=np.asarray([t['r_gross']-t['spread']-SLIPPAGE for t in tl if t['atr_ratio']>=best_thresh],float)
    pf_base=pf(r_base); pf_filt=pf(r_filt) if len(r_filt) else 0
    kept_pct=len(r_filt)/len(r_base)*100 if len(r_base) else 0
    gain=pf_filt-pf_base
    flag=' ★' if pf_filt>=2.5 else ''
    print(f'  {k:<8}  {pf_base:>10.2f}    {pf_filt:>11.2f}  {gain:>+8.2f}  '
          f'{kept_pct:>10.1f}%{flag}')

# ── VERDICT ───────────────────────────────────────────────────────────────────
filtered_best=[t for t in all_trades if t['atr_ratio']>=best_thresh]
r_best=np.asarray([t['r_gross']-t['spread']-SLIPPAGE for t in filtered_best],float)
ppd_best=len(r_best)/OOS_DAYS

print(f'\n\n{"═"*78}')
print(f'  VERDICT')
print(f'{"═"*78}')
pf_no=pf(np.asarray([t['r_gross']-t['spread']-SLIPPAGE for t in all_trades],float))
pf_yes=pf(r_best)
print(f'  Without ATR filter:  PF {pf_no:.2f}  |  {len(all_trades)/OOS_DAYS:.2f} trades/day')
print(f'  With ATR {best_thresh:.2f}x filter: PF {pf_yes:.2f}  |  {ppd_best:.2f} trades/day')
print(f'  PF improvement: {pf_yes-pf_no:+.2f}')
if pf_yes > pf_no + 0.1 and ppd_best >= 2.0:
    print(f'  ✓ ATR filter IMPROVES the system — add it to EA')
elif pf_yes > pf_no + 0.05:
    print(f'  ~ Marginal improvement — up to you')
else:
    print(f'  ✗ ATR filter does not meaningfully help — keep system as is')
print(f'{"═"*78}\nDone.')
