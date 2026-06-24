"""
backtest_system_combined.py — Full 11botV3 system backtest
All 29 strategy-instrument combinations, 2-year H1 data.

Matches live bot logic as closely as yfinance data allows:
  • Correct risk % per strategy (as coded in 11botV3.mq5)
  • 0.2R trail for LB/ORB/PDH/PWH/AMD/LSR/FVG
  • 0.3R trail for H4 EMA
  • ATR-based SL for PDH/PWH/AMD/LSR/H4
  • One trade per strategy per day (daily fired flag)
  • Spread + slippage modelled per strategy in R units (COST_R)

Spread/slippage model:
  Breakout strategies (LB, ORB): 0.08R — tight entry + slippage on breakout level
  Trend/PDH/PWH: 0.05-0.06R      — larger ATR SL so spread is smaller fraction
  Reversal (AMD, LSR, FVG): 0.05-0.06R
  H4 EMA: 0.04-0.05R             — biggest SL so cheapest in R terms

Run in GitHub Codespaces:
  pip install yfinance pandas numpy && python backtest_system_combined.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

# ── Config ──────────────────────────────────────────────────────────────────
ACCOUNT   = 70_000
TRAIL_ORB = 0.20
TRAIL_H4  = 0.30
TRAIL_DCH = 0.40

# Partial close config — set to None to disable, or float e.g. 1.0 = close 50% at 1R profit
PARTIAL_R = None   # toggled at runtime — see main block

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
    'H4_EURUSD': 0.0075, 'H4_GBPUSD': 0.0075, 'H4_EURJPY': 0.0075,
    'DCH_DAX': 0.005, 'DCH_UK100': 0.005, 'DCH_NAS': 0.0075, 'DCH_GOLD': 0.004,
    'LSR_GOLD': 0.003,
}

# Spread + slippage per trade in R units
# Entry spread + round-trip commission + execution slippage
COST_R = {
    'LB_EUR': 0.08,   'LB_GBP': 0.08,
    'DAX_ORB': 0.07,  'NAS_ORB': 0.06,  'SP5_ORB': 0.06,  'NG_ORB': 0.06,
    'NG_H1': 0.05,
    'PDH_DAX': 0.06,  'PDH_UK100': 0.06, 'PDH_GBPJPY': 0.05,
    'PDH_NAS': 0.05,  'PDH_SP5': 0.05,   'PDH_NG': 0.06,
    'PWH_DAX': 0.06,  'PWH_UK100': 0.06,
    'PWH_NAS': 0.05,  'PWH_SP5': 0.05,
    'AMD_EUR': 0.06,  'AMD_GBP': 0.07,   'AMD_NAS': 0.05,
    'LSR_UK100': 0.05,'LSR_NAS': 0.05,   'LSR_EUR': 0.05,
    'FVG_EUR': 0.06,
    'H4_DAX': 0.04,   'H4_UK100': 0.04,
    'H4_EURCHF': 0.05,'H4_GBPJPY': 0.04, 'H4_USDCHF': 0.05,
    'H4_EURUSD': 0.04,'H4_GBPUSD': 0.04, 'H4_EURJPY': 0.04,
    'DCH_DAX': 0.05,  'DCH_UK100': 0.05, 'DCH_NAS': 0.05, 'DCH_GOLD': 0.05,
    'LSR_GOLD': 0.05,
}

YFSYMS = {
    'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X',
    'DAX':    '^GDAXI',   'NAS100': 'NQ=F',
    'SP500':  'ES=F',     'NATGAS': 'NG=F',
    'UK100':  '^FTSE',    'GBPJPY': 'GBPJPY=X',
    'EURCHF': 'EURCHF=X', 'USDCHF': 'USDCHF=X',
    'EURJPY': 'EURJPY=X', 'GOLD':   'GC=F',
}

# ── Data ─────────────────────────────────────────────────────────────────────
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

# ── Trade simulator ───────────────────────────────────────────────────────────
def sim(df, entry_pos, direction, entry, sl, trail_mult, max_bars=48):
    """
    Simulate a trade on H1 bars. Returns R ratio.
    If PARTIAL_R is set, closes 50% at PARTIAL_R profit and trails the rest.
    """
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0
    trail    = sl_d * trail_mult
    cur_sl   = sl
    best     = entry
    be       = False
    partial_done = False
    locked_r = 0.0    # R locked in from partial close
    size     = 1.0    # remaining position size (halved after partial)

    bars = df.iloc[entry_pos+1 : entry_pos+1+max_bars]
    last_price = entry

    for _, b in bars.iterrows():
        last_price = b['close']
        if direction == 1:                          # BUY
            if b['low'] <= cur_sl:
                return locked_r + (cur_sl - entry) / sl_d * size
            best = max(best, b['high'])
            if not be and best >= entry + sl_d:
                be = True; cur_sl = entry
            if be:
                ns = best - trail
                if ns > cur_sl: cur_sl = ns
            if PARTIAL_R and not partial_done and best >= entry + PARTIAL_R * sl_d:
                locked_r     = PARTIAL_R * 0.5     # lock in PARTIAL_R R on 50%
                partial_done = True
                size         = 0.5
        else:                                       # SELL
            if b['high'] >= cur_sl:
                return locked_r + (entry - cur_sl) / sl_d * size
            best = min(best, b['low'])
            if not be and best <= entry - sl_d:
                be = True; cur_sl = entry
            if be:
                ns = best + trail
                if ns < cur_sl: cur_sl = ns
            if PARTIAL_R and not partial_done and best <= entry - PARTIAL_R * sl_d:
                locked_r     = PARTIAL_R * 0.5
                partial_done = True
                size         = 0.5

    pts = (last_price - entry) if direction == 1 else (entry - last_price)
    return locked_r + pts / sl_d * size

def make_trade(df, entry_pos, direction, entry, sl, trail_mult, risk_pct, cost_r=0.0):
    """Returns £P&L for a single trade, after deducting spread + slippage."""
    r_ratio = sim(df, entry_pos, direction, entry, sl, trail_mult)
    r_ratio -= cost_r
    return r_ratio * risk_pct * ACCOUNT

def ipos(df, ts):
    """Integer position of timestamp ts in df. Returns -1 if not found."""
    arr = df.index.searchsorted(ts)
    if arr >= len(df): return -1
    return int(arr) if df.index[int(arr)] == ts else -1

# ── Stats printer ─────────────────────────────────────────────────────────────
def stats(name, trades):
    if len(trades) < 8:
        print(f"  {name:<22}  — insufficient data ({len(trades)} trades)")
        return None
    arr  = np.array(trades, dtype=float)
    wins = arr[arr >  5]
    loss = arr[arr < -5]
    n    = len(arr)
    wr   = len(wins)/n*100
    gp   = wins.sum() if len(wins) else 0
    gl   = abs(loss.sum()) if len(loss) else 1e-9
    pf   = gp / gl
    days = 504   # ~2 trading years
    tpm  = n/days*21
    mo   = arr.sum()/days*21
    tag  = '✅' if pf >= 1.5 else ('⚠️ ' if pf >= 1.2 else '❌')
    print(f"  {name:<22} {n:>4}tr {wr:>5.1f}%wr {tpm:>4.1f}/mo "
          f"PF:{pf:>5.2f}  £{mo:>6,.0f}/mo  {tag}")
    return {'name': name, 'n': n, 'wr': round(wr,1),
            'pf': round(pf,2), 'mo': round(mo,0), 'trades': arr.tolist()}

# ── 1-2. London Breakout ──────────────────────────────────────────────────────
def run_lb(key, tag, skip_dow=set(), pip=0.0001):
    df = load_h1(key)
    if df is None: return []
    trades = []; risk = RISKS[tag]; cost = COST_R.get(tag, 0.06)
    dates  = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        prev = day - pd.Timedelta(days=1)
        rng_df = df[(df.index >= prev+pd.Timedelta(hours=22)) &
                    (df.index <  day +pd.Timedelta(hours=7))]
        if len(rng_df) < 5: continue
        a_hi = rng_df['high'].max(); a_lo = rng_df['low'].min()
        rng  = a_hi - a_lo
        if not (10 <= rng/pip <= 100): continue
        buf  = rng * 0.15
        edf  = df[(df.index >= day+pd.Timedelta(hours=7)) &
                  (df.index <  day+pd.Timedelta(hours=10))]
        for j in range(len(edf)):
            b  = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > a_hi:
                trades.append(make_trade(df,p,1, a_hi, a_lo-buf,TRAIL_ORB,risk,cost)); break
            if b['low']  < a_lo:
                trades.append(make_trade(df,p,-1,a_lo, a_hi+buf,TRAIL_ORB,risk,cost)); break
    return trades

# ── 3-6. ORB (DAX, NAS100, SP500, NatGas) ────────────────────────────────────
def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=set()):
    df = load_h1(key)
    if df is None: return []
    trades = []; risk = RISKS[tag]; cost = COST_R.get(tag, 0.06)
    dates  = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb = df[df.index == day+pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']; rng = rhi-rlo
        if not (rmin <= rng <= rmax): continue
        edf = df[(df.index >= day+pd.Timedelta(hours=es)) &
                 (df.index <  day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                trades.append(make_trade(df,p,1, rhi,rlo,TRAIL_ORB,risk,cost)); break
            if b['low']  < rlo:
                trades.append(make_trade(df,p,-1,rlo,rhi,TRAIL_ORB,risk,cost)); break
    return trades

# ── 7. NatGas H1 EMA fallback ─────────────────────────────────────────────────
def run_ng_h1(tag):
    df = load_h1('NATGAS')
    if df is None: return []
    ema10 = df['close'].ewm(span=10,adjust=False).mean()
    ema20 = df['close'].ewm(span=20,adjust=False).mean()
    atr   = calc_atr(df, 14)
    adx   = calc_adx(df, 14)
    trades = []; risk = RISKS[tag]; cost = COST_R.get(tag, 0.06)
    dates  = sorted(set(df.index.normalize().date))
    fired_days = set()
    for i in range(21, len(df)-50):
        ts = df.index[i]
        if ts.hour < 14 or ts.hour >= 21: continue
        day = ts.normalize().date()
        if day in fired_days: continue
        if adx.iloc[i] < 20: continue
        bull = ema10.iloc[i] > ema20.iloc[i] and ema10.iloc[i-1] <= ema20.iloc[i-1]
        bear = ema10.iloc[i] < ema20.iloc[i] and ema10.iloc[i-1] >= ema20.iloc[i-1]
        if not bull and not bear: continue
        a = atr.iloc[i]; entry = df.iloc[i]['close']
        if bull:
            trades.append(make_trade(df,i,1, entry,entry-1.5*a,TRAIL_ORB,risk,cost))
        else:
            trades.append(make_trade(df,i,-1,entry,entry+1.5*a,TRAIL_ORB,risk,cost))
        fired_days.add(day)
    return trades

# ── 8-13. PDH/PDL breakout ────────────────────────────────────────────────────
def run_pdh(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df,14); trades=[]; risk=RISKS[tag]; cost=COST_R.get(tag,0.06)
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        pd_  = df[(df.index >= prev) & (df.index < day)]
        if len(pd_) < 5: continue
        pdh = pd_['high'].max(); pdl = pd_['low'].min()
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        if len(edf) == 0: continue
        a = atr.reindex(edf.index, method='ffill')
        rng = pdh - pdl
        if len(a) == 0 or a.iloc[0] <= 0: continue
        if not (a.iloc[0]*0.4 <= rng <= a.iloc[0]*4.0): continue
        buf = a.iloc[0]*0.05
        for j in range(len(edf)):
            b = edf.iloc[j]; av = a.iloc[min(j,len(a)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or av <= 0: continue
            if b['high'] > pdh+buf:
                trades.append(make_trade(df,p,1, b['close'],b['close']-1.5*av,TRAIL_ORB,risk,cost)); break
            if b['low']  < pdl-buf:
                trades.append(make_trade(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB,risk,cost)); break
    return trades

# ── 14-17. PWH/PWL breakout ───────────────────────────────────────────────────
def run_pwh(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df,14); trades=[]; risk=RISKS[tag]; cost=COST_R.get(tag,0.06)
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        dow = day.dayofweek
        ws  = day - pd.Timedelta(days=dow+7)
        we  = day - pd.Timedelta(days=dow)
        pw  = df[(df.index >= ws) & (df.index < we)]
        if len(pw) < 20: continue
        pwh=pw['high'].max(); pwl=pw['low'].min()
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        if len(edf) == 0: continue
        a = atr.reindex(edf.index, method='ffill')
        if len(a) == 0 or a.iloc[0] <= 0: continue
        rng = pwh - pwl
        if not (0.5*a.iloc[0] <= rng <= 8.0*a.iloc[0]): continue
        buf = a.iloc[0]*0.05
        for j in range(len(edf)):
            b = edf.iloc[j]; av = a.iloc[min(j,len(a)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or av <= 0: continue
            if b['high'] > pwh+buf:
                trades.append(make_trade(df,p,1, b['close'],b['close']-1.5*av,TRAIL_ORB,risk,cost)); break
            if b['low']  < pwl-buf:
                trades.append(make_trade(df,p,-1,b['close'],b['close']+1.5*av,TRAIL_ORB,risk,cost)); break
    return trades

# ── 18-20. AMD manipulation reversal ─────────────────────────────────────────
def run_amd(key, tag, hs, he, asian_hrs=(22,7)):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df,14); trades=[]; risk=RISKS[tag]; cost=COST_R.get(tag,0.06)
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if asian_hrs[0] > asian_hrs[1]:   # overnight (FX: 22-07)
            rdf = df[(df.index >= prev+pd.Timedelta(hours=asian_hrs[0])) &
                     (df.index <  day +pd.Timedelta(hours=asian_hrs[1]))]
        else:                              # same-day (US: 12-14)
            rdf = df[(df.index >= day+pd.Timedelta(hours=asian_hrs[0])) &
                     (df.index <  day+pd.Timedelta(hours=asian_hrs[1]))]
        if len(rdf) < 3: continue
        a_hi = rdf['high'].max(); a_lo = rdf['low'].min(); rng = a_hi-a_lo
        if rng <= 0: continue
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        a_s = atr.reindex(edf.index, method='ffill')
        fired = False
        for j in range(len(edf)):
            if fired: break
            b = edf.iloc[j]; av = a_s.iloc[min(j,len(a_s)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or av <= 0: continue
            if b['high']>a_hi and b['close']<a_hi and (b['high']-a_hi)<rng*0.6:
                trades.append(make_trade(df,p,-1,b['close'],b['high']+av*0.1,TRAIL_ORB,risk,cost))
                fired=True
            elif b['low']<a_lo and b['close']>a_lo and (a_lo-b['low'])<rng*0.6:
                trades.append(make_trade(df,p,1, b['close'],b['low']-av*0.1, TRAIL_ORB,risk,cost))
                fired=True
    return trades

# ── 21-23. Liquidity sweep reversal ──────────────────────────────────────────
def run_lsr(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df,14); trades=[]; risk=RISKS[tag]; cost=COST_R.get(tag,0.06)
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        pd_  = df[(df.index >= prev) & (df.index < day)]
        if len(pd_) < 5: continue
        pdh=pd_['high'].max(); pdl=pd_['low'].min()
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        a_s = atr.reindex(edf.index, method='ffill')
        fired = False
        for j in range(len(edf)):
            if fired: break
            b = edf.iloc[j]; av = a_s.iloc[min(j,len(a_s)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or av <= 0: continue
            if b['high']>pdh and b['close']<pdh and (b['high']-pdh)<0.6*av:
                trades.append(make_trade(df,p,-1,b['close'],b['high']+av*0.1,TRAIL_ORB,risk,cost))
                fired=True
            elif b['low']<pdl and b['close']>pdl and (pdl-b['low'])<0.6*av:
                trades.append(make_trade(df,p,1, b['close'],b['low']-av*0.1, TRAIL_ORB,risk,cost))
                fired=True
    return trades

# ── 24. Fair Value Gap ────────────────────────────────────────────────────────
def run_fvg(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df,14); trades=[]; risk=RISKS[tag]; cost=COST_R.get(tag,0.06)
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        fired = False
        for j in range(len(edf)):
            if fired: break
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            av = atr.iloc[min(p, len(atr)-1)]
            if av <= 0: continue
            lb = df.iloc[max(0,p-24):p]
            for k in range(2, len(lb)):
                gap_bull = lb.iloc[k]['low']  - lb.iloc[k-2]['high']
                gap_bear = lb.iloc[k-2]['low'] - lb.iloc[k]['high']
                if gap_bull > av*0.15:
                    lo_z=lb.iloc[k-2]['high']; hi_z=lb.iloc[k]['low']
                    if lo_z <= b['close'] <= hi_z:
                        trades.append(make_trade(df,p,1, b['close'],lo_z-0.5*av,TRAIL_ORB,risk,cost))
                        fired=True; break
                if gap_bear > av*0.15:
                    lo_z=lb.iloc[k]['high']; hi_z=lb.iloc[k-2]['low']
                    if lo_z <= b['close'] <= hi_z:
                        trades.append(make_trade(df,p,-1,b['close'],hi_z+0.5*av,TRAIL_ORB,risk,cost))
                        fired=True; break
    return trades

# ── Daily data loader ────────────────────────────────────────────────────────
def load_d1(key):
    ck = key + '_d1'
    if ck not in _cache:
        sym = YFSYMS.get(key)
        if not sym: _cache[ck] = None; return None
        try:
            df = yf.download(sym, interval='1d', period='730d',
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None: df.index = df.index.tz_localize('UTC')
            else:                   df.index = df.index.tz_convert('UTC')
            _cache[ck] = df if len(df) > 50 else None
        except:
            _cache[ck] = None
    return _cache[ck]

# ── Donchian 20-day breakout ──────────────────────────────────────────────────
def run_donchian(key, tag, hs, he):
    df1 = load_h1(key); df4 = load_h4(key); dfd = load_d1(key)
    if df1 is None or df4 is None or dfd is None: return []
    adx4 = calc_adx(df4, 14); atr1 = calc_atr(df1, 14)
    trades = []; risk = RISKS.get(tag, 0.005); cost = COST_R.get(tag, 0.06)
    fired_days = set()
    dates = sorted(set(df1.index.normalize().date))
    for date in dates:
        if date in fired_days: continue
        day = pd.Timestamp(date, tz='UTC')
        d_slice = dfd[dfd.index < day].tail(20)
        if len(d_slice) < 20: continue
        d20hi = d_slice['high'].max(); d20lo = d_slice['low'].min()
        h4_at = adx4[adx4.index <= day + pd.Timedelta(hours=hs)]
        if len(h4_at) == 0 or h4_at.iloc[-1] < 25: continue
        edf = df1[(df1.index >= day+pd.Timedelta(hours=hs)) &
                  (df1.index <  day+pd.Timedelta(hours=he))]
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df1, edf.index[j])
            if p < 0: continue
            av = atr1.iloc[min(p, len(atr1)-1)]
            if av <= 0: continue
            if b['high'] > d20hi:
                trades.append(make_trade(df1,p,1, b['close'],b['close']-2.0*av,TRAIL_DCH,risk,cost))
                fired_days.add(date); break
            elif b['low'] < d20lo:
                trades.append(make_trade(df1,p,-1,b['close'],b['close']+2.0*av,TRAIL_DCH,risk,cost))
                fired_days.add(date); break
    return trades

# ── 25-29. H4 EMA trend ───────────────────────────────────────────────────────
def run_h4(key, tag, hs, he):
    df4 = load_h4(key); df1 = load_h1(key)
    if df4 is None or df1 is None: return []
    ema10 = df4['close'].ewm(span=10,adjust=False).mean()
    ema20 = df4['close'].ewm(span=20,adjust=False).mean()
    atr4  = calc_atr(df4,14)
    adx4  = calc_adx(df4,14)
    trades=[]; risk=RISKS[tag]; cost=COST_R.get(tag,0.05)
    for i in range(2, len(df4)-1):
        if adx4.iloc[i] < 25: continue
        a4 = atr4.iloc[i]
        if a4 <= 0: continue
        bull = ema10.iloc[i]>ema20.iloc[i] and ema10.iloc[i-1]<=ema20.iloc[i-1]
        bear = ema10.iloc[i]<ema20.iloc[i] and ema10.iloc[i-1]>=ema20.iloc[i-1]
        if not bull and not bear: continue
        sig_time = df4.index[i]
        day = sig_time.normalize()
        sess_s = day + pd.Timedelta(hours=hs)
        sess_e = day + pd.Timedelta(hours=he)
        if sig_time > sess_e:
            continue
        start = max(sig_time, sess_s)
        edf = df1[(df1.index >= start) & (df1.index < sess_e)]
        if len(edf) == 0: continue
        b = edf.iloc[0]; p = ipos(df1, edf.index[0])
        if p < 0: continue
        if bull:
            trades.append(make_trade(df1,p,1, b['close'],b['close']-1.5*a4,TRAIL_H4,risk,cost))
        else:
            trades.append(make_trade(df1,p,-1,b['close'],b['close']+1.5*a4,TRAIL_H4,risk,cost))
    return trades

# ── Strategy runner ───────────────────────────────────────────────────────────
def run_portfolio(print_table=True):
    """Run all strategies, return combined stats dict. Uses global PARTIAL_R."""
    global results
    results = []
    W = 65

    def r(tag, trades):
        s = stats(tag, trades)
        if s: results.append(s)

    if print_table:
        print(f"\n  {'Strategy':<22} {'Tr':>4}  {'WR%':>5}  {'T/mo':>4}  "
              f"{'PF':>6}  {'£/mo':>7}  {'OK?'}")
        print("  " + "─"*(W-2))

    if print_table: print("\n── London Breakout ──────────────────────────────────────────────")
    r('LB_EUR',  run_lb('EURUSD','LB_EUR', skip_dow={1}))
    r('LB_GBP',  run_lb('GBPUSD','LB_GBP', skip_dow={1}))

    if print_table: print("\n── ORBs ─────────────────────────────────────────────────────────")
    r('DAX_ORB', run_orb('DAX',   'DAX_ORB', 8, 9, 12,  30,  300,  set()))
    r('NAS_ORB', run_orb('NAS100','NAS_ORB',13,14, 16,  50, 1500, {0}))
    r('SP5_ORB', run_orb('SP500', 'SP5_ORB',13,14, 16,   5,  300, {0}))
    r('NG_ORB',  run_orb('NATGAS','NG_ORB', 13,14, 16,0.03,  1.0,  set()))

    if print_table: print("\n── NatGas H1 EMA ────────────────────────────────────────────────")
    r('NG_H1',   run_ng_h1('NG_H1'))

    if print_table: print("\n── PDH/PDL Breakout ─────────────────────────────────────────────")
    r('PDH_DAX',    run_pdh('DAX',   'PDH_DAX',    8, 17))
    r('PDH_GBPJPY', run_pdh('GBPJPY','PDH_GBPJPY', 7, 17))
    r('PDH_NAS',    run_pdh('NAS100','PDH_NAS',   14, 21))
    r('PDH_SP5',    run_pdh('SP500', 'PDH_SP5',   14, 21))
    # PDH_UK100 removed (PF 1.07) | PDH_NG removed (PF 1.00)

    if print_table: print("\n── PWH/PWL Breakout ─────────────────────────────────────────────")
    r('PWH_UK100', run_pwh('UK100', 'PWH_UK100',  8, 17))
    r('PWH_NAS',   run_pwh('NAS100','PWH_NAS',   14, 21))
    # PWH_DAX removed (PF 1.11) | PWH_SP5 removed (PF 0.89)

    if print_table: print("\n── AMD Manipulation Reversal ────────────────────────────────────")
    r('AMD_EUR', run_amd('EURUSD','AMD_EUR', 7,  9, asian_hrs=(22,7)))
    r('AMD_GBP', run_amd('GBPUSD','AMD_GBP', 7,  9, asian_hrs=(22,7)))
    r('AMD_NAS', run_amd('NAS100','AMD_NAS',14, 16, asian_hrs=(12,14)))

    if print_table: print("\n── Liquidity Sweep Reversal ─────────────────────────────────────")
    r('LSR_UK100', run_lsr('UK100', 'LSR_UK100',  8, 17))
    r('LSR_NAS',   run_lsr('NAS100','LSR_NAS',   14, 21))
    r('LSR_EUR',   run_lsr('EURUSD','LSR_EUR',    7, 17))

    if print_table: print("\n── Fair Value Gap ───────────────────────────────────────────────")
    r('FVG_EUR', run_fvg('EURUSD','FVG_EUR', 7, 17))

    if print_table: print("\n── H4 EMA Trend ─────────────────────────────────────────────────")
    r('H4_DAX',    run_h4('DAX',   'H4_DAX',    8, 16))
    r('H4_UK100',  run_h4('UK100', 'H4_UK100',  8, 16))
    r('H4_GBPJPY', run_h4('GBPJPY','H4_GBPJPY', 0, 21))
    r('H4_USDCHF', run_h4('USDCHF','H4_USDCHF', 8, 17))
    r('H4_EURUSD', run_h4('EURUSD','H4_EURUSD', 7, 17))
    r('H4_GBPUSD', run_h4('GBPUSD','H4_GBPUSD', 7, 17))
    r('H4_EURJPY', run_h4('EURJPY','H4_EURJPY', 7, 17))
    # H4_EURCHF removed (PF 1.00)

    if print_table: print("\n── Donchian 20-Day Breakout ─────────────────────────────────────")
    r('DCH_DAX',   run_donchian('DAX',   'DCH_DAX',    8, 17))
    r('DCH_NAS',   run_donchian('NAS100','DCH_NAS',   14, 21))
    # DCH_UK100 removed (PF 1.21) | DCH_GOLD removed (PF 1.03)

    if print_table: print("\n── Gold LSR ─────────────────────────────────────────────────────")
    r('LSR_GOLD',  run_lsr('GOLD', 'LSR_GOLD', 8, 20))

    all_pnls = []
    for res in results: all_pnls.extend(res['trades'])
    arr  = np.array(all_pnls, dtype=float)
    wins = arr[arr > 5]; loss = arr[arr < -5]
    n    = len(arr); days = 504
    avg_w = wins.mean() if len(wins) else 0
    avg_l = abs(loss.mean()) if len(loss) else 0
    return {
        'n': n, 'wr': len(wins)/n*100,
        'pf': wins.sum()/abs(loss.sum()) if len(loss) else 0,
        'mo': arr.sum()/days*21,
        'total': arr.sum(),
        'avg_w': avg_w, 'avg_l': avg_l,
        'results': results,
    }

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 65

    # ── Run clean v5.10 system ───────────────────────────────────────────────
    PARTIAL_R = None
    print("\n" + "="*W)
    print("  11botV3 v5.10 — Live Strategy Set (2-Year Backtest)")
    print("="*W)
    s1 = run_portfolio(print_table=True)

    strong = sorted([x for x in results if x['pf']>=1.5], key=lambda x:-x['pf'])
    weak   = [x for x in results if x['pf']<1.2]

    print("\n" + "="*W)
    print("  COMBINED PORTFOLIO SUMMARY")
    print("="*W)
    print(f"\n  Total trades:    {s1['n']}")
    print(f"  Win rate:        {s1['wr']:.1f}%")
    print(f"  Profit factor:   {s1['pf']:.2f}")
    print(f"  Avg win:         £{s1['avg_w']:,.0f}  |  Avg loss: £{s1['avg_l']:,.0f}"
          f"  |  Ratio: {s1['avg_w']/s1['avg_l']:.2f}R")
    print(f"  Monthly avg P&L: £{s1['mo']:,.0f}")
    print(f"  2-year total:    £{s1['total']:,.0f}")

    print(f"\n  ✅ STRONG (PF≥1.5):")
    for x in strong:
        print(f"     {x['name']:<18} PF {x['pf']:.2f}  £{x['mo']:,.0f}/mo")
    if weak:
        print(f"\n  ❌ WEAK (PF<1.2):")
        for x in weak:
            print(f"     {x['name']:<18} PF {x['pf']:.2f}  £{x['mo']:,.0f}/mo")
    print()
