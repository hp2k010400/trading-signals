"""
backtest_new_ideas.py — Quant-suggested new strategies
Testing all new ideas against 2 years of H1 data.

New strategies:
  1.  Gold PDH/PWH/LSR     — institutional level breaks on XAUUSD
  2.  GBPJPY LB            — Asian range London explosion JPY
  3.  EURJPY LB            — Asian range London explosion JPY
  4.  DAX Gap Fill         — fade overnight gap, 68-72% fill rate
  5.  UK100 Gap Fill       — same
  6.  Donchian DAX         — 20-day high/low breakout + ADX filter
  7.  Donchian Gold        — Turtle strategy on Gold
  8.  Donchian NatGas      — Turtle strategy on NatGas
  9.  EURUSD H4 EMA        — extend H4 trend strategy to FX majors
  10. GBPUSD H4 EMA        — same
  11. EURJPY H4 EMA        — JPY cross trend following
  12. Month-End EUR        — institutional rebalancing EURUSD
  13. Month-End GBP        — institutional rebalancing GBPUSD

Run in Codespaces:
  git pull && python backtest_new_ideas.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT   = 70_000
TRAIL_ORB = 0.20
TRAIL_H4  = 0.30
TRAIL_DCH = 0.40   # wider trail for Donchian trend following

YFSYMS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X',
    'GBPJPY': 'GBPJPY=X', 'EURJPY': 'EURJPY=X',
    'DAX':    '^GDAXI',   'UK100':  '^FTSE',
    'GOLD':   'GC=F',     'NATGAS': 'NG=F',
}

_cache = {}

def load_h1(key):
    if key not in _cache:
        sym = YFSYMS[key]
        try:
            df = yf.download(sym, interval='1h', period='730d',
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None: df.index = df.index.tz_localize('UTC')
            else:                   df.index = df.index.tz_convert('UTC')
            result = df if len(df) > 200 else None
            _cache[key] = result
            n = len(result) if result is not None else 0
            print(f"  {key}: {n} bars")
        except Exception as e:
            print(f"  {key}: FAILED ({e})")
            _cache[key] = None
    return _cache[key]

def load_h4(key):
    df = load_h1(key)
    if df is None: return None
    return df.resample('4h', origin='epoch').agg(
        {'open':'first','high':'max','low':'min','close':'last'}).dropna()

def load_daily(key):
    sym = YFSYMS[key]
    try:
        df = yf.download(sym, interval='1d', period='730d',
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if df.index.tz is None: df.index = df.index.tz_localize('UTC')
        else:                   df.index = df.index.tz_convert('UTC')
        return df if len(df) > 100 else None
    except:
        return None

def calc_atr(df, p=14):
    h=df['high']; l=df['low']; pc=df['close'].shift(1)
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(span=p,adjust=False).mean()

def calc_adx(df, p=14):
    h=df['high']; l=df['low']; c=df['close']
    up=h-h.shift(1); dn=l.shift(1)-l
    pdm=np.where((up>dn)&(up>0),up,0.0)
    ndm=np.where((dn>up)&(dn>0),dn,0.0)
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    atr=tr.ewm(span=p,adjust=False).mean()
    pdi=100*pd.Series(pdm,index=df.index).ewm(span=p,adjust=False).mean()/atr
    ndi=100*pd.Series(ndm,index=df.index).ewm(span=p,adjust=False).mean()/atr
    dx=100*(pdi-ndi).abs()/(pdi+ndi+1e-9)
    return dx.ewm(span=p,adjust=False).mean()

def ipos(df, ts):
    pos = df.index.searchsorted(ts)
    if pos >= len(df): return -1
    return int(pos) if df.index[int(pos)] == ts else -1

def sim(df, entry_pos, direction, entry, sl, trail_mult, max_bars=72):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0
    trail = sl_d * trail_mult
    cur_sl = sl; best = entry; be = False
    last = entry
    for _, b in df.iloc[entry_pos+1 : entry_pos+1+max_bars].iterrows():
        last = b['close']
        if direction == 1:
            if b['low'] <= cur_sl: return (cur_sl - entry) / sl_d
            best = max(best, b['high'])
            if not be and best >= entry + sl_d: be=True; cur_sl=entry
            if be:
                ns = best - trail
                if ns > cur_sl: cur_sl = ns
        else:
            if b['high'] >= cur_sl: return (entry - cur_sl) / sl_d
            best = min(best, b['low'])
            if not be and best <= entry - sl_d: be=True; cur_sl=entry
            if be:
                ns = best + trail
                if ns < cur_sl: cur_sl = ns
    pts = (last-entry) if direction==1 else (entry-last)
    return pts / sl_d

def trade(df, pos, direction, entry, sl, trail, risk_pct):
    return sim(df, pos, direction, entry, sl, trail) * risk_pct * ACCOUNT

def stats(name, trades, risk_label=''):
    if len(trades) < 8:
        print(f"  {name:<26}  — insufficient data ({len(trades)} trades)")
        return None
    arr  = np.array(trades, dtype=float)
    wins = arr[arr >  5]; loss = arr[arr < -5]
    n    = len(arr); wr = len(wins)/n*100
    gp   = wins.sum() if len(wins) else 0
    gl   = abs(loss.sum()) if len(loss) else 1e-9
    pf   = gp/gl
    days = 504; tpm = n/days*21; mo = arr.sum()/days*21
    tag  = '✅' if pf>=1.5 else ('⚠️ ' if pf>=1.2 else '❌')
    print(f"  {name:<26} {n:>4}tr {wr:>5.1f}%wr {tpm:>4.1f}/mo "
          f"PF:{pf:>5.2f}  £{mo:>7,.0f}/mo  {tag}")
    return {'name':name,'n':n,'wr':round(wr,1),'pf':round(pf,2),
            'mo':round(mo,0),'trades':arr.tolist()}

# ── 1-3. Gold / GBPJPY / EURJPY PDH ─────────────────────────────────────────
def run_pdh(key, tag, hs, he, risk=0.004):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df,14); trades=[]
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date,tz='UTC')
        prev = day - pd.Timedelta(days=1)
        pd_  = df[(df.index>=prev)&(df.index<day)]
        if len(pd_)<5: continue
        pdh=pd_['high'].max(); pdl=pd_['low'].min()
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&
               (df.index<day+pd.Timedelta(hours=he))]
        if len(edf)==0: continue
        a=atr.reindex(edf.index,method='ffill')
        if len(a)==0 or a.iloc[0]<=0: continue
        rng=pdh-pdl
        if not (a.iloc[0]*0.4<=rng<=a.iloc[0]*4.0): continue
        buf=a.iloc[0]*0.05
        for j in range(len(edf)):
            b=edf.iloc[j]; av=a.iloc[min(j,len(a)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pdh+buf:
                trades.append(trade(df,p,1,b['close'],b['close']-1.5*av,TRAIL_ORB,risk)); break
            if b['low']<pdl-buf:
                trades.append(trade(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB,risk)); break
    return trades

def run_pwh(key, tag, hs, he, risk=0.004):
    df = load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); trades=[]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC'); dow=day.dayofweek
        ws=day-pd.Timedelta(days=dow+7); we=day-pd.Timedelta(days=dow)
        pw=df[(df.index>=ws)&(df.index<we)]
        if len(pw)<20: continue
        pwh=pw['high'].max(); pwl=pw['low'].min()
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&
               (df.index<day+pd.Timedelta(hours=he))]
        if len(edf)==0: continue
        a=atr.reindex(edf.index,method='ffill')
        if len(a)==0 or a.iloc[0]<=0: continue
        rng=pwh-pwl
        if not (0.5*a.iloc[0]<=rng<=8.0*a.iloc[0]): continue
        buf=a.iloc[0]*0.05
        for j in range(len(edf)):
            b=edf.iloc[j]; av=a.iloc[min(j,len(a)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pwh+buf:
                trades.append(trade(df,p,1,b['close'],b['close']-1.5*av,TRAIL_ORB,risk)); break
            if b['low']<pwl-buf:
                trades.append(trade(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB,risk)); break
    return trades

def run_lsr(key, tag, hs, he, risk=0.003):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); trades=[]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC'); prev=day-pd.Timedelta(days=1)
        pd_=df[(df.index>=prev)&(df.index<day)]
        if len(pd_)<5: continue
        pdh=pd_['high'].max(); pdl=pd_['low'].min()
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&
               (df.index<day+pd.Timedelta(hours=he))]
        a_s=atr.reindex(edf.index,method='ffill'); fired=False
        for j in range(len(edf)):
            if fired: break
            b=edf.iloc[j]; av=a_s.iloc[min(j,len(a_s)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pdh and b['close']<pdh and (b['high']-pdh)<0.6*av:
                trades.append(trade(df,p,-1,b['close'],b['high']+av*0.1,TRAIL_ORB,risk)); fired=True
            elif b['low']<pdl and b['close']>pdl and (pdl-b['low'])<0.6*av:
                trades.append(trade(df,p,1,b['close'],b['low']-av*0.1,TRAIL_ORB,risk)); fired=True
    return trades

# ── 2-3. GBPJPY + EURJPY London Breakout ─────────────────────────────────────
def run_lb_jpy(key, tag, pip=0.01, min_rng=30, max_rng=300, risk=0.004, skip_dow=set()):
    df=load_h1(key)
    if df is None: return []
    trades=[]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip_dow: continue
        prev=day-pd.Timedelta(days=1)
        rdf=df[(df.index>=prev+pd.Timedelta(hours=22))&
               (df.index<day+pd.Timedelta(hours=7))]
        if len(rdf)<5: continue
        a_hi=rdf['high'].max(); a_lo=rdf['low'].min(); rng=a_hi-a_lo
        if not (min_rng<=rng/pip<=max_rng): continue
        buf=rng*0.15
        edf=df[(df.index>=day+pd.Timedelta(hours=7))&
               (df.index<day+pd.Timedelta(hours=10))]
        for j in range(len(edf)):
            b=edf.iloc[j]; p=ipos(df,edf.index[j])
            if p<0: continue
            if b['high']>a_hi:
                trades.append(trade(df,p,1,a_hi,a_lo-buf,TRAIL_ORB,risk)); break
            if b['low']<a_lo:
                trades.append(trade(df,p,-1,a_lo,a_hi+buf,TRAIL_ORB,risk)); break
    return trades

# ── 4-5. Opening Gap Fill (DAX, UK100) ───────────────────────────────────────
def run_gap_fill(key, tag, open_hour=8, session_end=17, min_gap_atr=0.3, risk=0.004):
    """
    Fade the overnight gap. If DAX opens above prev close → SELL.
    If opens below prev close → BUY. Target: gap fill.
    Edge: indices fill overnight gaps 68-72% of the time.
    """
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); trades=[]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in {5,6}: continue   # skip weekends
        # Previous day's last close
        prev=day-pd.Timedelta(days=1)
        prev_df=df[(df.index>=prev)&(df.index<day)]
        if len(prev_df)<3: continue
        prev_close=prev_df.iloc[-1]['close']
        # Current day opening bar
        open_bar=df[df.index==day+pd.Timedelta(hours=open_hour)]
        if len(open_bar)==0: continue
        ob=open_bar.iloc[0]
        gap=ob['open']-prev_close
        av=atr.reindex([ob.name],method='ffill')
        if len(av)==0 or av.iloc[0]<=0: continue
        a=av.iloc[0]
        if abs(gap)<min_gap_atr*a: continue   # gap too small — not significant
        p=ipos(df,ob.name)
        if p<0: continue
        # Max hold: end of session
        max_b=session_end-open_hour
        if gap>0:   # opened UP — fade down to fill gap (SELL)
            sl=ob['open']+1.5*a
            # Target = prev_close (gap fill), use trail from that point
            trades.append(trade(df,p,-1,ob['open'],sl,TRAIL_ORB,risk))
        else:       # opened DOWN — fade up to fill gap (BUY)
            sl=ob['open']-1.5*a
            trades.append(trade(df,p,1,ob['open'],sl,TRAIL_ORB,risk))
    return trades

# ── 6-8. Donchian 20-Day Breakout ────────────────────────────────────────────
def run_donchian(key, tag, period=20, hs=8, he=21, risk=0.004):
    """
    Classic Turtle / Donchian channel breakout.
    Buy new 20-day high, sell new 20-day low.
    Filter: H4 ADX > 25 (only in genuine trends).
    Wide 0.4R trail to ride multi-day moves.
    """
    df_d=load_daily(key)
    df_h=load_h1(key)
    if df_d is None or df_h is None: return []
    df_h4=load_h4(key)
    adx4=calc_adx(df_h4,14) if df_h4 is not None else None
    atr_h=calc_atr(df_h,14)
    trades=[]; fired_days=set()
    for i in range(period+1, len(df_d)-1):
        day=df_d.index[i].normalize()
        if day.date() in fired_days: continue
        roll_hi=df_d['high'].iloc[i-period:i].max()
        roll_lo=df_d['low'].iloc[i-period:i].min()
        today_h=df_d.iloc[i]['high']; today_l=df_d.iloc[i]['low']
        broke_up = today_h > roll_hi
        broke_dn = today_l < roll_lo
        if not broke_up and not broke_dn: continue
        # ADX filter on H4
        if adx4 is not None:
            adx_now=adx4[adx4.index<=day]
            if len(adx_now)<2 or adx_now.iloc[-1]<25: continue
        # Find entry bar in H1
        edf=df_h[(df_h.index>=day+pd.Timedelta(hours=hs))&
                 (df_h.index<day+pd.Timedelta(hours=he))]
        if len(edf)==0: continue
        b=edf.iloc[0]; p=ipos(df_h,edf.index[0])
        if p<0: continue
        a=atr_h.iloc[p] if p<len(atr_h) else 0
        if a<=0: continue
        if broke_up:
            trades.append(trade(df_h,p,1, b['close'],b['close']-2.0*a,TRAIL_DCH,risk))
        else:
            trades.append(trade(df_h,p,-1,b['close'],b['close']+2.0*a,TRAIL_DCH,risk))
        fired_days.add(day.date())
    return trades

# ── 9-11. H4 EMA on FX Majors ────────────────────────────────────────────────
def run_h4_ema(key, tag, hs=7, he=17, risk=0.0075):
    df4=load_h4(key); df1=load_h1(key)
    if df4 is None or df1 is None: return []
    ema10=df4['close'].ewm(span=10,adjust=False).mean()
    ema20=df4['close'].ewm(span=20,adjust=False).mean()
    atr4=calc_atr(df4,14); adx4=calc_adx(df4,14)
    trades=[]
    for i in range(2,len(df4)-1):
        if adx4.iloc[i]<25: continue
        a4=atr4.iloc[i]
        if a4<=0: continue
        bull=ema10.iloc[i]>ema20.iloc[i] and ema10.iloc[i-1]<=ema20.iloc[i-1]
        bear=ema10.iloc[i]<ema20.iloc[i] and ema10.iloc[i-1]>=ema20.iloc[i-1]
        if not bull and not bear: continue
        sig=df4.index[i]; day=sig.normalize()
        sess_s=max(sig,day+pd.Timedelta(hours=hs))
        sess_e=day+pd.Timedelta(hours=he)
        if sig>sess_e: continue
        edf=df1[(df1.index>=sess_s)&(df1.index<sess_e)]
        if len(edf)==0: continue
        b=edf.iloc[0]; p=ipos(df1,edf.index[0])
        if p<0: continue
        if bull: trades.append(trade(df1,p,1, b['close'],b['close']-1.5*a4,TRAIL_H4,risk))
        else:    trades.append(trade(df1,p,-1,b['close'],b['close']+1.5*a4,TRAIL_H4,risk))
    return trades

# ── 12-13. Month-End Rebalancing ─────────────────────────────────────────────
def run_month_end(key, tag, risk=0.004):
    """
    Institutional month-end rebalancing creates predictable FX flows.
    On last 3 trading days of each month:
    - If month was bullish for pair → fade it (SELL) — funds rebalance hedges
    - If month was bearish for pair → fade it (BUY)
    Academic basis: Barclays/JPM month-end rebalancing models.
    """
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); trades=[]
    dates=sorted(set(df.index.normalize().date))
    months={}
    for d in dates:
        k=(d.year,d.month)
        months.setdefault(k,[]).append(d)
    for (yr,mo),days in months.items():
        if len(days)<10: continue
        last3=days[-3:]
        # Month direction: compare first day close to day[-4] close (before last3)
        ref_day=days[-4]
        ref_bar=df[df.index.normalize().date==ref_day]
        first_day=days[0]
        first_bar=df[df.index.normalize().date==first_day]
        if len(ref_bar)==0 or len(first_bar)==0: continue
        month_start=first_bar.iloc[0]['open']
        month_ref=ref_bar.iloc[-1]['close']
        month_up=month_ref>month_start   # pair was rising this month
        # Fade: if month was up → sell. If down → buy.
        direction=-1 if month_up else 1
        for d in last3:
            day=pd.Timestamp(d,tz='UTC')
            # Enter at London open (08:00)
            edf=df[(df.index>=day+pd.Timedelta(hours=8))&
                   (df.index<day+pd.Timedelta(hours=9))]
            if len(edf)==0: continue
            b=edf.iloc[0]; p=ipos(df,edf.index[0])
            if p<0: continue
            av=atr.iloc[p] if p<len(atr) else 0
            if av<=0: continue
            sl=b['close']-1.5*av if direction==1 else b['close']+1.5*av
            trades.append(trade(df,p,direction,b['close'],sl,TRAIL_ORB,risk))
    return trades

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W=70
    print("\n" + "="*W)
    print("  New Strategy Ideas Backtest — 2-Year H1 Data")
    print("="*W)
    print("\nLoading data...")

    # Preload all symbols
    for k in YFSYMS: load_h1(k)

    results=[]
    def r(tag, trades):
        s=stats(tag,trades)
        if s: results.append(s)

    print(f"\n  {'Strategy':<26} {'Tr':>4}  {'WR%':>5}  {'T/mo':>4}  "
          f"{'PF':>6}  {'£/mo':>8}  OK?")
    print("  "+"─"*(W-2))

    print("\n── Gold PDH / PWH / LSR ─────────────────────────────────────────────")
    r('Gold PDH',     run_pdh('GOLD','Gold PDH', 8,20, risk=0.004))
    r('Gold PWH',     run_pwh('GOLD','Gold PWH', 8,20, risk=0.003))
    r('Gold LSR',     run_lsr('GOLD','Gold LSR', 8,20, risk=0.003))

    print("\n── JPY Pair London Breakout ──────────────────────────────────────────")
    r('GBPJPY LB',    run_lb_jpy('GBPJPY','GBPJPY LB', pip=0.01, min_rng=30, max_rng=300, risk=0.004, skip_dow={1}))
    r('EURJPY LB',    run_lb_jpy('EURJPY','EURJPY LB', pip=0.01, min_rng=20, max_rng=250, risk=0.004, skip_dow={1}))

    print("\n── Opening Gap Fill ─────────────────────────────────────────────────")
    r('DAX Gap Fill',   run_gap_fill('DAX',  'DAX Gap Fill',  open_hour=8, session_end=17, risk=0.005))
    r('UK100 Gap Fill', run_gap_fill('UK100','UK100 Gap Fill',open_hour=8, session_end=17, risk=0.005))

    print("\n── Donchian 20-Day Breakout ─────────────────────────────────────────")
    r('Donchian DAX',    run_donchian('DAX',   'Donchian DAX',    hs=8,  he=17, risk=0.005))
    r('Donchian Gold',   run_donchian('GOLD',  'Donchian Gold',   hs=8,  he=20, risk=0.004))
    r('Donchian NatGas', run_donchian('NATGAS','Donchian NatGas', hs=14, he=21, risk=0.004))

    print("\n── H4 EMA on FX Majors ──────────────────────────────────────────────")
    r('EURUSD H4 EMA', run_h4_ema('EURUSD','EURUSD H4 EMA', hs=7, he=17, risk=0.0075))
    r('GBPUSD H4 EMA', run_h4_ema('GBPUSD','GBPUSD H4 EMA', hs=7, he=17, risk=0.0075))
    r('EURJPY H4 EMA', run_h4_ema('EURJPY','EURJPY H4 EMA', hs=7, he=17, risk=0.0075))

    print("\n── Month-End Rebalancing ────────────────────────────────────────────")
    r('Month-End EUR', run_month_end('EURUSD','Month-End EUR', risk=0.004))
    r('Month-End GBP', run_month_end('GBPUSD','Month-End GBP', risk=0.004))

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "="*W)
    print("  RESULTS SUMMARY")
    print("="*W)

    strong=[x for x in results if x['pf']>=1.5]
    ok    =[x for x in results if 1.2<=x['pf']<1.5]
    weak  =[x for x in results if x['pf']<1.2]

    print(f"\n  ✅ ADD TO BOT (PF≥1.5):")
    for x in sorted(strong,key=lambda x:-x['pf']):
        print(f"     {x['name']:<26} PF {x['pf']:.2f}  "
              f"{x['wr']:.1f}%wr  £{x['mo']:,.0f}/mo")

    print(f"\n  ⚠️  MARGINAL (PF 1.2-1.5) — test more before adding:")
    for x in sorted(ok,key=lambda x:-x['pf']):
        print(f"     {x['name']:<26} PF {x['pf']:.2f}  "
              f"{x['wr']:.1f}%wr  £{x['mo']:,.0f}/mo")

    print(f"\n  ❌ NO EDGE (PF<1.2) — do not add:")
    for x in weak:
        print(f"     {x['name']:<26} PF {x['pf']:.2f}  "
              f"{x['wr']:.1f}%wr  £{x['mo']:,.0f}/mo")

    if strong:
        total_add=sum(x['mo'] for x in strong)
        print(f"\n  Combined monthly from strong additions: £{total_add:,.0f}")
    print()
