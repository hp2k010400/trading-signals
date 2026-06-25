"""
honest_backtest.py  —  11botV3 Conservative Backtest (June 2026)

Three specific fixes vs backtest_system_combined.py:

  1. ENTRY PRICE — bar-close signals now enter at NEXT BAR OPEN.
     Affected: PDH, PWH, AMD, LSR, FVG, H4 EMA, Donchian, NG_H1.
     LB and ORB already use the breakout level (stop-order logic) — unchanged.

  2. COST_SCALE — run at 1.0× / 1.5× / 2.0× spread+slippage to bracket reality.
     LB fires at 07:00 London open when EUR/USD spread can be 1-2 pips, not 0.3.

  3. ALL STRATEGIES INCLUDED — no cherry-picking.
     PDH_UK100, PDH_NG, PWH_DAX, PWH_SP5, H4_EURCHF, DCH_UK100, DCH_GOLD all re-added.
     These were removed because they looked bad on backtested data — but that's exactly
     the selection bias problem.

  4. INSTRUMENT COOLDOWN — SL hit on instrument X → block X for rest of that day.
     Matches live EA behaviour added 2026-06-24 (InstBlocked / CheckSLHits).

  5. MAX_BARS increased: H4 EMA → 120 bars (5 days), Donchian → 240 bars (10 days).
     These are trend-following strategies; 48-bar cut-off was undershooting winners.

CAVEAT: Strategy selection bias is NOT eliminated. These 37 strategies were tuned
on the same 2-year dataset being evaluated. Walk-forward reduces but doesn't remove
this problem. Treat all figures as upper-bound estimates.

Run:
  pip install yfinance pandas numpy
  python honest_backtest.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
from dataclasses import dataclass
from collections import defaultdict

warnings.filterwarnings('ignore')

# ── Config ───────────────────────────────────────────────────────────────────
ACCOUNT    = 70_000
TRAIL_ORB  = 0.10
TRAIL_H4   = 0.15
TRAIL_DCH  = 0.20
COST_SCALE = 1.0    # overridden in main loop: 1.0 / 1.5 / 2.0
USE_COOLDOWN = True

# Walk-forward split
WF_SPLIT = pd.Timestamp('2025-01-01', tz='UTC')

RISKS = {
    'LB_EUR':0.004,  'LB_GBP':0.004,
    'DAX_ORB':0.0075,'NAS_ORB':0.0075,'SP5_ORB':0.004,'NG_ORB':0.0075,'NG_H1':0.0075,
    'PDH_DAX':0.005, 'PDH_UK100':0.005,'PDH_GBPJPY':0.004,
    'PDH_NAS':0.004, 'PDH_SP5':0.004,  'PDH_NG':0.004,
    'PWH_DAX':0.004, 'PWH_UK100':0.004,'PWH_NAS':0.003,'PWH_SP5':0.003,
    'AMD_EUR':0.004, 'AMD_GBP':0.004,  'AMD_NAS':0.004,
    'LSR_UK100':0.003,'LSR_NAS':0.003, 'LSR_EUR':0.003,'LSR_GOLD':0.003,
    'FVG_EUR':0.003,
    'H4_DAX':0.0075, 'H4_UK100':0.0075,'H4_EURCHF':0.0075,'H4_GBPJPY':0.0075,
    'H4_USDCHF':0.0075,'H4_EURUSD':0.0075,'H4_GBPUSD':0.0075,'H4_EURJPY':0.0075,
    'DCH_DAX':0.005, 'DCH_UK100':0.005,'DCH_NAS':0.0075,'DCH_GOLD':0.004,
}

# Base spread+slippage in R — scaled by COST_SCALE at runtime
COST_R_BASE = {
    'LB_EUR':0.08,  'LB_GBP':0.08,
    'DAX_ORB':0.07, 'NAS_ORB':0.06,'SP5_ORB':0.06,'NG_ORB':0.06,'NG_H1':0.05,
    'PDH_DAX':0.06, 'PDH_UK100':0.06,'PDH_GBPJPY':0.05,
    'PDH_NAS':0.05, 'PDH_SP5':0.05, 'PDH_NG':0.06,
    'PWH_DAX':0.06, 'PWH_UK100':0.06,'PWH_NAS':0.05,'PWH_SP5':0.05,
    'AMD_EUR':0.06, 'AMD_GBP':0.07, 'AMD_NAS':0.05,
    'LSR_UK100':0.05,'LSR_NAS':0.05,'LSR_EUR':0.05,'LSR_GOLD':0.05,
    'FVG_EUR':0.06,
    'H4_DAX':0.04,  'H4_UK100':0.04,'H4_EURCHF':0.05,'H4_GBPJPY':0.04,
    'H4_USDCHF':0.05,'H4_EURUSD':0.04,'H4_GBPUSD':0.04,'H4_EURJPY':0.04,
    'DCH_DAX':0.05, 'DCH_UK100':0.05,'DCH_NAS':0.05,'DCH_GOLD':0.05,
}

# Which underlying instrument each strategy trades (for cooldown logic)
INSTRUMENT = {
    'LB_EUR':'EURUSD',   'LB_GBP':'GBPUSD',
    'DAX_ORB':'DAX',     'NAS_ORB':'NAS100', 'SP5_ORB':'SP500',
    'NG_ORB':'NATGAS',   'NG_H1':'NATGAS',
    'PDH_DAX':'DAX',     'PDH_UK100':'UK100','PDH_GBPJPY':'GBPJPY',
    'PDH_NAS':'NAS100',  'PDH_SP5':'SP500',  'PDH_NG':'NATGAS',
    'PWH_DAX':'DAX',     'PWH_UK100':'UK100','PWH_NAS':'NAS100','PWH_SP5':'SP500',
    'AMD_EUR':'EURUSD',  'AMD_GBP':'GBPUSD', 'AMD_NAS':'NAS100',
    'LSR_UK100':'UK100', 'LSR_NAS':'NAS100', 'LSR_EUR':'EURUSD','LSR_GOLD':'GOLD',
    'FVG_EUR':'EURUSD',
    'H4_DAX':'DAX',      'H4_UK100':'UK100', 'H4_EURCHF':'EURCHF','H4_GBPJPY':'GBPJPY',
    'H4_USDCHF':'USDCHF','H4_EURUSD':'EURUSD','H4_GBPUSD':'GBPUSD','H4_EURJPY':'EURJPY',
    'DCH_DAX':'DAX',     'DCH_UK100':'UK100','DCH_NAS':'NAS100','DCH_GOLD':'GOLD',
}

# Approximate UTC fire hour (used to order trades within a day for cooldown)
FIRE_HOUR = {
    'LB_EUR':7,  'LB_GBP':7,
    'DAX_ORB':9, 'NAS_ORB':14,'SP5_ORB':14,'NG_ORB':14,'NG_H1':15,
    'PDH_DAX':8, 'PDH_UK100':8,'PDH_GBPJPY':7,'PDH_NAS':14,'PDH_SP5':14,'PDH_NG':14,
    'PWH_DAX':8, 'PWH_UK100':8,'PWH_NAS':14,'PWH_SP5':14,
    'AMD_EUR':7, 'AMD_GBP':7, 'AMD_NAS':14,
    'LSR_UK100':8,'LSR_NAS':14,'LSR_EUR':7,'LSR_GOLD':8,
    'FVG_EUR':7,
    'H4_DAX':8,  'H4_UK100':8,'H4_EURCHF':8,'H4_GBPJPY':0,
    'H4_USDCHF':8,'H4_EURUSD':7,'H4_GBPUSD':7,'H4_EURJPY':7,
    'DCH_DAX':8, 'DCH_UK100':8,'DCH_NAS':14,'DCH_GOLD':8,
}

YFSYMS = {
    'EURUSD':'EURUSD=X','GBPUSD':'GBPUSD=X',
    'DAX':'^GDAXI',     'NAS100':'NQ=F',
    'SP500':'ES=F',     'NATGAS':'NG=F',
    'UK100':'^FTSE',    'GBPJPY':'GBPJPY=X',
    'EURCHF':'EURCHF=X','USDCHF':'USDCHF=X',
    'EURJPY':'EURJPY=X','GOLD':'GC=F',
}

# ── Trade record ─────────────────────────────────────────────────────────────
@dataclass
class Trade:
    date: str        # 'YYYY-MM-DD'
    instrument: str  # e.g. 'EURUSD'
    pnl: float       # £ P&L after costs
    tag: str         # strategy name
    fire_hour: int   # approximate UTC entry hour (for cooldown ordering)

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
    Simulate on H1 bars. Trail activates only after 1R breakeven (matches live EA).
    Returns R ratio (before cost deduction).
    """
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0

    if trail_mult <= 0:
        bars = df.iloc[entry_pos+1 : entry_pos+1+max_bars]
        last_price = entry
        for _, b in bars.iterrows():
            last_price = b['close']
            if direction == 1 and b['low']  <= sl: return (sl   - entry) / sl_d
            if direction ==-1 and b['high'] >= sl: return (entry - sl)   / sl_d
        pts = (last_price - entry) if direction == 1 else (entry - last_price)
        return pts / sl_d

    trail   = sl_d * trail_mult
    cur_sl  = sl
    best    = entry
    be      = False
    bars    = df.iloc[entry_pos+1 : entry_pos+1+max_bars]
    last_price = entry

    for _, b in bars.iterrows():
        last_price = b['close']
        if direction == 1:
            if b['low'] <= cur_sl:
                return (cur_sl - entry) / sl_d
            best = max(best, b['high'])
            if not be and best >= entry + sl_d:
                be = True; cur_sl = entry
            if be:
                ns = best - trail
                if ns > cur_sl: cur_sl = ns
        else:
            if b['high'] >= cur_sl:
                return (entry - cur_sl) / sl_d
            best = min(best, b['low'])
            if not be and best <= entry - sl_d:
                be = True; cur_sl = entry
            if be:
                ns = best + trail
                if ns < cur_sl: cur_sl = ns

    pts = (last_price - entry) if direction == 1 else (entry - last_price)
    return pts / sl_d

def ipos(df, ts):
    arr = df.index.searchsorted(ts)
    if arr >= len(df): return -1
    return int(arr) if df.index[int(arr)] == ts else -1

def make_pnl(df, entry_pos, direction, entry, sl, trail_mult, risk_pct, max_bars=48):
    """Raw £ P&L before cost — costs applied at call site."""
    r = sim(df, entry_pos, direction, entry, sl, trail_mult, max_bars)
    return r * risk_pct * ACCOUNT

def make_trade(df, entry_pos, direction, entry, sl, trail_mult, risk_pct,
               tag, date_str, max_bars=48):
    """
    Build a Trade. Costs are NOT deducted here — applied in run_portfolio
    so COST_SCALE can be applied consistently.
    """
    pnl_raw = make_pnl(df, entry_pos, direction, entry, sl, trail_mult, risk_pct, max_bars)
    return Trade(
        date=date_str,
        instrument=INSTRUMENT.get(tag, '?'),
        pnl=pnl_raw,
        tag=tag,
        fire_hour=FIRE_HOUR.get(tag, 12),
    )

def apply_cost(trade, cost_r_base):
    """Return new Trade with spread+slippage cost deducted (scaled by COST_SCALE)."""
    cost_pnl = cost_r_base * COST_SCALE * RISKS.get(trade.tag, 0.004) * ACCOUNT
    return Trade(trade.date, trade.instrument,
                 trade.pnl - cost_pnl, trade.tag, trade.fire_hour)

# ── Instrument cooldown ───────────────────────────────────────────────────────
def apply_cooldown(trades):
    """
    Process trades in (date, fire_hour) order.
    If a trade hits SL (pnl < -£5), block that instrument for the rest of that day.
    """
    sorted_t = sorted(trades, key=lambda t: (t.date, t.fire_hour))
    blocked = defaultdict(set)   # instrument -> set of blocked dates
    active  = []
    removed = 0
    for t in sorted_t:
        if t.date in blocked[t.instrument]:
            removed += 1
            continue
        active.append(t)
        if t.pnl < -5.0:
            blocked[t.instrument].add(t.date)
    return active, removed

# ── 1-2. London Breakout ──────────────────────────────────────────────────────
def run_lb(key, tag, skip_dow=frozenset(), pip=0.0001):
    df = load_h1(key)
    if df is None: return []
    trades = []
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
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            # LB enters at the breakout level (stop order) — no close/open bias
            if b['high'] > a_hi:
                trades.append(make_trade(df,p,1, a_hi,a_lo-buf,TRAIL_ORB,RISKS[tag],tag,ds)); break
            if b['low']  < a_lo:
                trades.append(make_trade(df,p,-1,a_lo,a_hi+buf,TRAIL_ORB,RISKS[tag],tag,ds)); break
    return trades

# ── 3-6. ORB ─────────────────────────────────────────────────────────────────
def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None: return []
    trades = []
    dates  = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb = df[df.index == day+pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi-rlo <= rmax): continue
        edf = df[(df.index >= day+pd.Timedelta(hours=es)) &
                 (df.index <  day+pd.Timedelta(hours=ee))]
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            # ORB enters at the range level (stop order) — no close/open bias
            if b['high'] > rhi:
                trades.append(make_trade(df,p,1, rhi,rlo,TRAIL_ORB,RISKS[tag],tag,ds)); break
            if b['low']  < rlo:
                trades.append(make_trade(df,p,-1,rlo,rhi,TRAIL_ORB,RISKS[tag],tag,ds)); break
    return trades

# ── 7. NatGas H1 EMA ─────────────────────────────────────────────────────────
def run_ng_h1(tag):
    df = load_h1('NATGAS')
    if df is None: return []
    ema10 = df['close'].ewm(span=10,adjust=False).mean()
    ema20 = df['close'].ewm(span=20,adjust=False).mean()
    atr   = calc_atr(df, 14)
    adx   = calc_adx(df, 14)
    trades = []; fired_days = set()
    for i in range(21, len(df)-50):
        ts = df.index[i]
        if ts.hour < 14 or ts.hour >= 21: continue
        day = ts.normalize().date()
        if day in fired_days: continue
        if adx.iloc[i] < 20: continue
        bull = ema10.iloc[i]>ema20.iloc[i] and ema10.iloc[i-1]<=ema20.iloc[i-1]
        bear = ema10.iloc[i]<ema20.iloc[i] and ema10.iloc[i-1]>=ema20.iloc[i-1]
        if not bull and not bear: continue
        # FIX: enter at next bar open, not current bar close
        if i+1 >= len(df): continue
        a = atr.iloc[i]
        entry = df.iloc[i+1]['open']
        ds = str(day)
        if bull:
            trades.append(make_trade(df,i+1,1,  entry,entry-1.5*a,TRAIL_ORB,RISKS[tag],tag,ds))
        else:
            trades.append(make_trade(df,i+1,-1, entry,entry+1.5*a,TRAIL_ORB,RISKS[tag],tag,ds))
        fired_days.add(day)
    return trades

# ── 8-13. PDH breakout ────────────────────────────────────────────────────────
def run_pdh(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df, 14); trades = []
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
        a_series = atr.reindex(edf.index, method='ffill')
        rng = pdh - pdl
        if len(a_series)==0 or a_series.iloc[0]<=0: continue
        if not (a_series.iloc[0]*0.4 <= rng <= a_series.iloc[0]*4.0): continue
        buf = a_series.iloc[0] * 0.05
        ds = str(date)
        for j in range(len(edf)-1):   # -1: need j+1 to exist
            b = edf.iloc[j]; av = a_series.iloc[min(j, len(a_series)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or p+1 >= len(df) or av <= 0: continue
            # FIX: enter at next bar open
            if b['high'] > pdh+buf:
                entry = df.iloc[p+1]['open']
                trades.append(make_trade(df,p+1,1, entry,entry-1.5*av,TRAIL_ORB,RISKS[tag],tag,ds)); break
            if b['low']  < pdl-buf:
                entry = df.iloc[p+1]['open']
                trades.append(make_trade(df,p+1,-1,entry,entry+1.5*av,TRAIL_ORB,RISKS[tag],tag,ds)); break
    return trades

# ── 14-17. PWH breakout ───────────────────────────────────────────────────────
def run_pwh(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df, 14); trades = []
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        dow = day.dayofweek
        ws  = day - pd.Timedelta(days=dow+7)
        we  = day - pd.Timedelta(days=dow)
        pw  = df[(df.index >= ws) & (df.index < we)]
        if len(pw) < 20: continue
        pwh = pw['high'].max(); pwl = pw['low'].min()
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        if len(edf) == 0: continue
        a_series = atr.reindex(edf.index, method='ffill')
        rng = pwh - pwl
        if len(a_series)==0 or a_series.iloc[0]<=0: continue
        if not (0.5*a_series.iloc[0] <= rng <= 8.0*a_series.iloc[0]): continue
        buf = a_series.iloc[0] * 0.05
        ds = str(date)
        for j in range(len(edf)-1):
            b = edf.iloc[j]; av = a_series.iloc[min(j, len(a_series)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or p+1 >= len(df) or av <= 0: continue
            # FIX: enter at next bar open
            if b['high'] > pwh+buf:
                entry = df.iloc[p+1]['open']
                trades.append(make_trade(df,p+1,1, entry,entry-1.5*av,TRAIL_ORB,RISKS[tag],tag,ds)); break
            if b['low']  < pwl-buf:
                entry = df.iloc[p+1]['open']
                trades.append(make_trade(df,p+1,-1,entry,entry+1.5*av,TRAIL_ORB,RISKS[tag],tag,ds)); break
    return trades

# ── 18-20. AMD manipulation reversal ─────────────────────────────────────────
def run_amd(key, tag, hs, he, asian_hrs=(22,7)):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df, 14); trades = []
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if asian_hrs[0] > asian_hrs[1]:
            rdf = df[(df.index >= prev+pd.Timedelta(hours=asian_hrs[0])) &
                     (df.index <  day +pd.Timedelta(hours=asian_hrs[1]))]
        else:
            rdf = df[(df.index >= day+pd.Timedelta(hours=asian_hrs[0])) &
                     (df.index <  day+pd.Timedelta(hours=asian_hrs[1]))]
        if len(rdf) < 3: continue
        a_hi = rdf['high'].max(); a_lo = rdf['low'].min(); rng = a_hi - a_lo
        if rng <= 0: continue
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        a_s = atr.reindex(edf.index, method='ffill')
        fired = False; ds = str(date)
        for j in range(len(edf)-1):
            if fired: break
            b = edf.iloc[j]; av = a_s.iloc[min(j, len(a_s)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or p+1 >= len(df) or av <= 0: continue
            # AMD: spike+close back below level — enter at next bar open
            if b['high']>a_hi and b['close']<a_hi and (b['high']-a_hi)<rng*0.6:
                entry = df.iloc[p+1]['open']
                sl_px = b['high'] + av*0.1
                if sl_px > entry:  # valid sell: SL above entry
                    trades.append(make_trade(df,p+1,-1,entry,sl_px,TRAIL_ORB,RISKS[tag],tag,ds))
                    fired=True
            elif b['low']<a_lo and b['close']>a_lo and (a_lo-b['low'])<rng*0.6:
                entry = df.iloc[p+1]['open']
                sl_px = b['low'] - av*0.1
                if sl_px < entry:  # valid buy: SL below entry
                    trades.append(make_trade(df,p+1,1, entry,sl_px,TRAIL_ORB,RISKS[tag],tag,ds))
                    fired=True
    return trades

# ── 21-23. Liquidity sweep reversal ──────────────────────────────────────────
def run_lsr(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df, 14); trades = []
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
        fired = False; ds = str(date)
        for j in range(len(edf)-1):
            if fired: break
            b = edf.iloc[j]; av = a_s.iloc[min(j, len(a_s)-1)]
            p = ipos(df, edf.index[j])
            if p < 0 or p+1 >= len(df) or av <= 0: continue
            # LSR: sweep+close back — enter at next bar open
            if b['high']>pdh and b['close']<pdh and (b['high']-pdh)<0.6*av:
                entry = df.iloc[p+1]['open']
                sl_px = b['high'] + av*0.1
                if sl_px > entry:
                    trades.append(make_trade(df,p+1,-1,entry,sl_px,TRAIL_ORB,RISKS[tag],tag,ds))
                    fired=True
            elif b['low']<pdl and b['close']>pdl and (pdl-b['low'])<0.6*av:
                entry = df.iloc[p+1]['open']
                sl_px = b['low'] - av*0.1
                if sl_px < entry:
                    trades.append(make_trade(df,p+1,1, entry,sl_px,TRAIL_ORB,RISKS[tag],tag,ds))
                    fired=True
    return trades

# ── 24. Fair Value Gap ────────────────────────────────────────────────────────
def run_fvg(key, tag, hs, he):
    df = load_h1(key)
    if df is None: return []
    atr = calc_atr(df, 14); trades = []
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day = pd.Timestamp(date, tz='UTC')
        edf = df[(df.index >= day+pd.Timedelta(hours=hs)) &
                 (df.index <  day+pd.Timedelta(hours=he))]
        fired = False; ds = str(date)
        for j in range(len(edf)-1):
            if fired: break
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0 or p+1 >= len(df): continue
            av = atr.iloc[min(p, len(atr)-1)]
            if av <= 0: continue
            lb = df.iloc[max(0,p-24):p]
            for k in range(2, len(lb)):
                gap_bull = lb.iloc[k]['low']  - lb.iloc[k-2]['high']
                gap_bear = lb.iloc[k-2]['low'] - lb.iloc[k]['high']
                if gap_bull > av*0.15:
                    lo_z=lb.iloc[k-2]['high']; hi_z=lb.iloc[k]['low']
                    if lo_z <= b['close'] <= hi_z:
                        entry = df.iloc[p+1]['open']
                        sl_px = lo_z - 0.5*av
                        if sl_px < entry:
                            trades.append(make_trade(df,p+1,1, entry,sl_px,TRAIL_ORB,RISKS[tag],tag,ds))
                            fired=True; break
                if gap_bear > av*0.15:
                    lo_z=lb.iloc[k]['high']; hi_z=lb.iloc[k-2]['low']
                    if lo_z <= b['close'] <= hi_z:
                        entry = df.iloc[p+1]['open']
                        sl_px = hi_z + 0.5*av
                        if sl_px > entry:
                            trades.append(make_trade(df,p+1,-1,entry,sl_px,TRAIL_ORB,RISKS[tag],tag,ds))
                            fired=True; break
    return trades

# ── 25-32. H4 EMA trend ───────────────────────────────────────────────────────
def run_h4(key, tag, hs, he):
    df4 = load_h4(key); df1 = load_h1(key)
    if df4 is None or df1 is None: return []
    ema10 = df4['close'].ewm(span=10,adjust=False).mean()
    ema20 = df4['close'].ewm(span=20,adjust=False).mean()
    atr4  = calc_atr(df4, 14)
    adx4  = calc_adx(df4, 14)
    trades = []
    for i in range(2, len(df4)-1):
        if adx4.iloc[i] < 25: continue
        a4 = atr4.iloc[i]
        if a4 <= 0: continue
        bull = ema10.iloc[i]>ema20.iloc[i] and ema10.iloc[i-1]<=ema20.iloc[i-1]
        bear = ema10.iloc[i]<ema20.iloc[i] and ema10.iloc[i-1]>=ema20.iloc[i-1]
        if not bull and not bear: continue
        sig_time = df4.index[i]
        day  = sig_time.normalize()
        sess_s = day + pd.Timedelta(hours=hs)
        sess_e = day + pd.Timedelta(hours=he)
        if sig_time > sess_e: continue
        start = max(sig_time, sess_s)
        edf = df1[(df1.index >= start) & (df1.index < sess_e)]
        if len(edf) == 0: continue
        # FIX: enter at next H1 bar open after signal bar
        b = edf.iloc[0]; p = ipos(df1, edf.index[0])
        if p < 0 or p+1 >= len(df1): continue
        entry = df1.iloc[p+1]['open']
        ds = str(day.date())
        if bull:
            trades.append(make_trade(df1,p+1,1, entry,entry-1.5*a4,TRAIL_H4,RISKS[tag],tag,ds,max_bars=120))
        else:
            trades.append(make_trade(df1,p+1,-1,entry,entry+1.5*a4,TRAIL_H4,RISKS[tag],tag,ds,max_bars=120))
    return trades

# ── 33-36. Donchian 20-day breakout ──────────────────────────────────────────
def run_donchian(key, tag, hs, he):
    df1 = load_h1(key); df4 = load_h4(key); dfd = load_d1(key)
    if df1 is None or df4 is None or dfd is None: return []
    adx4 = calc_adx(df4, 14); atr1 = calc_atr(df1, 14)
    trades = []; fired_days = set()
    dates  = sorted(set(df1.index.normalize().date))
    for date in dates:
        if date in fired_days: continue
        day = pd.Timestamp(date, tz='UTC')
        d_slice = dfd[dfd.index < day].tail(20)
        if len(d_slice) < 20: continue
        d20hi = d_slice['high'].max(); d20lo = d_slice['low'].min()
        h4_at = adx4[adx4.index <= day + pd.Timedelta(hours=hs)]
        if len(h4_at)==0 or h4_at.iloc[-1] < 25: continue
        edf = df1[(df1.index >= day+pd.Timedelta(hours=hs)) &
                  (df1.index <  day+pd.Timedelta(hours=he))]
        if len(edf) == 0: continue
        ds = str(date)
        for j in range(len(edf)-1):
            b = edf.iloc[j]; p = ipos(df1, edf.index[j])
            if p < 0 or p+1 >= len(df1): continue
            av = atr1.iloc[min(p, len(atr1)-1)]
            if av <= 0: continue
            # FIX: enter at next bar open
            if b['high'] > d20hi:
                entry = df1.iloc[p+1]['open']
                trades.append(make_trade(df1,p+1,1, entry,entry-2.0*av,TRAIL_DCH,RISKS[tag],tag,ds,max_bars=240))
                fired_days.add(date); break
            elif b['low'] < d20lo:
                entry = df1.iloc[p+1]['open']
                trades.append(make_trade(df1,p+1,-1,entry,entry+2.0*av,TRAIL_DCH,RISKS[tag],tag,ds,max_bars=240))
                fired_days.add(date); break
    return trades

# ── 37. Gold LSR ──────────────────────────────────────────────────────────────
def run_lsr_gold():
    return run_lsr('GOLD', 'LSR_GOLD', 8, 20)

# ── Raw trade cache (strategies run ONCE, then filtered per scenario) ─────────
_RAW_CACHE = None

def get_all_raw_trades():
    """Run all 37 strategies once and cache the results. ~5-10 min on Codespace."""
    global _RAW_CACHE
    if _RAW_CACHE is not None:
        return _RAW_CACHE

    raw = []
    strats = [
        ('LB_EUR',     lambda: run_lb('EURUSD','LB_EUR',  skip_dow={1})),
        ('LB_GBP',     lambda: run_lb('GBPUSD','LB_GBP',  skip_dow={1})),
        ('DAX_ORB',    lambda: run_orb('DAX',   'DAX_ORB',  8,9,12, 30,  300, set())),
        ('NAS_ORB',    lambda: run_orb('NAS100','NAS_ORB', 13,14,16, 50, 1500, {0})),
        ('SP5_ORB',    lambda: run_orb('SP500', 'SP5_ORB', 13,14,16,  5,  300, {0})),
        ('NG_ORB',     lambda: run_orb('NATGAS','NG_ORB',  13,14,16,0.03,1.0, set())),
        ('NG_H1',      lambda: run_ng_h1('NG_H1')),
        ('PDH_DAX',    lambda: run_pdh('DAX',   'PDH_DAX',    8,17)),
        ('PDH_UK100',  lambda: run_pdh('UK100', 'PDH_UK100',  8,17)),
        ('PDH_GBPJPY', lambda: run_pdh('GBPJPY','PDH_GBPJPY', 7,17)),
        ('PDH_NAS',    lambda: run_pdh('NAS100','PDH_NAS',   14,21)),
        ('PDH_SP5',    lambda: run_pdh('SP500', 'PDH_SP5',   14,21)),
        ('PDH_NG',     lambda: run_pdh('NATGAS','PDH_NG',    14,21)),
        ('PWH_DAX',    lambda: run_pwh('DAX',   'PWH_DAX',    8,17)),
        ('PWH_UK100',  lambda: run_pwh('UK100', 'PWH_UK100',  8,17)),
        ('PWH_NAS',    lambda: run_pwh('NAS100','PWH_NAS',   14,21)),
        ('PWH_SP5',    lambda: run_pwh('SP500', 'PWH_SP5',   14,21)),
        ('AMD_EUR',    lambda: run_amd('EURUSD','AMD_EUR',  7, 9)),
        ('AMD_GBP',    lambda: run_amd('GBPUSD','AMD_GBP',  7, 9)),
        ('AMD_NAS',    lambda: run_amd('NAS100','AMD_NAS', 14,16, asian_hrs=(12,14))),
        ('LSR_UK100',  lambda: run_lsr('UK100', 'LSR_UK100', 8,17)),
        ('LSR_NAS',    lambda: run_lsr('NAS100','LSR_NAS',  14,21)),
        ('LSR_EUR',    lambda: run_lsr('EURUSD','LSR_EUR',   7,17)),
        ('FVG_EUR',    lambda: run_fvg('EURUSD','FVG_EUR',   7,17)),
        ('H4_DAX',     lambda: run_h4('DAX',   'H4_DAX',    8,16)),
        ('H4_UK100',   lambda: run_h4('UK100', 'H4_UK100',  8,16)),
        ('H4_EURCHF',  lambda: run_h4('EURCHF','H4_EURCHF', 8,17)),
        ('H4_GBPJPY',  lambda: run_h4('GBPJPY','H4_GBPJPY', 0,21)),
        ('H4_USDCHF',  lambda: run_h4('USDCHF','H4_USDCHF', 8,17)),
        ('H4_EURUSD',  lambda: run_h4('EURUSD','H4_EURUSD', 7,17)),
        ('H4_GBPUSD',  lambda: run_h4('GBPUSD','H4_GBPUSD', 7,17)),
        ('H4_EURJPY',  lambda: run_h4('EURJPY','H4_EURJPY', 7,17)),
        ('DCH_DAX',    lambda: run_donchian('DAX',   'DCH_DAX',    8,17)),
        ('DCH_UK100',  lambda: run_donchian('UK100', 'DCH_UK100',  8,17)),
        ('DCH_NAS',    lambda: run_donchian('NAS100','DCH_NAS',   14,21)),
        ('DCH_GOLD',   lambda: run_donchian('GOLD',  'DCH_GOLD',   8,20)),
        ('LSR_GOLD',   lambda: run_lsr_gold()),
    ]

    total = len(strats)
    for i, (tag, fn) in enumerate(strats):
        print(f"  [{i+1:>2}/{total}] Running {tag}...", end='\r')
        raw.extend(fn())
    print(f"  All strategies done — {len(raw):,} raw trades total.          ")

    _RAW_CACHE = raw
    return raw

# ── Portfolio runner ──────────────────────────────────────────────────────────
def run_portfolio(date_from=None, date_to=None):
    """
    Filter raw trades by date range, apply COST_SCALE and optional cooldown.
    Strategies are only computed once (cached in _RAW_CACHE).
    """
    all_raw = get_all_raw_trades()

    d_from = str(date_from.date()) if date_from else None
    d_to   = str(date_to.date())   if date_to   else None

    filtered = [
        t for t in all_raw
        if (d_from is None or t.date >= d_from)
        and (d_to   is None or t.date <  d_to)
    ]

    # Apply cost scaling
    costed = [apply_cost(t, COST_R_BASE.get(t.tag, 0.05)) for t in filtered]

    # Apply instrument cooldown
    cooldown_removed = 0
    if USE_COOLDOWN:
        costed, cooldown_removed = apply_cooldown(costed)

    if not costed:
        return None

    arr  = np.array([t.pnl for t in costed], dtype=float)
    wins = arr[arr >  5]; loss = arr[arr < -5]
    n    = len(arr)
    days = max((pd.Timestamp(max(t.date for t in costed)) -
                pd.Timestamp(min(t.date for t in costed))).days, 1)
    tpm  = n / days * 21
    mo   = arr.sum() / days * 21
    pf   = wins.sum() / abs(loss.sum()) if len(loss) else 0.0
    wr   = len(wins) / n * 100 if n else 0.0

    return {
        'n': n, 'wr': round(wr,1), 'pf': round(pf,2),
        'mo': round(mo,0), 'total': round(arr.sum(),0),
        'avg_w': round(wins.mean(),0) if len(wins) else 0,
        'avg_l': round(abs(loss.mean()),0) if len(loss) else 0,
        'tpm': round(tpm,1),
        'cooldown_removed': cooldown_removed,
        'trades': costed,
    }

# ── Per-strategy breakdown ────────────────────────────────────────────────────
def strategy_table(trades_list, date_from=None, date_to=None):
    """Print per-strategy P&L table from the full trade list."""
    from collections import defaultdict
    by_tag = defaultdict(list)
    for t in trades_list:
        if date_from and t.date < str(date_from.date()): continue
        if date_to   and t.date >= str(date_to.date()):  continue
        by_tag[t.tag].append(t.pnl)

    rows = []
    for tag in sorted(by_tag.keys()):
        arr  = np.array(by_tag[tag])
        wins = arr[arr > 5]; loss = arr[arr < -5]
        if len(arr) < 5: continue
        days = 504
        pf   = wins.sum()/abs(loss.sum()) if len(loss) else 0.0
        mo   = arr.sum()/days*21
        wr   = len(wins)/len(arr)*100
        tag2 = '✅' if pf>=1.5 else ('⚠ ' if pf>=1.2 else '❌')
        rows.append((tag, len(arr), wr, pf, mo, tag2))

    print(f"\n  {'Strategy':<18} {'Tr':>4}  {'WR%':>5}  {'PF':>5}  {'£/mo':>7}  OK")
    print("  " + "─"*52)
    for tag, n, wr, pf, mo, ok in sorted(rows, key=lambda x: -x[3]):
        print(f"  {tag:<18} {n:>4}  {wr:>5.1f}%  {pf:>5.2f}  £{mo:>6,.0f}  {ok}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 72

    print("\nRunning all 37 strategies (strategies cached after first run)...")
    print("Expected: ~5-10 min on Codespace first time, instant on re-runs.\n")

    cost_scales = [1.0, 1.5, 2.0]
    labels      = ['1.0× (optimistic)', '1.5× (realistic)', '2.0× (conservative)']

    # ── Full 2-year results ───────────────────────────────────────────────────
    print("=" * W)
    print("  11botV3 HONEST BACKTEST  —  37 strategies, next-bar-open entry")
    print("=" * W)
    print(f"\n  {'Scenario':<22}  {'Trades':>6}  {'T/mo':>5}  {'WR%':>5}  "
          f"{'PF':>5}  {'Avg W':>7}  {'Avg L':>7}  {'£/mo':>8}  {'Cooldown':>9}")
    print("  " + "─"*(W-2))

    full_results = {}
    for scale, label in zip(cost_scales, labels):
        COST_SCALE = scale
        s = run_portfolio()
        full_results[scale] = s
        if s:
            print(f"  {label:<22}  {s['n']:>6,}  {s['tpm']:>5.1f}  {s['wr']:>5.1f}%  "
                  f"{s['pf']:>5.2f}  £{s['avg_w']:>6,}  £{s['avg_l']:>6,}  "
                  f"£{s['mo']:>7,}  -{s['cooldown_removed']:>4} trades")

    # Per-strategy breakdown at 1.5× (realistic)
    COST_SCALE = 1.5
    s15 = run_portfolio()
    if s15:
        print(f"\n  Strategy breakdown at 1.5× costs:")
        strategy_table(s15['trades'])

    # ── Walk-forward validation ───────────────────────────────────────────────
    print("\n" + "=" * W)
    print("  WALK-FORWARD VALIDATION  (split: Jan 2025)")
    print("  IS = ~18 months of data   |   OOS = last ~6 months")
    print("=" * W)

    header = f"\n  {'Metric':<22}"
    for label in ['1.0× optimistic', '1.5× realistic', '2.0× conservative']:
        header += f"  {label:>18}"
    print(header)
    print("  " + "─"*(W-2))

    wf = {}
    for scale in cost_scales:
        COST_SCALE = scale
        si = run_portfolio(date_to=WF_SPLIT)
        so = run_portfolio(date_from=WF_SPLIT)
        wf[scale] = (si, so)

    def wf_row(label, fn):
        row = f"  {label:<22}"
        for scale in cost_scales:
            si, so = wf[scale]
            row += f"  {fn(si, so):>18}"
        print(row)

    print(f"\n  {'--- IN-SAMPLE (IS) ---':<22}")
    wf_row('  Trades',     lambda i,o: f"{i['n']:,}"   if i else 'n/a')
    wf_row('  Win Rate',   lambda i,o: f"{i['wr']:.1f}%"  if i else 'n/a')
    wf_row('  Prof Factor',lambda i,o: f"{i['pf']:.2f}"  if i else 'n/a')
    wf_row('  Avg Win',    lambda i,o: f"£{i['avg_w']:,}" if i else 'n/a')
    wf_row('  £/month',    lambda i,o: f"£{i['mo']:,}"   if i else 'n/a')

    print(f"\n  {'--- OUT-OF-SAMPLE (OOS) ---':<22}")
    wf_row('  Trades',     lambda i,o: f"{o['n']:,}"   if o else 'n/a')
    wf_row('  Win Rate',   lambda i,o: f"{o['wr']:.1f}%"  if o else 'n/a')
    wf_row('  Prof Factor',lambda i,o: f"{o['pf']:.2f}"  if o else 'n/a')
    wf_row('  Avg Win',    lambda i,o: f"£{o['avg_w']:,}" if o else 'n/a')
    wf_row('  £/month',    lambda i,o: f"£{o['mo']:,}"   if o else 'n/a')

    print(f"\n  {'OOS/IS PF ratio':<22}", end='')
    for scale in cost_scales:
        si, so = wf[scale]
        if si and so and si['pf'] > 0:
            ratio = so['pf'] / si['pf'] * 100
            verdict = '✅' if ratio >= 80 else ('⚠ ' if ratio >= 60 else '❌')
            print(f"  {ratio:>15.0f}%  {verdict}", end='')
        else:
            print(f"  {'n/a':>18}", end='')
    print()

    # ── Honest summary ────────────────────────────────────────────────────────
    print("\n" + "=" * W)
    print("  HONEST SUMMARY")
    print("=" * W)
    orig_mo = 20000   # claimed figure from previous backtest

    s10 = full_results.get(1.0)
    s15f = full_results.get(1.5)
    s20 = full_results.get(2.0)

    print(f"""
  Original backtest claim:    £{orig_mo:,}/month
  This backtest (1.0× costs): £{s10['mo']:,}/month  (next-bar entry + all strategies)
  Realistic (1.5× costs):     £{s15f['mo']:,}/month
  Conservative (2.0× costs):  £{s20['mo']:,}/month

  With instrument cooldown enabled: {USE_COOLDOWN}
  Cooldown removed (at 1.5×): {s15f['cooldown_removed']} trades/2yr

  CAVEATS:
  1. Strategy selection bias — strategies were picked from the same 2yr dataset.
     Even the OOS period above is partially contaminated by this.
  2. H/L ordering within H1 bars not simulated — minor ±noise.
  3. No overnight swap costs for H4/Donchian holds — likely -5 to -10% on those.
  4. yfinance futures (NQ=F, ES=F) ≠ exact broker CFD prices — minor spread diff.

  BOTTOM LINE:
  If OOS PF ≥ 1.3 at 1.5× costs, there is probably a real edge.
  If OOS PF < 1.2 at 1.5× costs, the system needs rethinking before FTMO.
""")
