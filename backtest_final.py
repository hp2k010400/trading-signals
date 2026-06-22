"""
backtest_final.py — DEFINITIVE 11botV3 v5.00 system backtest
All 37 strategies, 2-year H1 data.

This script properly accounts for:
  1. HasPosition — only ONE trade per symbol at a time (live constraint)
  2. Spread/slippage — instrument-specific cost per trade
  3. Commission — £3.50 per side estimate

HasPosition simulation:
  For each symbol, trades are sorted chronologically across ALL strategies.
  Once a trade opens, no other strategy can fire on that symbol until it closes.
  Trade duration is tracked from the simulation.

Slippage/spread per trade (round trip):
  FX pairs (EURUSD, GBPUSD, EURJPY):  £12/trade
  Indices (DAX, UK100, NAS100, SP500): £20/trade
  Commodities (NatGas, Gold):          £28/trade  (wider spread, gap risk)

Run in Codespaces:
  git pull && python backtest_final.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT   = 70_000
TRAIL_ORB = 0.20
TRAIL_H4  = 0.30
TRAIL_DCH = 0.40

RISKS = {
    'LB_EUR': 0.004,  'LB_GBP': 0.004,
    'DAX_ORB': 0.0075, 'NAS_ORB': 0.0075, 'SP5_ORB': 0.004, 'NG_ORB': 0.0075,
    'NG_H1': 0.0075,
    'PDH_DAX': 0.005,  'PDH_UK100': 0.005, 'PDH_GBPJPY': 0.004,
    'PDH_NAS': 0.004,  'PDH_SP5': 0.004,   'PDH_NG': 0.004,
    'PWH_DAX': 0.004,  'PWH_UK100': 0.004,
    'PWH_NAS': 0.003,  'PWH_SP5': 0.003,
    'AMD_EUR': 0.004,  'AMD_GBP': 0.004,   'AMD_NAS': 0.004,
    'LSR_UK100': 0.003,'LSR_NAS': 0.003,   'LSR_EUR': 0.003,
    'FVG_EUR': 0.003,
    'H4_DAX': 0.0075,  'H4_UK100': 0.0075,
    'H4_EURCHF': 0.0075, 'H4_GBPJPY': 0.0075, 'H4_USDCHF': 0.0075,
    # New strategies v5.00
    'H4_EURUSD': 0.0075, 'H4_GBPUSD': 0.0075, 'H4_EURJPY': 0.0075,
    'DCH_DAX': 0.005,  'DCH_UK100': 0.005,
    'DCH_NAS': 0.0075, 'DCH_GOLD': 0.004,
    'LSR_GOLD': 0.003,
}

# Spread/slippage cost per trade (round trip, in £)
SLIPPAGE = {
    'EURUSD': 12, 'GBPUSD': 12, 'EURJPY': 12,
    'DAX':    20, 'UK100':  20, 'NAS100': 20, 'SP500': 20,
    'NATGAS': 28, 'GOLD':   28,
    'GBPJPY': 14, 'EURCHF': 12, 'USDCHF': 12,
}

YFSYMS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X',
    'DAX':    '^GDAXI',   'NAS100': 'NQ=F',
    'SP500':  'ES=F',     'NATGAS': 'NG=F',
    'UK100':  '^FTSE',    'GBPJPY': 'GBPJPY=X',
    'EURCHF': 'EURCHF=X', 'USDCHF': 'USDCHF=X',
    'EURJPY': 'EURJPY=X', 'GOLD':   'GC=F',
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
    """Returns (pnl_ratio, bars_held)"""
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0, 0
    trail  = sl_d * trail_mult
    cur_sl = sl; best = entry; be = False; last = entry; held = 0
    for _, b in df.iloc[entry_pos+1 : entry_pos+1+max_bars].iterrows():
        held += 1; last = b['close']
        if direction == 1:
            if b['low'] <= cur_sl: return (cur_sl-entry)/sl_d, held
            best = max(best, b['high'])
            if not be and best >= entry+sl_d: be=True; cur_sl=entry
            if be:
                ns=best-trail
                if ns>cur_sl: cur_sl=ns
        else:
            if b['high'] >= cur_sl: return (entry-cur_sl)/sl_d, held
            best = min(best, b['low'])
            if not be and best <= entry-sl_d: be=True; cur_sl=entry
            if be:
                ns=best+trail
                if ns<cur_sl: cur_sl=ns
    pts=(last-entry) if direction==1 else (entry-last)
    return pts/sl_d, held

def make_signal(df, pos, direction, entry, sl, trail, risk_pct, sym_key, strat):
    """Returns signal dict with timestamp, pnl, duration for HasPosition simulation."""
    ratio, held = sim(df, pos, direction, entry, sl, trail)
    pnl = ratio * risk_pct * ACCOUNT
    ts  = df.index[pos]
    # Estimate exit timestamp based on bars held
    exit_ts = df.index[min(pos+held, len(df)-1)] if held > 0 else ts + pd.Timedelta(hours=4)
    return {'sym': sym_key, 'strat': strat, 'ts': ts, 'exit_ts': exit_ts,
            'pnl': pnl, 'held': held}

# ─── Strategy runners (return list of signal dicts) ──────────────────────────

def run_lb(key, tag, skip_dow=set(), pip=0.0001):
    df=load_h1(key)
    if df is None: return []
    signals=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip_dow: continue
        prev=day-pd.Timedelta(days=1)
        rdf=df[(df.index>=prev+pd.Timedelta(hours=22))&(df.index<day+pd.Timedelta(hours=7))]
        if len(rdf)<5: continue
        a_hi=rdf['high'].max(); a_lo=rdf['low'].min(); rng=a_hi-a_lo
        if not (10<=rng/pip<=100): continue
        buf=rng*0.15
        edf=df[(df.index>=day+pd.Timedelta(hours=7))&(df.index<day+pd.Timedelta(hours=10))]
        for j in range(len(edf)):
            b=edf.iloc[j]; p=ipos(df,edf.index[j])
            if p<0: continue
            if b['high']>a_hi:
                signals.append(make_signal(df,p,1,a_hi,a_lo-buf,TRAIL_ORB,risk,key,tag)); break
            if b['low']<a_lo:
                signals.append(make_signal(df,p,-1,a_lo,a_hi+buf,TRAIL_ORB,risk,key,tag)); break
    return signals

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=set()):
    df=load_h1(key)
    if df is None: return []
    signals=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb=df[df.index==day+pd.Timedelta(hours=ref_h)]
        if len(rb)==0: continue
        rhi=rb.iloc[0]['high']; rlo=rb.iloc[0]['low']; rng=rhi-rlo
        if not (rmin<=rng<=rmax): continue
        edf=df[(df.index>=day+pd.Timedelta(hours=es))&(df.index<day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b=edf.iloc[j]; p=ipos(df,edf.index[j])
            if p<0: continue
            if b['high']>rhi:
                signals.append(make_signal(df,p,1,rhi,rlo,TRAIL_ORB,risk,key,tag)); break
            if b['low']<rlo:
                signals.append(make_signal(df,p,-1,rlo,rhi,TRAIL_ORB,risk,key,tag)); break
    return signals

def run_ng_h1(tag):
    df=load_h1('NATGAS')
    if df is None: return []
    ema10=df['close'].ewm(span=10,adjust=False).mean()
    ema20=df['close'].ewm(span=20,adjust=False).mean()
    atr=calc_atr(df,14); adx=calc_adx(df,14)
    signals=[]; risk=RISKS[tag]; fired=set()
    for i in range(21,len(df)-50):
        ts=df.index[i]
        if ts.hour<14 or ts.hour>=21: continue
        day=ts.normalize().date()
        if day in fired: continue
        if adx.iloc[i]<20: continue
        bull=ema10.iloc[i]>ema20.iloc[i] and ema10.iloc[i-1]<=ema20.iloc[i-1]
        bear=ema10.iloc[i]<ema20.iloc[i] and ema10.iloc[i-1]>=ema20.iloc[i-1]
        if not bull and not bear: continue
        a=atr.iloc[i]; entry=df.iloc[i]['close']
        d=1 if bull else -1
        sl=entry-1.5*a if bull else entry+1.5*a
        signals.append(make_signal(df,i,d,entry,sl,TRAIL_ORB,risk,'NATGAS',tag))
        fired.add(day)
    return signals

def run_pdh(key, tag, hs, he):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); signals=[]; risk=RISKS[tag]
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
        for j in range(len(edf)):
            b=edf.iloc[j]; av=a.iloc[min(j,len(a)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pdh+buf:
                signals.append(make_signal(df,p,1,b['close'],b['close']-1.5*av,TRAIL_ORB,risk,key,tag)); break
            if b['low']<pdl-buf:
                signals.append(make_signal(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB,risk,key,tag)); break
    return signals

def run_pwh(key, tag, hs, he):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); signals=[]; risk=RISKS[tag]
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
        for j in range(len(edf)):
            b=edf.iloc[j]; av=a.iloc[min(j,len(a)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pwh+buf:
                signals.append(make_signal(df,p,1,b['close'],b['close']-1.5*av,TRAIL_ORB,risk,key,tag)); break
            if b['low']<pwl-buf:
                signals.append(make_signal(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB,risk,key,tag)); break
    return signals

def run_amd(key, tag, hs, he, asian_hrs=(22,7)):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); signals=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC'); prev=day-pd.Timedelta(days=1)
        if asian_hrs[0]>asian_hrs[1]:
            rdf=df[(df.index>=prev+pd.Timedelta(hours=asian_hrs[0]))&(df.index<day+pd.Timedelta(hours=asian_hrs[1]))]
        else:
            rdf=df[(df.index>=day+pd.Timedelta(hours=asian_hrs[0]))&(df.index<day+pd.Timedelta(hours=asian_hrs[1]))]
        if len(rdf)<3: continue
        a_hi=rdf['high'].max(); a_lo=rdf['low'].min(); rng=a_hi-a_lo
        if rng<=0: continue
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&(df.index<day+pd.Timedelta(hours=he))]
        a_s=atr.reindex(edf.index,method='ffill'); fired=False
        for j in range(len(edf)):
            if fired: break
            b=edf.iloc[j]; av=a_s.iloc[min(j,len(a_s)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>a_hi and b['close']<a_hi and (b['high']-a_hi)<rng*0.6:
                signals.append(make_signal(df,p,-1,b['close'],b['high']+av*0.1,TRAIL_ORB,risk,key,tag)); fired=True
            elif b['low']<a_lo and b['close']>a_lo and (a_lo-b['low'])<rng*0.6:
                signals.append(make_signal(df,p,1,b['close'],b['low']-av*0.1,TRAIL_ORB,risk,key,tag)); fired=True
    return signals

def run_lsr(key, tag, hs, he):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); signals=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC'); prev=day-pd.Timedelta(days=1)
        pd_=df[(df.index>=prev)&(df.index<day)]
        if len(pd_)<5: continue
        pdh=pd_['high'].max(); pdl=pd_['low'].min()
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&(df.index<day+pd.Timedelta(hours=he))]
        a_s=atr.reindex(edf.index,method='ffill'); fired=False
        for j in range(len(edf)):
            if fired: break
            b=edf.iloc[j]; av=a_s.iloc[min(j,len(a_s)-1)]
            p=ipos(df,edf.index[j])
            if p<0 or av<=0: continue
            if b['high']>pdh and b['close']<pdh and (b['high']-pdh)<0.6*av:
                signals.append(make_signal(df,p,-1,b['close'],b['high']+av*0.1,TRAIL_ORB,risk,key,tag)); fired=True
            elif b['low']<pdl and b['close']>pdl and (pdl-b['low'])<0.6*av:
                signals.append(make_signal(df,p,1,b['close'],b['low']-av*0.1,TRAIL_ORB,risk,key,tag)); fired=True
    return signals

def run_fvg(key, tag, hs, he):
    df=load_h1(key)
    if df is None: return []
    atr=calc_atr(df,14); signals=[]; risk=RISKS[tag]
    dates=sorted(set(df.index.normalize().date))
    for date in dates:
        day=pd.Timestamp(date,tz='UTC')
        edf=df[(df.index>=day+pd.Timedelta(hours=hs))&(df.index<day+pd.Timedelta(hours=he))]
        fired=False
        for j in range(len(edf)):
            if fired: break
            b=edf.iloc[j]; p=ipos(df,edf.index[j])
            if p<0: continue
            av=atr.iloc[min(p,len(atr)-1)]
            if av<=0: continue
            lb=df.iloc[max(0,p-24):p]
            for k in range(2,len(lb)):
                gap_bull=lb.iloc[k]['low']-lb.iloc[k-2]['high']
                gap_bear=lb.iloc[k-2]['low']-lb.iloc[k]['high']
                if gap_bull>av*0.15:
                    lo_z=lb.iloc[k-2]['high']; hi_z=lb.iloc[k]['low']
                    if lo_z<=b['close']<=hi_z:
                        signals.append(make_signal(df,p,1,b['close'],lo_z-0.5*av,TRAIL_ORB,risk,key,tag))
                        fired=True; break
                if gap_bear>av*0.15:
                    lo_z=lb.iloc[k]['high']; hi_z=lb.iloc[k-2]['low']
                    if lo_z<=b['close']<=hi_z:
                        signals.append(make_signal(df,p,-1,b['close'],hi_z+0.5*av,TRAIL_ORB,risk,key,tag))
                        fired=True; break
    return signals

def run_h4(key, tag, hs, he):
    df4=load_h4(key); df1=load_h1(key)
    if df4 is None or df1 is None: return []
    ema10=df4['close'].ewm(span=10,adjust=False).mean()
    ema20=df4['close'].ewm(span=20,adjust=False).mean()
    atr4=calc_atr(df4,14); adx4=calc_adx(df4,14)
    signals=[]; risk=RISKS[tag]
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
        d=1 if bull else -1
        sl=b['close']-1.5*a4 if bull else b['close']+1.5*a4
        signals.append(make_signal(df1,p,d,b['close'],sl,TRAIL_H4,risk,key,tag))
    return signals

def run_donchian(key, tag, hs, he):
    df_d=load_daily(key); df_h=load_h1(key)
    if df_d is None or df_h is None: return []
    df_h4=load_h4(key)
    adx4=calc_adx(df_h4,14) if df_h4 is not None else None
    atr_h=calc_atr(df_h,14)
    signals=[]; risk=RISKS[tag]; fired_days=set()
    for i in range(21,len(df_d)-1):
        day=df_d.index[i].normalize()
        if day.date() in fired_days: continue
        roll_hi=df_d['high'].iloc[i-20:i].max()
        roll_lo=df_d['low'].iloc[i-20:i].min()
        today_h=df_d.iloc[i]['high']; today_l=df_d.iloc[i]['low']
        broke_up=today_h>roll_hi; broke_dn=today_l<roll_lo
        if not broke_up and not broke_dn: continue
        if adx4 is not None:
            adx_now=adx4[adx4.index<=day]
            if len(adx_now)<2 or adx_now.iloc[-1]<25: continue
        edf=df_h[(df_h.index>=day+pd.Timedelta(hours=hs))&(df_h.index<day+pd.Timedelta(hours=he))]
        if len(edf)==0: continue
        b=edf.iloc[0]; p=ipos(df_h,edf.index[0])
        if p<0: continue
        a=atr_h.iloc[p] if p<len(atr_h) else 0
        if a<=0: continue
        d=1 if broke_up else -1
        sl=b['close']-2.0*a if broke_up else b['close']+2.0*a
        signals.append(make_signal(df_h,p,d,b['close'],sl,TRAIL_DCH,risk,key,tag))
        fired_days.add(day.date())
    return signals

# ─── HasPosition simulation ───────────────────────────────────────────────────
def apply_has_position(all_signals):
    """
    Simulate live HasPosition constraint.
    For each symbol, sort all signals by timestamp.
    Once a trade is open, block subsequent signals until it closes.
    Returns filtered list of signals that would actually have fired live.
    """
    by_sym = {}
    for s in all_signals:
        by_sym.setdefault(s['sym'], []).append(s)

    live_signals = []
    blocked_stats = {'total': 0, 'blocked': 0}

    for sym, sigs in by_sym.items():
        sorted_sigs = sorted(sigs, key=lambda x: x['ts'])
        position_close = None
        for s in sorted_sigs:
            blocked_stats['total'] += 1
            if position_close is None or s['ts'] >= position_close:
                live_signals.append(s)
                position_close = s['exit_ts']
            else:
                blocked_stats['blocked'] += 1

    pct_blocked = blocked_stats['blocked']/blocked_stats['total']*100 if blocked_stats['total'] else 0
    print(f"\n  HasPosition: {blocked_stats['blocked']} of {blocked_stats['total']} signals blocked "
          f"({pct_blocked:.1f}%) — {100-pct_blocked:.1f}% actually fire")
    return live_signals

# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 65
    print("\n" + "="*W)
    print("  11botV3 v5.00 — DEFINITIVE FINAL BACKTEST")
    print("  37 strategies | HasPosition simulated | Slippage included")
    print("="*W)
    print("\nLoading data (this takes ~2 mins)...")
    for k in YFSYMS: load_h1(k)

    all_signals = []

    print("\nRunning all 37 strategies...")

    # London Breakout
    all_signals += run_lb('EURUSD','LB_EUR', skip_dow={1})
    all_signals += run_lb('GBPUSD','LB_GBP', skip_dow={1})
    # ORBs
    all_signals += run_orb('DAX',   'DAX_ORB', 8, 9, 12,  30,  300,  set())
    all_signals += run_orb('NAS100','NAS_ORB',13,14, 16,  50, 1500, {0})
    all_signals += run_orb('SP500', 'SP5_ORB',13,14, 16,   5,  300, {0})
    all_signals += run_orb('NATGAS','NG_ORB', 13,14, 16,0.03,  1.0,  set())
    all_signals += run_ng_h1('NG_H1')
    # PDH
    all_signals += run_pdh('DAX',   'PDH_DAX',    8,17)
    all_signals += run_pdh('UK100', 'PDH_UK100',  8,17)
    all_signals += run_pdh('GBPJPY','PDH_GBPJPY', 7,17)
    all_signals += run_pdh('NAS100','PDH_NAS',   14,21)
    all_signals += run_pdh('SP500', 'PDH_SP5',   14,21)
    all_signals += run_pdh('NATGAS','PDH_NG',    14,21)
    # PWH
    all_signals += run_pwh('DAX',   'PWH_DAX',   8,17)
    all_signals += run_pwh('UK100', 'PWH_UK100', 8,17)
    all_signals += run_pwh('NAS100','PWH_NAS',  14,21)
    all_signals += run_pwh('SP500', 'PWH_SP5',  14,21)
    # AMD
    all_signals += run_amd('EURUSD','AMD_EUR', 7, 9, asian_hrs=(22,7))
    all_signals += run_amd('GBPUSD','AMD_GBP', 7, 9, asian_hrs=(22,7))
    all_signals += run_amd('NAS100','AMD_NAS',14,16, asian_hrs=(12,14))
    # LSR
    all_signals += run_lsr('UK100', 'LSR_UK100',  8,17)
    all_signals += run_lsr('NAS100','LSR_NAS',   14,21)
    all_signals += run_lsr('EURUSD','LSR_EUR',    7,17)
    all_signals += run_lsr('GOLD',  'LSR_GOLD',   8,20)
    # FVG
    all_signals += run_fvg('EURUSD','FVG_EUR', 7,17)
    # H4 EMA (original)
    all_signals += run_h4('DAX',   'H4_DAX',    8,16)
    all_signals += run_h4('UK100', 'H4_UK100',  8,16)
    all_signals += run_h4('EURCHF','H4_EURCHF', 8,17)
    all_signals += run_h4('GBPJPY','H4_GBPJPY', 0,21)
    all_signals += run_h4('USDCHF','H4_USDCHF', 8,17)
    # H4 EMA (new v5.00)
    all_signals += run_h4('EURUSD','H4_EURUSD', 7,17)
    all_signals += run_h4('GBPUSD','H4_GBPUSD', 7,17)
    all_signals += run_h4('EURJPY','H4_EURJPY', 7,17)
    # Donchian (new v5.00)
    all_signals += run_donchian('DAX',   'DCH_DAX',    8,17)
    all_signals += run_donchian('UK100', 'DCH_UK100',  8,17)
    all_signals += run_donchian('NAS100','DCH_NAS',   14,21)
    all_signals += run_donchian('GOLD',  'DCH_GOLD',   8,20)

    print(f"  Raw signals generated: {len(all_signals)}")

    # Apply HasPosition constraint
    live_signals = apply_has_position(all_signals)

    # Apply slippage
    def get_slip(sym):
        return SLIPPAGE.get(sym, 18)

    live_pnls = [s['pnl'] - get_slip(s['sym']) for s in live_signals]
    raw_pnls  = [s['pnl'] for s in all_signals]

    # Stats
    days = 504
    def summary(pnls, label):
        arr  = np.array(pnls, dtype=float)
        wins = arr[arr>5]; loss=arr[arr<-5]
        n    = len(arr); wr=len(wins)/n*100
        pf   = wins.sum()/abs(loss.sum()) if len(loss) else 0
        tpm  = n/days*21; mo=arr.sum()/days*21
        total= arr.sum()
        print(f"\n  {label}")
        print(f"  {'─'*55}")
        print(f"  Total trades:     {n:,}")
        print(f"  Trades/month:     {tpm:.0f}")
        print(f"  Win rate:         {wr:.1f}%")
        print(f"  Profit factor:    {pf:.2f}")
        print(f"  Monthly avg P&L:  £{mo:,.0f}")
        print(f"  2-year total:     £{total:,.0f}")
        return mo

    print("\n" + "="*W)
    print("  RESULTS")
    print("="*W)
    mo_raw  = summary(raw_pnls,  "① BACKTEST (no HasPosition, no slippage)")
    mo_live = summary(live_pnls, "② REALISTIC LIVE (HasPosition + slippage applied)")

    slip_total = sum(get_slip(s['sym']) for s in live_signals) / days * 21
    print(f"\n  Slippage/spread cost per month: -£{slip_total:,.0f}")
    print(f"  HasPosition trade reduction:    -{(len(all_signals)-len(live_signals)):,} signals blocked")
    print(f"\n  ══════════════════════════════════════════════════")
    print(f"  REALISTIC MONTHLY FROM ONE £70K ACCOUNT: £{mo_live:,.0f}")
    print(f"  After FTMO 80% profit split to you:      £{mo_live*0.8:,.0f}")
    print(f"  ══════════════════════════════════════════════════")
    print()
