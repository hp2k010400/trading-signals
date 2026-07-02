"""
backtest_vwap.py  —  Session TWAP Deviation Fade
=================================================
Strategy:
  Calculates session Time-Weighted Average Price (TWAP) from 07:00 UTC daily.
  TWAP = expanding mean of (H+L+C)/3 — approximates VWAP without volume data.
  Entry when price deviates > 1.8 × ATR14 from session TWAP.
  Direction: fade the deviation (price extended → expect reversion to mean).
  SL:    1.5 × ATR from entry
  Exit:  price returns to TWAP OR 1R trail after breakeven
  Window: 10:00-15:00 UTC (avoid open/close noise)
  Risk:  0.50% per trade | One trade per instrument per day
  Instruments: GER40, US100, US500 (indices — cleaner intraday structure)

Compares against main 10kbotV3 portfolio and shows combined stats.
Run: python backtest_vwap.py
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
THRESHOLD  = 1.8   # ATR multiples from TWAP to trigger entry
RISK       = 0.005
COST       = 0.08

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

def calc_atr14(df, i, n=14):
    hi = df['high'].iloc[max(0,i-n):i]
    lo = df['low'].iloc[max(0,i-n):i]
    cl = df['close'].iloc[max(0,i-n):i]
    if len(hi) < 2: return 0.0
    tr = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    return tr.mean()

def pnl_net(r): return (r - COST * COST_SCALE) * RISK * ACCOUNT

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

# ── TWAP deviation strategy ───────────────────────────────────────────────────
def run_vwap(key, tag):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek >= 5: continue
        # Session bars from 07:00 UTC
        sess = df[(df.index >= day+pd.Timedelta(hours=7)) &
                  (df.index <  day+pd.Timedelta(hours=17))]
        if len(sess) < 4: continue
        # Entry window 10:00-15:00 UTC
        entry_win = sess[(sess.index.hour >= 10) & (sess.index.hour < 15)]
        if len(entry_win) == 0: continue
        fired = False
        for idx_ts, bar in entry_win.iterrows():
            if fired: break
            # All session bars up to and including this bar
            bars_so_far = sess[sess.index <= idx_ts]
            if len(bars_so_far) < 4: continue
            tp    = (bars_so_far['high'] + bars_so_far['low'] + bars_so_far['close']) / 3
            twap  = tp.mean()
            atr   = (bars_so_far['high'] - bars_so_far['low']).mean()
            if atr <= 0 or twap <= 0: continue
            dev   = (bar['close'] - twap) / atr
            if abs(dev) < THRESHOLD: continue
            direction = -1 if dev > 0 else 1   # fade the deviation
            entry = bar['close']
            sl    = entry + 1.5*atr if direction == -1 else entry - 1.5*atr
            if abs(entry - sl) <= 0: continue
            # Simulate: exit when price returns to TWAP or SL hit
            p = ipos(df, idx_ts)
            if p < 0: continue
            sl_d = abs(entry - sl)
            cur_sl = sl; best = entry; be = False
            trail_step = sl_d * TRAIL
            r = ((df.iloc[min(p+48, len(df)-1)]['close'] - entry) if direction == 1
                 else (entry - df.iloc[min(p+48, len(df)-1)]['close'])) / sl_d
            for _, fb in df.iloc[p+1:p+49].iterrows():
                # Check if price returned to TWAP
                tp2 = (sess[sess.index <= fb.name]['high'] +
                       sess[sess.index <= fb.name]['low'] +
                       sess[sess.index <= fb.name]['close']).mean() / 3
                if direction == 1:
                    if fb['low'] <= cur_sl: r = (cur_sl-entry)/sl_d; break
                    if fb['close'] >= twap: r = (fb['close']-entry)/sl_d; break
                    best = max(best, fb['high'])
                    if not be and best >= entry+sl_d: be=True; cur_sl=entry
                    if be:
                        ns = best - trail_step
                        if ns > cur_sl: cur_sl = ns
                else:
                    if fb['high'] >= cur_sl: r = (entry-cur_sl)/sl_d; break
                    if fb['close'] <= twap: r = (entry-fb['close'])/sl_d; break
                    best = min(best, fb['low'])
                    if not be and best <= entry-sl_d: be=True; cur_sl=entry
                    if be:
                        ns = best + trail_step
                        if ns < cur_sl: cur_sl = ns
            trades.append({'pnl': pnl_net(r), 'date': str(date), 'tag': tag, 'r': r})
            fired = True
    return trades

# ── Main portfolio (compact, for combined comparison) ─────────────────────────
MAIN_R = {'DAX_ORB':0.0075,'NAS_ORB':0.0075,'SP5_ORB':0.004,
          'LC_EUR':0.004,'LC_GBP':0.004,'LC_DAX':0.0075,'LC_UK':0.0075,'LC_GOLD':0.004}
MAIN_C = {'DAX_ORB':0.07,'NAS_ORB':0.06,'SP5_ORB':0.06,
          'LC_EUR':0.08,'LC_GBP':0.08,'LC_DAX':0.07,'LC_UK':0.07,'LC_GOLD':0.08}

def _sim(df, ep, direction, entry, sl, max_bars=80):
    sl_d = abs(entry-sl)
    if sl_d <= 0: return -1.0
    tr=sl_d*TRAIL; cs=sl; bst=entry; be=False
    for _, b in df.iloc[ep+1:ep+1+max_bars].iterrows():
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
    print("  SESSION TWAP DEVIATION FADE  (approximates institutional VWAP fade)")
    print("  Entry: price > 1.8×ATR from session mean | Exit: mean retest or trail")
    print("  3 instruments | 8-year MT5 H1 data | 0.50% risk")
    print("="*W)

    for k in CSVSYMS: load_h1(k)

    VWAP_STRATS = [
        ('DAX',   'TWAP_DAX'),
        ('NAS100','TWAP_NAS'),
        ('SP500', 'TWAP_SP5'),
    ]

    all_vwap = []
    print(f"\n  {'Strategy':<12} {'Tr':>5} {'T/mo':>5} {'WR%':>6} {'PF':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'£/mo':>8}")
    print("  " + "─"*(W-2))
    for key, tag in VWAP_STRATS:
        t = run_vwap(key, tag)
        s = stats_from(t)
        if not s: print(f"  {tag:<12}  no data / insufficient trades"); continue
        ok = '✅' if s['pf']>=1.5 else ('⚠ ' if s['pf']>=1.2 else '❌')
        print(f"  {tag:<12} {s['n']:>5} {s['tpm']:>5.1f} {s['wr']:>5.1f}% "
              f"{s['pf']:>6.2f} £{s['aw']:>6,} £{s['al']:>6,} £{s['mo']:>7,}  {ok}")
        all_vwap += t

    vw = stats_from(all_vwap)
    if vw:
        dd, ddp = max_dd(all_vwap)
        print(f"\n  TWAP total: £{vw['mo']:,.0f}/mo | PF {vw['pf']} | WR {vw['wr']}% | MaxDD £{dd:,} ({ddp}%)")

    print(f"\n{'='*W}")
    print("  Running main 10kbotV3 portfolio for comparison...")
    print("="*W)
    main_trades = run_main()
    ms = stats_from(main_trades)
    if ms:
        mdd, mddp = max_dd(main_trades)
        print(f"\n  Main strategy:  £{ms['mo']:,.0f}/mo | PF {ms['pf']} | WR {ms['wr']}% | MaxDD £{mdd:,} ({mddp}%)")

    if vw and ms:
        print(f"\n{'='*W}")
        print("  COMBINED PORTFOLIO  (main + TWAP fade)")
        print("="*W)
        all_t = main_trades + all_vwap
        cs = stats_from(all_t)
        if cs:
            cdd, cddp = max_dd(all_t)
            print(f"\n  Combined:    £{cs['mo']:,.0f}/mo | PF {cs['pf']} | WR {cs['wr']}% | MaxDD £{cdd:,} ({cddp}%)")
            print(f"  Main alone:  £{ms['mo']:,.0f}/mo | MaxDD £{mdd:,}")
            print(f"  Improvement: £{cs['mo']-ms['mo']:+,.0f}/mo | DD change: £{cdd-mdd:+,.0f}")
            vw_m = monthly_map(all_vwap); mn_m = monthly_map(main_trades)
            common = sorted(set(vw_m) & set(mn_m))
            if len(common) >= 12:
                corr = np.corrcoef([vw_m[m] for m in common], [mn_m[m] for m in common])[0,1]
                verdict = ('Low — good diversifier ✅' if abs(corr)<0.3 else '⚠  Moderate' if abs(corr)<0.6 else '❌ High — correlated')
                print(f"\n  Monthly correlation with main: {corr:.2f}  →  {verdict}")
    print()
