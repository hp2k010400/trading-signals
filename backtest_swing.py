"""
backtest_swing.py  —  Swing / Trend Following  (Donchian 20-day Breakout)
==========================================================================
Strategy:
  20-day Donchian channel on D1 (resampled from H1 CSV data).
  Buy:  yesterday close > 20-day high  →  enter at today open
  Sell: yesterday close < 20-day low   →  enter at today open
  SL:   10-day opposite extreme
  Trail: 0.10R step after 1R breakeven | Max hold: 15 trading days
  Risk:  0.75% indices / 0.50% FX + GOLD
  Filter: skip Friday entries, require ATR > 0.2% of price

Compares against main 10kbotV3 portfolio and shows combined stats.
Run: python backtest_swing.py
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

def resample_d1(df):
    d1 = df.resample('D').agg({'open':'first','high':'max','low':'min','close':'last'})
    counts = df.resample('D').size()
    return d1[counts >= 6].dropna()

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    return int(a) if a < len(df) and df.index[int(a)] == ts else -1

def sim_h1(df, ep, direction, entry, sl, max_bars=150):
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

def pnl_net(r, risk, cost): return (r - cost * COST_SCALE) * risk * ACCOUNT

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
    dd  = (pk - eq).max()
    return round(dd, 0), round(dd/ACCOUNT*100, 2)

def monthly_map(trades):
    m = defaultdict(float)
    for t in trades: m[t['date'][:7]] += t['pnl']
    return m

# ── Donchian swing runner ─────────────────────────────────────────────────────
SWING = [
    ('DAX',   'SW_GER40', 0.0075, 0.08),
    ('NAS100','SW_US100', 0.0075, 0.08),
    ('SP500', 'SW_SP500', 0.0075, 0.06),
    ('UK100', 'SW_UK100', 0.0075, 0.08),
    ('EURUSD','SW_EUR',   0.005,  0.09),
    ('GBPUSD','SW_GBP',   0.005,  0.09),
    ('GOLD',  'SW_GOLD',  0.005,  0.09),
]

def run_swing(key, tag, risk, cost, n_hi=20, n_trail=10, max_days=15):
    df = load_h1(key)
    if df is None: return []
    d1 = resample_d1(df)
    trades = []
    for i in range(n_hi + 2, len(d1) - 1):
        prev      = d1.iloc[i - 1]
        ch_hi     = d1.iloc[i-n_hi:i-1]['high'].max()   # exclude yesterday so close can break it
        ch_lo     = d1.iloc[i-n_hi:i-1]['low'].min()
        atr14     = (d1.iloc[max(0,i-14):i]['high'] - d1.iloc[max(0,i-14):i]['low']).mean()
        entry_day = d1.index[i]
        if entry_day.dayofweek >= 4: continue           # skip Fri/Sat
        if atr14 < prev['close'] * 0.002: continue      # low volatility filter
        # Find first H1 bar on entry day
        day_bars = df[df.index.date == entry_day.date()]
        if len(day_bars) == 0: continue
        ep    = ipos(df, day_bars.index[0])
        if ep < 0: continue
        entry_px = day_bars.iloc[0]['open']
        ds       = str(entry_day.date())
        dow      = entry_day.dayofweek
        if prev['close'] > ch_hi:   # long signal
            sl_px = d1.iloc[i-n_trail:i]['low'].min()
            if sl_px >= entry_px or entry_px - sl_px < entry_px * 0.001: continue
            r = sim_h1(df, ep, 1, entry_px, sl_px, max_days*10)
            trades.append({'pnl': pnl_net(r, risk, cost), 'date': ds, 'tag': tag, 'r': r})
        elif prev['close'] < ch_lo:  # short signal
            sl_px = d1.iloc[i-n_trail:i]['high'].max()
            if sl_px <= entry_px or sl_px - entry_px < entry_px * 0.001: continue
            r = sim_h1(df, ep, -1, entry_px, sl_px, max_days*10)
            trades.append({'pnl': pnl_net(r, risk, cost), 'date': ds, 'tag': tag, 'r': r})
    return trades

# ── Main portfolio (compact, for combined comparison) ─────────────────────────
MAIN_R = {'DAX_ORB':0.0075,'NAS_ORB':0.0075,'SP5_ORB':0.004,
          'LC_EUR':0.004,'LC_GBP':0.004,'LC_DAX':0.0075,'LC_UK':0.0075,'LC_GOLD':0.004}
MAIN_C = {'DAX_ORB':0.07,'NAS_ORB':0.06,'SP5_ORB':0.06,
          'LC_EUR':0.08,'LC_GBP':0.08,'LC_DAX':0.07,'LC_UK':0.07,'LC_GOLD':0.08}

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=frozenset()):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb  = df[df.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue
        edf = df[(df.index >= day+pd.Timedelta(hours=es)) &
                 (df.index <  day+pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                r = sim_h1(df, p, 1, rhi, rlo)
                trades.append({'pnl':pnl_net(r,MAIN_R[tag],MAIN_C[tag]),'date':str(date),'tag':tag,'r':r}); break
            if b['low'] < rlo:
                r = sim_h1(df, p, -1, rlo, rhi)
                trades.append({'pnl':pnl_net(r,MAIN_R[tag],MAIN_C[tag]),'date':str(date),'tag':tag,'r':r}); break
    return trades

def run_lc(key, tag, min_move):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        ob  = df[df.index == day+pd.Timedelta(hours=7)]
        cb  = df[df.index == day+pd.Timedelta(hours=15)]
        if len(ob)==0 or len(cb)==0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue
        sess = df[(df.index >= day+pd.Timedelta(hours=7)) & (df.index <= day+pd.Timedelta(hours=16))]
        if len(sess) == 0: continue
        dh = sess['high'].max(); dl = sess['low'].min(); buf = (dh-dl)*0.03
        p  = ipos(df, day+pd.Timedelta(hours=16))
        if p < 0: continue
        entry = df.iloc[p]['open']
        if move > min_move:
            sl = dh + buf
            if sl <= entry: continue
            r = sim_h1(df, p, -1, entry, sl)
        else:
            sl = dl - buf
            if sl >= entry: continue
            r = sim_h1(df, p, 1, entry, sl)
        trades.append({'pnl':pnl_net(r,MAIN_R[tag],MAIN_C[tag]),'date':str(date),'tag':tag,'r':r})
    return trades

def run_main():
    return (run_orb('DAX','DAX_ORB',8,9,12,30,300) +
            run_orb('NAS100','NAS_ORB',13,14,16,50,1500,{0,2,4}) +
            run_orb('SP500','SP5_ORB',13,14,16,5,300,{0}) +
            run_lc('EURUSD','LC_EUR',0.0020) + run_lc('GBPUSD','LC_GBP',0.0025) +
            run_lc('DAX','LC_DAX',30.0) + run_lc('UK100','LC_UK',30.0) +
            run_lc('GOLD','LC_GOLD',8.0))

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 70
    print("\n" + "="*W)
    print("  SWING / TREND FOLLOWING  —  Donchian 20-day Breakout")
    print("  7 instruments | 8-year MT5 H1 data | 0.75% risk (indices) / 0.50% (FX)")
    print("="*W)

    print("\n  Loading data and running strategies...")
    for k in CSVSYMS: load_h1(k)

    swing_trades = []
    print(f"\n  {'Strategy':<12} {'Tr':>5} {'T/mo':>5} {'WR%':>6} {'PF':>6} "
          f"{'AvgW':>7} {'AvgL':>7} {'£/mo':>8}")
    print("  " + "─"*(W-2))
    for key, tag, risk, cost in SWING:
        t = run_swing(key, tag, risk, cost)
        s = stats_from(t)
        if not s:
            print(f"  {tag:<12}  no data"); continue
        ok = '✅' if s['pf']>=1.5 else ('⚠ ' if s['pf']>=1.2 else '❌')
        print(f"  {tag:<12} {s['n']:>5} {s['tpm']:>5.1f} {s['wr']:>5.1f}% "
              f"{s['pf']:>6.2f} £{s['aw']:>6,} £{s['al']:>6,} £{s['mo']:>7,}  {ok}")
        swing_trades += t

    sw = stats_from(swing_trades)
    if sw:
        dd, ddp = max_dd(swing_trades)
        print(f"\n  Portfolio total: £{sw['mo']:,.0f}/mo | PF {sw['pf']} | "
              f"WR {sw['wr']}% | MaxDD £{dd:,} ({ddp}%)")

    print(f"\n{'='*W}")
    print("  Running main 10kbotV3 portfolio for comparison...")
    print("="*W)
    main_trades = run_main()
    ms = stats_from(main_trades)
    if ms:
        mdd, mddp = max_dd(main_trades)
        print(f"\n  Main strategy:  £{ms['mo']:,.0f}/mo | PF {ms['pf']} | "
              f"WR {ms['wr']}% | MaxDD £{mdd:,} ({mddp}%)")

    print(f"\n{'='*W}")
    print("  COMBINED PORTFOLIO  (main + swing)")
    print("="*W)
    all_t = main_trades + swing_trades
    cs = stats_from(all_t)
    if cs and ms and sw:
        cdd, cddp = max_dd(all_t)
        print(f"\n  Combined:       £{cs['mo']:,.0f}/mo | PF {cs['pf']} | "
              f"WR {cs['wr']}% | MaxDD £{cdd:,} ({cddp}%)")
        print(f"  Main alone:     £{ms['mo']:,.0f}/mo | MaxDD £{mdd:,}")
        print(f"  Improvement:    £{cs['mo']-ms['mo']:+,.0f}/mo | "
              f"DD change: £{cdd-mdd:+,.0f}")

        # Monthly correlation
        sw_m = monthly_map(swing_trades)
        mn_m = monthly_map(main_trades)
        common = sorted(set(sw_m) & set(mn_m))
        if len(common) >= 12:
            sv = np.array([sw_m[m] for m in common])
            mv = np.array([mn_m[m] for m in common])
            corr = np.corrcoef(sv, mv)[0,1]
            verdict = ('Low — good diversifier ✅' if abs(corr) < 0.3 else
                       'Moderate ⚠ ' if abs(corr) < 0.6 else 'High — correlated ❌')
            print(f"\n  Monthly correlation with main: {corr:.2f}  →  {verdict}")
            print(f"  ({len(common)} months of overlap)")

    print()
