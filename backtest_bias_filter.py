"""
backtest_bias_filter.py — Daily trend bias filter test
Tests ORB, PDH, PWH strategies WITH and WITHOUT a D1 20-SMA bias filter.

Filter logic:
  Price > 20-day SMA → only take BUY signals
  Price < 20-day SMA → only take SELL signals
  Removes false breakouts against the daily trend (e.g. SELL when market is bullish)

Strategies tested: DAX ORB, NAS100 ORB, SP500 ORB, NatGas ORB,
                   PDH/PWH on DAX, UK100, NAS100, SP500

Run: git pull && python backtest_bias_filter.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT   = 70_000
TRAIL_ORB = 0.20

RISKS = {
    'DAX_ORB': 0.0075, 'NAS_ORB': 0.0075, 'SP5_ORB': 0.004, 'NG_ORB': 0.0075,
    'PDH_DAX': 0.005,  'PDH_UK100': 0.005,
    'PDH_NAS': 0.004,  'PDH_SP5': 0.004,
    'PWH_DAX': 0.004,  'PWH_UK100': 0.004,
    'PWH_NAS': 0.003,  'PWH_SP5': 0.003,
}

YFSYMS = {
    'DAX':    '^GDAXI', 'UK100':  '^FTSE',
    'NAS100': 'NQ=F',   'SP500':  'ES=F',
    'NATGAS': 'NG=F',
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
            _cache[key] = df if len(df) > 200 else None
        except:
            _cache[key] = None
    return _cache[key]

def load_daily_sma(key, period=20):
    """Returns a Series of 20-day SMA indexed by date."""
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
        sma = df['close'].rolling(period).mean()
        # Bias: +1 if close > SMA (bullish), -1 if close < SMA (bearish)
        bias = np.sign(df['close'] - sma)
        return bias
    except:
        return None

def calc_atr(df, p=14):
    h=df['high']; l=df['low']; pc=df['close'].shift(1)
    tr=pd.concat([h-l,(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(span=p,adjust=False).mean()

def ipos(df, ts):
    pos = df.index.searchsorted(ts)
    if pos >= len(df): return -1
    return int(pos) if df.index[int(pos)] == ts else -1

def sim(df, entry_pos, direction, entry, sl, trail_mult=0.2, max_bars=72):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0
    trail = sl_d * trail_mult
    cur_sl = sl; best = entry; be = False; last = entry
    for _, b in df.iloc[entry_pos+1 : entry_pos+1+max_bars].iterrows():
        last = b['close']
        if direction == 1:
            if b['low'] <= cur_sl: return (cur_sl-entry)/sl_d
            best = max(best, b['high'])
            if not be and best >= entry+sl_d: be=True; cur_sl=entry
            if be:
                ns=best-trail
                if ns>cur_sl: cur_sl=ns
        else:
            if b['high'] >= cur_sl: return (entry-cur_sl)/sl_d
            best = min(best, b['low'])
            if not be and best <= entry-sl_d: be=True; cur_sl=entry
            if be:
                ns=best+trail
                if ns<cur_sl: cur_sl=ns
    pts=(last-entry) if direction==1 else (entry-last)
    return pts/sl_d

def get_bias(bias_series, date):
    """Get D1 bias for a given date. Returns +1, -1, or 0."""
    if bias_series is None: return 0
    prev = date - pd.Timedelta(days=1)
    candidates = bias_series[bias_series.index.normalize() <= prev]
    if len(candidates) == 0: return 0
    return int(candidates.iloc[-1])

# ── Strategy runners ──────────────────────────────────────────────────────────

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=set(), bias_series=None):
    df = load_h1(key)
    if df is None: return []
    trades=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb=df[df.index==day+pd.Timedelta(hours=ref_h)]
        if len(rb)==0: continue
        rhi=rb.iloc[0]['high']; rlo=rb.iloc[0]['low']; rng=rhi-rlo
        if not (rmin<=rng<=rmax): continue
        edf=df[(df.index>=day+pd.Timedelta(hours=es))&(df.index<day+pd.Timedelta(hours=ee))]
        bias = get_bias(bias_series, day) if bias_series is not None else 0
        for j in range(len(edf)):
            b=edf.iloc[j]; p=ipos(df,edf.index[j])
            if p<0: continue
            if b['high']>rhi and (bias>=0):  # BUY — only if not bearish bias
                r=sim(df,p,1,rhi,rlo,TRAIL_ORB)
                trades.append(r*risk*ACCOUNT); break
            if b['low']<rlo and (bias<=0):   # SELL — only if not bullish bias
                r=sim(df,p,-1,rlo,rhi,TRAIL_ORB)
                trades.append(r*risk*ACCOUNT); break
    return trades

def run_orb_no_filter(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=set()):
    return run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow, bias_series=None)

def run_orb_filtered(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=set()):
    bias = load_daily_sma(key)
    return run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow, bias_series=bias)

def run_pdh(key, tag, hs, he, bias_series=None):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); trades=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC'); prev=day-pd.Timedelta(days=1)
        pd_=df[(df.index>=prev)&(df.index<day)]
        if len(pd_)<5: continue
        pdh=pd_['high'].max(); pdl=pd_['low'].min()
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&(df.index<day+pd.Timedelta(hours=he))]
        if len(edf)==0: continue
        a=atr.reindex(edf.index,method='ffill')
        if len(a)==0 or a.iloc[0]<=0: continue
        rng=pdh-pdl
        if not (a.iloc[0]*0.4<=rng<=a.iloc[0]*4.0): continue
        buf=a.iloc[0]*0.05
        bias=get_bias(bias_series,day) if bias_series is not None else 0
        for j in range(len(edf)):
            b=edf.iloc[j]; av=a.iloc[min(j,len(a)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pdh+buf and (bias>=0):
                r=sim(df,p,1,b['close'],b['close']-1.5*av,TRAIL_ORB)
                trades.append(r*risk*ACCOUNT); break
            if b['low']<pdl-buf and (bias<=0):
                r=sim(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB)
                trades.append(r*risk*ACCOUNT); break
    return trades

def run_pwh(key, tag, hs, he, bias_series=None):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); trades=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC'); dow=day.dayofweek
        ws=day-pd.Timedelta(days=dow+7); we=day-pd.Timedelta(days=dow)
        pw=df[(df.index>=ws)&(df.index<we)]
        if len(pw)<20: continue
        pwh=pw['high'].max(); pwl=pw['low'].min()
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&(df.index<day+pd.Timedelta(hours=he))]
        if len(edf)==0: continue
        a=atr.reindex(edf.index,method='ffill')
        if len(a)==0 or a.iloc[0]<=0: continue
        rng=pwh-pwl
        if not (0.5*a.iloc[0]<=rng<=8.0*a.iloc[0]): continue
        buf=a.iloc[0]*0.05
        bias=get_bias(bias_series,day) if bias_series is not None else 0
        for j in range(len(edf)):
            b=edf.iloc[j]; av=a.iloc[min(j,len(a)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pwh+buf and (bias>=0):
                r=sim(df,p,1,b['close'],b['close']-1.5*av,TRAIL_ORB)
                trades.append(r*risk*ACCOUNT); break
            if b['low']<pwl-buf and (bias<=0):
                r=sim(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB)
                trades.append(r*risk*ACCOUNT); break
    return trades

# ── Stats ─────────────────────────────────────────────────────────────────────
def stats(name, trades, days=504):
    if len(trades) < 5:
        print(f"  {name:<30} — insufficient data")
        return None
    arr=np.array(trades,dtype=float)
    wins=arr[arr>5]; loss=arr[arr<-5]
    n=len(arr); wr=len(wins)/n*100
    pf=wins.sum()/abs(loss.sum()) if len(loss) else 0
    tpm=n/days*21; mo=arr.sum()/days*21
    tag='✅' if pf>=1.5 else ('⚠️' if pf>=1.2 else '❌')
    print(f"  {name:<30} {n:>4}tr  {wr:>5.1f}%wr  {tpm:>4.1f}/mo  PF:{pf:>5.2f}  £{mo:>7,.0f}/mo  {tag}")
    return {'name':name,'n':n,'wr':wr,'pf':pf,'mo':mo,'trades':arr.tolist()}

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 75
    print("\n" + "="*W)
    print("  Daily Bias Filter Backtest — ORB + PDH + PWH")
    print("  Filter: only BUY when price > 20-day SMA, only SELL when price < 20-day SMA")
    print("="*W)
    print("\nLoading data...")
    for k in YFSYMS: load_h1(k)

    print("\nLoading daily SMA bias data...")
    bias = {k: load_daily_sma(k) for k in YFSYMS}

    print(f"\n  {'Strategy':<30} {'Tr':>4}  {'WR%':>5}  {'T/mo':>4}  {'PF':>6}  {'£/mo':>8}  OK?")
    print("  " + "─"*(W-2))

    # ── WITHOUT FILTER ────────────────────────────────────────────────────────
    print("\n── WITHOUT BIAS FILTER (current system) ────────────────────────────────")

    no_f = []
    def nf(tag, trades):
        s=stats(f"{tag} [no filter]",trades)
        if s: no_f.append(s)

    nf('DAX_ORB',   run_orb('DAX',   'DAX_ORB', 8, 9,12, 30, 300,  set()))
    nf('NAS_ORB',   run_orb('NAS100','NAS_ORB',13,14,16, 50,1500, {0}))
    nf('SP5_ORB',   run_orb('SP500', 'SP5_ORB',13,14,16,  5, 300, {0}))
    nf('NG_ORB',    run_orb('NATGAS','NG_ORB', 13,14,16,0.03,1.0, set()))
    nf('PDH_DAX',   run_pdh('DAX',   'PDH_DAX',   8,17))
    nf('PDH_UK100', run_pdh('UK100', 'PDH_UK100', 8,17))
    nf('PDH_NAS',   run_pdh('NAS100','PDH_NAS',  14,21))
    nf('PDH_SP5',   run_pdh('SP500', 'PDH_SP5',  14,21))
    nf('PWH_DAX',   run_pwh('DAX',   'PWH_DAX',   8,17))
    nf('PWH_UK100', run_pwh('UK100', 'PWH_UK100', 8,17))
    nf('PWH_NAS',   run_pwh('NAS100','PWH_NAS',  14,21))
    nf('PWH_SP5',   run_pwh('SP500', 'PWH_SP5',  14,21))

    total_nf = sum(s['mo'] for s in no_f)
    trades_nf = sum(s['n'] for s in no_f)
    print(f"\n  No filter total: {trades_nf} trades | £{total_nf:,.0f}/mo combined")

    # ── WITH FILTER ───────────────────────────────────────────────────────────
    print("\n── WITH D1 20-SMA BIAS FILTER ───────────────────────────────────────────")

    with_f = []
    def wf(tag, trades):
        s=stats(f"{tag} [bias filter]",trades)
        if s: with_f.append(s)

    wf('DAX_ORB',   run_orb('DAX',   'DAX_ORB', 8, 9,12, 30, 300,  set(),  bias['DAX']))
    wf('NAS_ORB',   run_orb('NAS100','NAS_ORB',13,14,16, 50,1500, {0},     bias['NAS100']))
    wf('SP5_ORB',   run_orb('SP500', 'SP5_ORB',13,14,16,  5, 300, {0},     bias['SP500']))
    wf('NG_ORB',    run_orb('NATGAS','NG_ORB', 13,14,16,0.03,1.0, set(),   bias['NATGAS']))
    wf('PDH_DAX',   run_pdh('DAX',   'PDH_DAX',   8,17, bias['DAX']))
    wf('PDH_UK100', run_pdh('UK100', 'PDH_UK100', 8,17, bias['UK100']))
    wf('PDH_NAS',   run_pdh('NAS100','PDH_NAS',  14,21, bias['NAS100']))
    wf('PDH_SP5',   run_pdh('SP500', 'PDH_SP5',  14,21, bias['SP500']))
    wf('PWH_DAX',   run_pwh('DAX',   'PWH_DAX',   8,17, bias['DAX']))
    wf('PWH_UK100', run_pwh('UK100', 'PWH_UK100', 8,17, bias['UK100']))
    wf('PWH_NAS',   run_pwh('NAS100','PWH_NAS',  14,21, bias['NAS100']))
    wf('PWH_SP5',   run_pwh('SP500', 'PWH_SP5',  14,21, bias['SP500']))

    total_wf = sum(s['mo'] for s in with_f)
    trades_wf = sum(s['n'] for s in with_f)
    print(f"\n  Bias filter total: {trades_wf} trades | £{total_wf:,.0f}/mo combined")

    # ── COMPARISON ────────────────────────────────────────────────────────────
    print("\n" + "="*W)
    print("  COMPARISON SUMMARY")
    print("="*W)
    print(f"\n  {'Strategy':<18} {'No filter PF':>13}  {'Bias filter PF':>14}  {'PF change':>10}  {'Trades lost':>11}")
    print("  " + "─"*(W-2))
    for nf_s in no_f:
        name=nf_s['name'].replace(' [no filter]','')
        wf_s=next((x for x in with_f if x['name'].replace(' [bias filter]','')==name),None)
        if wf_s:
            pf_change=wf_s['pf']-nf_s['pf']
            trades_lost=nf_s['n']-wf_s['n']
            sign='+' if pf_change>=0 else ''
            verdict='✅ better' if pf_change>0.05 else ('⚠️ worse' if pf_change<-0.05 else '➖ similar')
            print(f"  {name:<18} {nf_s['pf']:>12.2f}  {wf_s['pf']:>13.2f}  "
                  f"{sign}{pf_change:>+8.2f}  {trades_lost:>10}  {verdict}")

    print(f"\n  Monthly P&L without filter: £{total_nf:,.0f}")
    print(f"  Monthly P&L with filter:    £{total_wf:,.0f}")
    print(f"  Trades per month lost:      {(trades_nf-trades_wf)//24}")
    diff = total_wf - total_nf
    sign = '+' if diff >= 0 else ''
    print(f"  Net monthly change:         {sign}£{diff:,.0f}")
    print(f"\n  Verdict: {'✅ Add the filter' if diff > 0 else '❌ Filter hurts — keep as is'}")
    print()
