"""
backtest_correlation.py  —  LC Correlation Filter Test
=======================================================
The issue: LC_EUR and LC_GBP both fire at 16:00 UTC on the same day.
They're ~80% correlated — on bad LC days both stop out simultaneously.
Same problem with LC_DAX and LC_UK (both European indices).

This script tests 5 configurations:
  A. Baseline  — all 8 strategies as-is (current bot)
  B. FX filter — when EUR+GBP both signal, take only the larger morning move
  C. FX boost  — like B but boost winner to 0.80% risk (same total FX exposure)
  D. IDX filter — also filter DAX vs UK100
  E. Full      — both FX and Index filters with boost

Also analyses: how often do EUR+GBP win/lose together? (confirms correlation)

Run: python backtest_correlation.py
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

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    return int(a) if a < len(df) and df.index[int(a)] == ts else -1

def sim(df, ep, direction, entry, sl, max_bars=80):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    tr = sl_d * TRAIL; cs = sl; bst = entry; be = False
    for _, b in df.iloc[ep+1: ep+1+max_bars].iterrows():
        if direction == 1:
            if b['low'] <= cs: return (cs - entry) / sl_d
            bst = max(bst, b['high'])
            if not be and bst >= entry + sl_d: be = True; cs = entry
            if be:
                ns = bst - tr
                if ns > cs: cs = ns
        else:
            if b['high'] >= cs: return (entry - cs) / sl_d
            bst = min(bst, b['low'])
            if not be and bst <= entry - sl_d: be = True; cs = entry
            if be:
                ns = bst + tr
                if ns < cs: cs = ns
    lp = df.iloc[min(ep + max_bars, len(df)-1)]['close']
    return ((lp - entry) if direction == 1 else (entry - lp)) / sl_d

def _pnl(r, risk, cost): return (r - cost * COST_SCALE) * risk * ACCOUNT

def _get_sig(df, day, mm):
    """Get LC morning move if it qualifies, else None."""
    if df is None: return None
    ob = df[df.index == day + pd.Timedelta(hours=7)]
    cb = df[df.index == day + pd.Timedelta(hours=15)]
    if len(ob) == 0 or len(cb) == 0: return None
    m = cb.iloc[0]['close'] - ob.iloc[0]['open']
    return m if abs(m) >= mm else None

def _exec(df, day, move, tag, risk, cost):
    """Execute an LC trade, return trade dict or None."""
    if df is None: return None
    sess = df[(df.index >= day+pd.Timedelta(hours=7)) &
              (df.index <= day+pd.Timedelta(hours=16))]
    if len(sess) == 0: return None
    dh = sess['high'].max(); dl = sess['low'].min(); buf = (dh - dl) * 0.03
    p  = ipos(df, day + pd.Timedelta(hours=16))
    if p < 0: return None
    entry = df.iloc[p]['open']
    if move > 0: sl = dh + buf; d = -1
    else:        sl = dl - buf; d =  1
    if d == -1 and sl <= entry: return None
    if d ==  1 and sl >= entry: return None
    r = sim(df, p, d, entry, sl)
    return {'pnl': _pnl(r, risk, cost), 'date': str(day.date()), 'tag': tag, 'r': r}

def run_lc_pair(ka, ta, mma, ra, ca, kb, tb, mmb, rb, cb,
                pick_stronger=False, boost=False):
    """
    Run LC on two instruments (or one if kb=None).
    If pick_stronger: on dual-signal days, take only the larger normalised move.
    If boost: when picking one, use ra+rb as the risk (same total exposure).
    """
    da = load_h1(ka)
    db = load_h1(kb) if kb else None
    trades = []; dual = 0; single_a = 0; single_b = 0
    a_dates = set(d.date() for d in (da.index if da is not None else []))
    b_dates = set(d.date() for d in (db.index if db is not None else []))
    for date in sorted(a_dates | b_dates):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        sa = _get_sig(da, day, mma)
        sb = _get_sig(db, day, mmb) if db is not None else None
        if sa is not None and sb is not None:
            dual += 1
            if pick_stronger:
                use_r = (ra + rb) if boost else ra
                if abs(sa) / mma >= abs(sb) / mmb:
                    t = _exec(da, day, sa, ta, use_r, ca)
                else:
                    t = _exec(db, day, sb, tb, use_r, cb)
                if t: trades.append(t)
            else:
                ta_ = _exec(da, day, sa, ta, ra, ca)
                tb_ = _exec(db, day, sb, tb, rb, cb)
                if ta_: trades.append(ta_)
                if tb_: trades.append(tb_)
        elif sa is not None:
            single_a += 1
            t = _exec(da, day, sa, ta, ra, ca)
            if t: trades.append(t)
        elif sb is not None:
            single_b += 1
            t = _exec(db, day, sb, tb, rb, cb)
            if t: trades.append(t)
    return trades, dual, single_a + single_b

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, cost, skip_dow=frozenset()):
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
                r = sim(df, p, 1, rhi, rlo)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
            if b['low'] < rlo:
                r = sim(df, p, -1, rlo, rhi)
                trades.append({'pnl':_pnl(r,risk,cost),'date':str(date),'tag':tag,'r':r}); break
    return trades

def build(fx_filter=False, fx_boost=False, idx_filter=False):
    orb = (run_orb('DAX',   'DAX_ORB', 8,  9, 12, 30,  300, 0.0075, 0.07) +
           run_orb('NAS100','NAS_ORB',13, 14, 16, 50, 1500, 0.0075, 0.06, {0,2,4}) +
           run_orb('SP500', 'SP5_ORB',13, 14, 16,  5,  300, 0.004,  0.06, {0}))
    fx,  fd,  fs  = run_lc_pair('EURUSD','LC_EUR',0.0020,0.004,0.08,
                                 'GBPUSD','LC_GBP',0.0025,0.004,0.08, fx_filter, fx_boost)
    idx, id_, is_ = run_lc_pair('DAX',   'LC_DAX',30.0, 0.0075,0.07,
                                 'UK100', 'LC_UK', 30.0, 0.0075,0.07, idx_filter)
    gld, _,  _    = run_lc_pair('GOLD',  'LC_GOLD',8.0,  0.004, 0.08,
                                 None,    None,    None,  None,  None)
    return orb + fx + idx + gld, fd, id_

def stats(trades):
    if len(trades) < 20: return None
    arr  = np.array([t['pnl'] for t in trades])
    wins = arr[arr > 5]; loss = arr[arr < -5]
    dates = sorted(set(t['date'] for t in trades))
    span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    eq    = ACCOUNT + np.cumsum(arr); pk = np.maximum.accumulate(eq)
    dd    = (pk - eq).max()
    return {
        'n':   len(arr),
        'wr':  round(len(wins)/len(arr)*100, 1),
        'pf':  round(wins.sum()/abs(loss.sum()), 2) if len(loss) and loss.sum() != 0 else 0.0,
        'mo':  round(arr.sum()/span*21, 0),
        'dd':  round(dd, 0),
        'ddp': round(dd/ACCOUNT*100, 2),
    }

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 70
    print("\n" + "="*W)
    print("  LC CORRELATION FILTER TEST  —  8-year MT5 H1 data")
    print("  Question: does picking the stronger EUR/GBP signal improve the portfolio?")
    print("="*W)
    for k in CSVSYMS: load_h1(k)
    print("\n  Data loaded. Running 5 configurations...\n")

    configs = [
        ("A. Baseline (current bot)",    False, False, False),
        ("B. FX filter",                 True,  False, False),
        ("C. FX filter + risk boost",    True,  True,  False),
        ("D. FX + Index filter",         True,  False, True),
        ("E. Full filter + boost",       True,  True,  True),
    ]

    print(f"  {'Config':<32} {'Tr':>5} {'WR%':>6} {'PF':>6} {'£/mo':>8} {'MaxDD':>9} {'DD%':>6}")
    print("  " + "─"*(W-2))
    results = []
    for label, ff, fb, fi in configs:
        t, fd, id_ = build(ff, fb, fi)
        s = stats(t)
        if not s: print(f"  {label:<32}  insufficient data"); continue
        ok = '✅' if s['pf'] >= 1.95 else ('⚠ ' if s['pf'] >= 1.75 else '❌')
        print(f"  {label:<32} {s['n']:>5} {s['wr']:>5.1f}% {s['pf']:>6.2f} "
              f"£{s['mo']:>7,} £{s['dd']:>8,} {s['ddp']:>5.1f}%  {ok}")
        results.append((label, s, fd, id_))

    # ── Dual-signal day analysis ──────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  DUAL-SIGNAL DAY ANALYSIS  (EUR + GBP)")
    print("  How often do they signal together? Do they win/lose together?")
    print("="*W)
    da = load_h1('EURUSD'); db = load_h1('GBPUSD')
    if da is not None and db is not None:
        both_win = both_lose = split = total = 0
        eur_wins_gbp_loses = eur_loses_gbp_wins = 0
        for date in sorted(set(d.date() for d in da.index)):
            day = pd.Timestamp(date, tz='UTC')
            if day.dayofweek == 4: continue
            sa = _get_sig(da, day, 0.0020); sb = _get_sig(db, day, 0.0025)
            if sa is None or sb is None: continue
            ta = _exec(da, day, sa, 'LC_EUR', 0.004, 0.08)
            tb = _exec(db, day, sb, 'LC_GBP', 0.004, 0.08)
            if ta is None or tb is None: continue
            total += 1
            wa = ta['r'] > 0; wb = tb['r'] > 0
            if wa and wb:   both_win  += 1
            elif not wa and not wb: both_lose += 1
            else:
                split += 1
                if wa: eur_wins_gbp_loses += 1
                else:  eur_loses_gbp_wins += 1
        if total > 0:
            print(f"\n  Days EUR+GBP both qualify:   {total}")
            print(f"  Both WIN:                    {both_win:>4}  ({both_win/total*100:.0f}%)")
            print(f"  Both LOSE:                   {both_lose:>4}  ({both_lose/total*100:.0f}%)")
            print(f"  Split (EUR win, GBP lose):   {eur_wins_gbp_loses:>4}  ({eur_wins_gbp_loses/total*100:.0f}%)")
            print(f"  Split (GBP win, EUR lose):   {eur_loses_gbp_wins:>4}  ({eur_loses_gbp_wins/total*100:.0f}%)")
            corr_rate = (both_win + both_lose) / total * 100
            print(f"\n  Move in SAME direction:      {corr_rate:.0f}% of dual-signal days")
            if corr_rate > 65:
                print(f"  → HIGH correlation confirmed. On {both_lose} days both lose together.")
                print(f"    Filtering to 1 trade would have avoided {both_lose} double-loss days.")
            else:
                print(f"  → Lower correlation than expected. Filter may not help much.")

    # ── Verdict ───────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  VERDICT")
    print("="*W)
    if len(results) >= 2:
        base = results[0][1]
        best_idx = max(range(1, len(results)), key=lambda i: results[i][1]['pf'])
        best_label, best_s, _, _ = results[best_idx]
        print(f"\n  Baseline:      PF {base['pf']}  |  £{base['mo']:,.0f}/mo  |  MaxDD £{base['dd']:,}")
        print(f"  Best filter:   {best_label}")
        print(f"                 PF {best_s['pf']}  |  £{best_s['mo']:,.0f}/mo  |  MaxDD £{best_s['dd']:,}")
        print(f"\n  Monthly change: £{best_s['mo']-base['mo']:+,.0f}")
        print(f"  MaxDD change:   £{best_s['dd']-base['dd']:+,.0f}")
        print(f"  PF change:      {best_s['pf']-base['pf']:+.2f}")
        if best_s['pf'] > base['pf']:
            print(f"\n  ✅ Filter IMPROVES strategy — worth implementing in the EA")
        else:
            print(f"\n  ❌ Filter does NOT improve strategy — leave current bot as-is")
    print()
