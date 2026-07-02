"""
backtest_sensitivity.py  —  Parameter Robustness & Slippage Stress Test
========================================================================
Tests whether the edge is REAL (works across a range of settings)
or CURVE-FITTED (only works at the exact current parameters).

5 tests:
  1. LC min_move threshold  — how sensitive is the signal filter?
  2. ORB range filter       — does the range window matter?
  3. Trailing stop size     — is 10% trail the sweet spot or arbitrary?
  4. LC entry time          — is 16:00 UTC "special" or would 15:00/17:00 work?
  5. Slippage / execution   — how bad can fills get before edge disappears?

Run: python backtest_sensitivity.py
"""
import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

ACCOUNT = 70_000

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

def sim(df, ep, direction, entry, sl, trail, max_bars=80):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return -1.0
    tr = sl_d * trail; cs = sl; bst = entry; be = False
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

def _pnl(r, risk, cost, cs): return (r - cost * cs) * risk * ACCOUNT

def run_lc(key, tag, min_move, risk, cost, trail=0.10, cs=1.5, lc_hour=16):
    df = load_h1(key)
    if df is None: return []
    trades = []
    am_close_h = lc_hour - 1
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue
        ob   = df[df.index == day + pd.Timedelta(hours=7)]
        cb   = df[df.index == day + pd.Timedelta(hours=am_close_h)]
        if len(ob) == 0 or len(cb) == 0: continue
        move = cb.iloc[0]['close'] - ob.iloc[0]['open']
        if abs(move) < min_move: continue
        sess = df[(df.index >= day+pd.Timedelta(hours=7)) &
                  (df.index <= day+pd.Timedelta(hours=lc_hour))]
        if len(sess) == 0: continue
        dh = sess['high'].max(); dl = sess['low'].min(); buf = (dh-dl)*0.03
        p  = ipos(df, day + pd.Timedelta(hours=lc_hour))
        if p < 0: continue
        entry = df.iloc[p]['open']
        if move > 0: sl = dh + buf; d = -1
        else:        sl = dl - buf; d =  1
        if d == -1 and sl <= entry: continue
        if d ==  1 and sl >= entry: continue
        r = sim(df, p, d, entry, sl, trail)
        trades.append({'pnl': _pnl(r, risk, cost, cs), 'date': str(date), 'tag': tag})
    return trades

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, risk, cost,
            skip_dow=frozenset(), trail=0.10, cs=1.5):
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
                r = sim(df, p, 1, rhi, rlo, trail)
                trades.append({'pnl':_pnl(r,risk,cost,cs),'date':str(date),'tag':tag}); break
            if b['low'] < rlo:
                r = sim(df, p,-1, rlo, rhi, trail)
                trades.append({'pnl':_pnl(r,risk,cost,cs),'date':str(date),'tag':tag}); break
    return trades

def run_all(mm=1.0, rng=1.0, trail=0.10, cs=1.5, lc_hour=16):
    kw_lc  = dict(trail=trail, cs=cs, lc_hour=lc_hour)
    kw_orb = dict(trail=trail, cs=cs)
    return (
        run_orb('DAX',   'DAX_ORB', 8, 9,12, 30*rng,  300*rng, 0.0075,0.07, frozenset(), **kw_orb) +
        run_orb('NAS100','NAS_ORB',13,14,16, 50*rng, 1500*rng, 0.0075,0.06, {0,2,4},     **kw_orb) +
        run_orb('SP500', 'SP5_ORB',13,14,16,  5*rng,  300*rng, 0.004, 0.06, {0},         **kw_orb) +
        run_lc('EURUSD','LC_EUR', 0.0020*mm, 0.004, 0.08, **kw_lc) +
        run_lc('GBPUSD','LC_GBP', 0.0025*mm, 0.004, 0.08, **kw_lc) +
        run_lc('DAX',   'LC_DAX',  30.0*mm,  0.0075,0.07, **kw_lc) +
        run_lc('UK100', 'LC_UK',   30.0*mm,  0.0075,0.07, **kw_lc) +
        run_lc('GOLD',  'LC_GOLD',  8.0*mm,  0.004, 0.08, **kw_lc)
    )

def row_stats(trades, base_pf=None):
    if len(trades) < 20: return None
    arr  = np.array([t['pnl'] for t in trades])
    wins = arr[arr > 5]; loss = arr[arr < -5]
    wr   = len(wins)/len(arr)*100
    pf   = round(wins.sum()/abs(loss.sum()), 2) if len(loss) and loss.sum()!=0 else 0.0
    dates= sorted(set(t['date'] for t in trades))
    span = max((pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days, 1)
    mo   = round(arr.sum()/span*21, 0)
    eq   = ACCOUNT + np.cumsum(arr)
    dd   = round((np.maximum.accumulate(eq)-eq).max(), 0)
    delta = f'{pf-base_pf:+.2f}' if base_pf else '  base'
    flag = ('← baseline' if base_pf is None else
            ('✅' if pf >= base_pf * 0.85 else '❌ FRAGILE'))
    return {'n':len(arr),'wr':round(wr,1),'pf':pf,'mo':mo,'dd':dd,'delta':delta,'flag':flag}

def print_row(label, s):
    if s:
        print(f"  {label:<14} {s['n']:>5} {s['wr']:>5.1f}% {s['pf']:>6.2f} "
              f"{s['delta']:>8}  £{s['mo']:>7,.0f}  £{s['dd']:>7,.0f}  {s['flag']}")

HDR = f"  {'Label':<14} {'Tr':>5} {'WR%':>6} {'PF':>6} {'ΔPF':>8}  {'£/mo':>8}  {'MaxDD':>8}"
SEP = "  " + "─"*68

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 72
    print("\n" + "="*W)
    print("  PARAMETER SENSITIVITY & SLIPPAGE STRESS TEST")
    print("  Does the edge hold across a range of settings?")
    print("  ✅ = PF stays within 15% of baseline  |  ❌ FRAGILE = edge breaks")
    print("="*W)

    for k in CSVSYMS: load_h1(k)
    print("\n  Running baseline...")
    base_trades = run_all()
    base = row_stats(base_trades)
    print(f"\n  BASELINE  →  {base['n']} trades | PF {base['pf']} | "
          f"£{base['mo']:,.0f}/mo | MaxDD £{base['dd']:,}\n")

    # ── Test 1: LC min_move ───────────────────────────────────────────────────
    print("="*W)
    print("  TEST 1 — LC morning move threshold  (how big the move must be to qualify)")
    print("  60% = easier to qualify (more trades) | 140% = harder (fewer trades)")
    print(f"  If PF collapses at 80% or 120% → threshold was cherry-picked")
    print(SEP); print(HDR); print(SEP)
    for scale, label in [(0.6,'60% (easier)'),(0.8,'80%'),(1.0,'100% BASE'),
                         (1.2,'120%'),(1.4,'140% (harder)')]:
        t = run_all(mm=scale)
        s = row_stats(t, None if scale==1.0 else base['pf'])
        if scale == 1.0: s['delta'] = '  base'; s['flag'] = '← baseline'
        print_row(label, s)

    # ── Test 2: ORB range filter ──────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  TEST 2 — ORB range filter  (DAX: 30–300pts | NAS: 50–1500pts)")
    print("  Tests whether the range boundaries are meaningful or arbitrary")
    print(SEP); print(HDR); print(SEP)
    for scale, label in [(0.6,'60% (tighter)'),(0.8,'80%'),(1.0,'100% BASE'),
                         (1.2,'120%'),(1.4,'140% (wider)')]:
        t = run_all(rng=scale)
        s = row_stats(t, None if scale==1.0 else base['pf'])
        if scale == 1.0: s['delta'] = '  base'; s['flag'] = '← baseline'
        print_row(label, s)

    # ── Test 3: Trailing stop ─────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  TEST 3 — Trailing stop size  (currently 10% of SL distance)")
    print("  Tight trail = locks in more profit but exits earlier")
    print("  Wide trail  = lets winners run further but gives back more")
    print(SEP); print(HDR); print(SEP)
    for trail, label in [(0.05,'5% (tightest)'),(0.075,'7.5%'),(0.10,'10%  BASE'),
                         (0.125,'12.5%'),(0.15,'15% (widest)')]:
        t = run_all(trail=trail)
        s = row_stats(t, None if trail==0.10 else base['pf'])
        if trail == 0.10: s['delta'] = '  base'; s['flag'] = '← baseline'
        print_row(label, s)

    # ── Test 4: LC entry time ─────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  TEST 4 — LC entry hour  (currently 16:00 UTC = London Close)")
    print("  Is 16:00 special, or would 15:00 or 17:00 work just as well?")
    print("  If only 16:00 works → timing was fitted to data")
    print("  If 15–17:00 all work → the reversal effect is real & persistent")
    print(SEP); print(HDR); print(SEP)
    for hour, label in [(13,'13:00 UTC'),(14,'14:00 UTC'),(15,'15:00 UTC'),
                        (16,'16:00 BASE'),(17,'17:00 UTC'),(18,'18:00 UTC')]:
        t = run_all(lc_hour=hour)
        s = row_stats(t, None if hour==16 else base['pf'])
        if hour == 16: s['delta'] = '  base'; s['flag'] = '← baseline'
        print_row(label, s)

    # ── Test 5: Slippage / cost ───────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  TEST 5 — Slippage stress test  (baseline cost_scale = 1.5×)")
    print("  How much worse can execution get before the edge disappears?")
    print("  2.0× = fills 33% worse than assumed | 4.0× = extreme slippage")
    print(SEP); print(HDR); print(SEP)
    for cs, label in [(0.75,'0.5× (best)'),(1.5,'1.0×  BASE'),
                      (3.0,'2.0× (worse)'),(4.5,'3.0× (bad)'),(6.0,'4.0× (extreme)')]:
        t = run_all(cs=cs)
        s = row_stats(t, None if cs==1.5 else base['pf'])
        if cs == 1.5: s['delta'] = '  base'; s['flag'] = '← baseline'
        if s and cs != 1.5:
            s['flag'] = ('✅' if s['pf'] >= 1.2 else ('⚠  barely' if s['pf'] >= 1.0 else '❌ EDGE GONE'))
        print_row(label, s)

    # ── Verdict ───────────────────────────────────────────────────────────────
    print(f"\n{'='*W}")
    print("  ROBUSTNESS VERDICT")
    print("="*W)
    print("""
  If most tests show ✅:
    → Edge comes from real market structure (institutions reversing at LC,
      ORB momentum from volatility expansions). Parameters are reasonable
      filters, not cherry-picked magic numbers. Safe to trade live.

  If tests show ❌ on small changes:
    → Edge is curve-fitted. Works in backtest only because params were
      tuned to the exact historical data. Will not hold forward.
    """)
