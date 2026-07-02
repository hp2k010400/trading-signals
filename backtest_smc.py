"""
backtest_smc.py  —  Smart Money Concepts (SMC)
===============================================
Two ICT / Smart Money patterns:

1. FAIR VALUE GAP (FVG)
   3-bar imbalance: strong impulse candle leaves a price gap.
   Bullish FVG: bar[i-2].high < bar[i].low  →  price returns to gap  →  BUY
   Bearish FVG: bar[i-2].low  > bar[i].high →  price returns to gap  →  SELL
   SL: 0.5 ATR beyond the gap boundary. Max gap age: 16 bars.
   Instruments: GER40, US100, SP500, EURUSD, GBPUSD

2. AMD MANIPULATION REVERSAL (ICT: Accumulation→Manipulation→Distribution)
   Asian range (00:00-07:00 UTC) = accumulation.
   London open (07:00-09:00 UTC) sweeps Asian high or low (stop hunt).
   If candle closes BACK INSIDE the Asian range = manipulation complete.
   Enter OPPOSITE to the sweep. Institutions grabbed retail stops; real move begins.
   SL: extreme of the manipulation wick + buffer.
   Instruments: EURUSD, GBPUSD, GER40

Both: 0.50% risk | 0.10R trail after 1R | 8-year MT5 H1 CSV data

Compares against main 10kbotV3 portfolio and shows combined stats.
Run: python backtest_smc.py
"""
import pandas as pd
import numpy as np
import os
import warnings
from collections import defaultdict
warnings.filterwarnings('ignore')

ACCOUNT    = 70_000
COST_SCALE = 1.5
TRAIL      = 0.10
RISK       = 0.005
COST_FVG   = 0.07
COST_AMD   = 0.08

CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv', 'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv', 'UK100':  'UK100_cash_H1.csv',
    'GOLD':   'XAUUSD_H1.csv',
}

_cache = {}
def load_h1(key):
    if key in _cache: return _cache[key]
    fname = CSVSYMS.get(key)
    if not fname or not os.path.exists(fname): _cache[key] = None; return None
    df = pd.read_csv(fname)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    _cache[key] = df.dropna() if len(df) > 200 else None
    return _cache[key]

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    return int(a) if a < len(df) and df.index[int(a)] == ts else -1

def sim_trade(df, ep, direction, entry, sl, max_bars=48):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    trail = sl_d * TRAIL; cur_sl = sl; best = entry; be = False
    for _, b in df.iloc[ep+1: ep+1+max_bars].iterrows():
        if direction == 1:
            if b['low'] <= cur_sl: return (cur_sl - entry) / sl_d
            best = max(best, b['high'])
            if not be and best >= entry + sl_d: be = True; cur_sl = entry
            if be:
                ns = best - trail
                if ns > cur_sl: cur_sl = ns
        else:
            if b['high'] >= cur_sl: return (entry - cur_sl) / sl_d
            best = min(best, b['low'])
            if not be and best <= entry - sl_d: be = True; cur_sl = entry
            if be:
                ns = best + trail
                if ns < cur_sl: cur_sl = ns
    lp = df.iloc[min(ep+max_bars, len(df)-1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def pnl_net(r, cost): return (r - cost * COST_SCALE) * RISK * ACCOUNT

def stats_from(trades):
    if len(trades) < 10: return None
    arr  = np.array([t['pnl'] for t in trades])
    wins = arr[arr >  5]; loss = arr[arr < -5]
    dates = sorted(set(t['date'] for t in trades))
    span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    return {
        'n': len(arr), 'arr': arr,
        'wr':  round(len(wins)/len(arr)*100, 1),
        'pf':  round(wins.sum()/abs(loss.sum()), 2) if len(loss) and loss.sum() != 0 else 0.0,
        'mo':  round(arr.sum()/span*21, 0),
        'aw':  round(wins.mean()) if len(wins) else 0,
        'al':  round(abs(loss.mean())) if len(loss) else 0,
        'tpm': round(len(arr)/span*21, 1),
    }

def max_dd(trades):
    arr = np.array([t['pnl'] for t in sorted(trades, key=lambda x: x['date'])])
    eq  = ACCOUNT + np.cumsum(arr); pk = np.maximum.accumulate(eq)
    return round((pk-eq).max(), 0), round((pk-eq).max()/ACCOUNT*100, 2)

def monthly_map(trades):
    m = defaultdict(float)
    for t in trades: m[t['date'][:7]] += t['pnl']
    return m

# ── 1. FAIR VALUE GAP ─────────────────────────────────────────────────────────
FVG_CONFIGS = [
    ('DAX',   'FVG_DAX',  8, 17, 0.15),
    ('NAS100','FVG_NAS', 14, 21, 0.15),
    ('SP500', 'FVG_SP5', 14, 21, 0.15),
    ('EURUSD','FVG_EUR',  7, 17, 0.15),
    ('GBPUSD','FVG_GBP',  7, 17, 0.15),
]

def run_fvg(key, tag, s_start, s_end, min_gap_atr=0.15, max_age=16):
    df = load_h1(key)
    if df is None: return []
    trades = []; open_fvgs = []; fired = set()
    hi = df['high']; lo = df['low']; cl = df['close']
    tr = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(com=13, adjust=False).mean()

    for i in range(3, len(df)):
        bar = df.iloc[i]
        if bar.name.dayofweek >= 5: continue
        atr = bar['atr14']
        if atr <= 0: continue
        b0, b2 = df.iloc[i-2], df.iloc[i]

        # Detect new FVGs
        gap_bull = b2['low'] - b0['high']
        if gap_bull > min_gap_atr * atr:
            open_fvgs.append({'t':'bull','hi':b2['low'],'lo':b0['high'],'age':0})
        gap_bear = b0['low'] - b2['high']
        if gap_bear > min_gap_atr * atr:
            open_fvgs.append({'t':'bear','hi':b0['low'],'lo':b2['high'],'age':0})

        for f in open_fvgs: f['age'] += 1
        open_fvgs = [f for f in open_fvgs if f['age'] <= max_age]

        h = bar.name.hour
        if not (s_start <= h < s_end): continue
        date_key = bar.name.date()
        if date_key in fired: continue

        for f in list(open_fvgs):
            if f['age'] < 2: continue
            direction = entry = sl = None
            if f['t'] == 'bull':
                # Price retraces into bullish gap → buy
                if bar['low'] <= f['hi'] and bar['close'] >= f['lo']:
                    direction = 1; entry = bar['close']; sl = f['lo'] - 0.5*atr
            else:
                # Price retraces into bearish gap → sell
                if bar['high'] >= f['lo'] and bar['close'] <= f['hi']:
                    direction = -1; entry = bar['close']; sl = f['hi'] + 0.5*atr
            if direction is None or abs(entry-sl) <= 0: continue
            p = ipos(df, bar.name)
            if p < 0: continue
            day = pd.Timestamp(bar.name.date(), tz='UTC')
            r = sim_trade(df, p, direction, entry, sl,
                          max_bars=int((s_end - h) * 1))
            trades.append({'pnl': pnl_net(r, COST_FVG), 'date': str(date_key), 'tag': tag, 'r': r})
            open_fvgs.remove(f); fired.add(date_key); break

    return trades

# ── 2. AMD MANIPULATION REVERSAL ──────────────────────────────────────────────
AMD_CONFIGS = [
    ('EURUSD', 'AMD_EUR', 0.0001),
    ('GBPUSD', 'AMD_GBP', 0.0001),
    ('DAX',    'AMD_DAX', None),
]

def run_amd(key, tag, pip):
    df = load_h1(key)
    if df is None: return []
    hi = df['high']; lo = df['low']; cl = df['close']
    tr = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(com=13, adjust=False).mean()
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if day.dayofweek >= 5 or day.dayofweek == 0: continue  # skip Mon (gap risk)
        # Asian range: previous 22:00 → today 07:00
        ab = df[(df.index >= prev+pd.Timedelta(hours=22)) &
                (df.index <  day+pd.Timedelta(hours=7))]
        if len(ab) < 3: continue
        ah = ab['high'].max(); al = ab['low'].min(); rng = ah - al
        if pip and rng / pip < 8: continue   # range too small
        atr_row = df[df.index < day]
        if len(atr_row) == 0: continue
        atr = atr_row['atr14'].iloc[-1]
        if atr <= 0: continue
        # Manipulation window: 07:00-09:00 UTC
        lb = df[(df.index >= day+pd.Timedelta(hours=7)) &
                (df.index <  day+pd.Timedelta(hours=9))]
        direction = entry = sl = et = None
        for bt, b in lb.iterrows():
            sweep_up   = b['high'] > ah and b['close'] < ah and (b['high']-ah) < rng*0.6
            sweep_down = b['low']  < al and b['close'] > al and (al-b['low'])  < rng*0.6
            if sweep_up:
                direction = -1; entry = b['close']; sl = b['high'] + atr*0.1; et = bt; break
            if sweep_down:
                direction = 1;  entry = b['close']; sl = b['low']  - atr*0.1; et = bt; break
        if direction is None or abs(entry-sl) <= 0: continue
        p = ipos(df, et)
        if p < 0: continue
        r = sim_trade(df, p, direction, entry, sl,
                      max_bars=int((17 - 7) * 1))  # hold until 17:00 max
        trades.append({'pnl': pnl_net(r, COST_AMD), 'date': str(date), 'tag': tag, 'r': r})
    return trades

# ── Main portfolio (compact, for combined comparison) ─────────────────────────
MAIN_R = {'DAX_ORB':0.0075,'NAS_ORB':0.0075,'SP5_ORB':0.004,
          'LC_EUR':0.004,'LC_GBP':0.004,'LC_DAX':0.0075,'LC_UK':0.0075,'LC_GOLD':0.004}
MAIN_C = {'DAX_ORB':0.07,'NAS_ORB':0.06,'SP5_ORB':0.06,
          'LC_EUR':0.08,'LC_GBP':0.08,'LC_DAX':0.07,'LC_UK':0.07,'LC_GOLD':0.08}

def _sim(df,ep,direction,entry,sl,max_bars=80):
    sl_d=abs(entry-sl)
    if sl_d<=0: return -1.0
    tr=sl_d*TRAIL; cs=sl; bst=entry; be=False
    for _,b in df.iloc[ep+1:ep+1+max_bars].iterrows():
        if direction==1:
            if b['low']<=cs: return (cs-entry)/sl_d
            bst=max(bst,b['high'])
            if not be and bst>=entry+sl_d: be=True; cs=entry
            if be:
                ns=bst-tr
                if ns>cs: cs=ns
        else:
            if b['high']>=cs: return (entry-cs)/sl_d
            bst=min(bst,b['low'])
            if not be and bst<=entry-sl_d: be=True; cs=entry
            if be:
                ns=bst+tr
                if ns<cs: cs=ns
    lp=df.iloc[min(ep+max_bars,len(df)-1)]['close']
    return ((lp-entry) if direction==1 else (entry-lp))/sl_d

def run_orb(key,tag,ref_h,es,ee,rmin,rmax,skip_dow=frozenset()):
    df=load_h1(key)
    if df is None: return []
    trades=[]
    for date in sorted(set(df.index.normalize().date)):
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb=df[df.index==day+pd.Timedelta(hours=ref_h)]
        if len(rb)==0: continue
        rhi=rb.iloc[0]['high']; rlo=rb.iloc[0]['low']
        if not (rmin<=rhi-rlo<=rmax): continue
        edf=df[(df.index>=day+pd.Timedelta(hours=es))&(df.index<day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b=edf.iloc[j]; p=ipos(df,edf.index[j])
            if p<0: continue
            if b['high']>rhi:
                r=_sim(df,p,1,rhi,rlo); trades.append({'pnl':(r-MAIN_C[tag]*COST_SCALE)*MAIN_R[tag]*ACCOUNT,'date':str(date),'tag':tag,'r':r}); break
            if b['low']<rlo:
                r=_sim(df,p,-1,rlo,rhi); trades.append({'pnl':(r-MAIN_C[tag]*COST_SCALE)*MAIN_R[tag]*ACCOUNT,'date':str(date),'tag':tag,'r':r}); break
    return trades

def run_lc(key,tag,min_move):
    df=load_h1(key)
    if df is None: return []
    trades=[]
    for date in sorted(set(df.index.normalize().date)):
        day=pd.Timestamp(date,tz='UTC')
        if day.dayofweek==4: continue
        ob=df[df.index==day+pd.Timedelta(hours=7)]; cb=df[df.index==day+pd.Timedelta(hours=15)]
        if len(ob)==0 or len(cb)==0: continue
        move=cb.iloc[0]['close']-ob.iloc[0]['open']
        if abs(move)<min_move: continue
        sess=df[(df.index>=day+pd.Timedelta(hours=7))&(df.index<=day+pd.Timedelta(hours=16))]
        if len(sess)==0: continue
        dh=sess['high'].max(); dl=sess['low'].min(); buf=(dh-dl)*0.03
        p=ipos(df,day+pd.Timedelta(hours=16))
        if p<0: continue
        entry=df.iloc[p]['open']
        if move>min_move:
            sl=dh+buf
            if sl<=entry: continue
            r=_sim(df,p,-1,entry,sl)
        else:
            sl=dl-buf
            if sl>=entry: continue
            r=_sim(df,p,1,entry,sl)
        trades.append({'pnl':(r-MAIN_C[tag]*COST_SCALE)*MAIN_R[tag]*ACCOUNT,'date':str(date),'tag':tag,'r':r})
    return trades

def run_main():
    return (run_orb('DAX','DAX_ORB',8,9,12,30,300)+run_orb('NAS100','NAS_ORB',13,14,16,50,1500,{0,2,4})+
            run_orb('SP500','SP5_ORB',13,14,16,5,300,{0})+run_lc('EURUSD','LC_EUR',0.0020)+
            run_lc('GBPUSD','LC_GBP',0.0025)+run_lc('DAX','LC_DAX',30.0)+run_lc('UK100','LC_UK',30.0)+run_lc('GOLD','LC_GOLD',8.0))

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 70
    print("\n" + "="*W)
    print("  SMART MONEY CONCEPTS (SMC)  —  FVG + AMD Manipulation Reversal")
    print("  ICT-based institutional patterns | 8-year MT5 H1 data | 0.50% risk")
    print("="*W)

    for k in CSVSYMS: load_h1(k)

    # ── Fair Value Gap ────────────────────────────────────────────────────────
    print(f"\n  1. FAIR VALUE GAP (FVG)")
    print(f"  {'Strategy':<12} {'Tr':>5} {'T/mo':>5} {'WR%':>6} {'PF':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'£/mo':>8}")
    print("  " + "─"*(W-2))
    fvg_trades = []
    for key, tag, s_start, s_end, mgap in FVG_CONFIGS:
        t = run_fvg(key, tag, s_start, s_end, mgap)
        s = stats_from(t)
        if not s: print(f"  {tag:<12}  insufficient data"); continue
        ok = '✅' if s['pf']>=1.5 else ('⚠ ' if s['pf']>=1.2 else '❌')
        print(f"  {tag:<12} {s['n']:>5} {s['tpm']:>5.1f} {s['wr']:>5.1f}% "
              f"{s['pf']:>6.2f} £{s['aw']:>6,} £{s['al']:>6,} £{s['mo']:>7,}  {ok}")
        fvg_trades += t

    fvg_s = stats_from(fvg_trades)
    if fvg_s:
        dd, ddp = max_dd(fvg_trades)
        print(f"\n  FVG total: £{fvg_s['mo']:,.0f}/mo | PF {fvg_s['pf']} | WR {fvg_s['wr']}% | MaxDD £{dd:,}")

    # ── AMD Manipulation ──────────────────────────────────────────────────────
    print(f"\n  2. AMD MANIPULATION REVERSAL")
    print(f"  {'Strategy':<12} {'Tr':>5} {'T/mo':>5} {'WR%':>6} {'PF':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'£/mo':>8}")
    print("  " + "─"*(W-2))
    amd_trades = []
    for key, tag, pip in AMD_CONFIGS:
        t = run_amd(key, tag, pip)
        s = stats_from(t)
        if not s: print(f"  {tag:<12}  insufficient data"); continue
        ok = '✅' if s['pf']>=1.5 else ('⚠ ' if s['pf']>=1.2 else '❌')
        print(f"  {tag:<12} {s['n']:>5} {s['tpm']:>5.1f} {s['wr']:>5.1f}% "
              f"{s['pf']:>6.2f} £{s['aw']:>6,} £{s['al']:>6,} £{s['mo']:>7,}  {ok}")
        amd_trades += t

    amd_s = stats_from(amd_trades)
    if amd_s:
        dd, ddp = max_dd(amd_trades)
        print(f"\n  AMD total: £{amd_s['mo']:,.0f}/mo | PF {amd_s['pf']} | WR {amd_s['wr']}% | MaxDD £{dd:,}")

    # ── All SMC combined ──────────────────────────────────────────────────────
    all_smc = fvg_trades + amd_trades
    smc_s = stats_from(all_smc)
    if smc_s:
        dd, ddp = max_dd(all_smc)
        print(f"\n  ALL SMC:   £{smc_s['mo']:,.0f}/mo | PF {smc_s['pf']} | WR {smc_s['wr']}% | MaxDD £{dd:,}")

    # ── Compare with main ─────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  Running main 10kbotV3 portfolio for comparison...")
    print("="*W)
    main_trades = run_main()
    ms = stats_from(main_trades)
    if ms and smc_s:
        mdd, mddp = max_dd(main_trades)
        print(f"\n  Main strategy:  £{ms['mo']:,.0f}/mo | PF {ms['pf']} | WR {ms['wr']}% | MaxDD £{mdd:,}")
        print(f"\n{'='*W}")
        print("  COMBINED PORTFOLIO  (main + SMC)")
        print("="*W)
        all_t = main_trades + all_smc
        cs = stats_from(all_t)
        if cs:
            cdd, cddp = max_dd(all_t)
            print(f"\n  Combined:    £{cs['mo']:,.0f}/mo | PF {cs['pf']} | WR {cs['wr']}% | MaxDD £{cdd:,}")
            print(f"  Main alone:  £{ms['mo']:,.0f}/mo | MaxDD £{mdd:,}")
            print(f"  Improvement: £{cs['mo']-ms['mo']:+,.0f}/mo | DD change: £{cdd-mdd:+,.0f}")
            smc_m = monthly_map(all_smc); mn_m = monthly_map(main_trades)
            common = sorted(set(smc_m) & set(mn_m))
            if len(common) >= 12:
                corr = np.corrcoef([smc_m[m] for m in common], [mn_m[m] for m in common])[0,1]
                verdict = ('Low — good diversifier ✅' if abs(corr)<0.3 else '⚠  Moderate' if abs(corr)<0.6 else '❌ High — correlated')
                print(f"\n  Monthly correlation with main: {corr:.2f}  →  {verdict}")
    print()
