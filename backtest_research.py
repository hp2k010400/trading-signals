"""
backtest_research.py — Strategy research lab
8 years of real MT5 H1 data (2018-2026)

Tests:
  1. ATR volatility filter  — only trade high-vol days
  2. Trend direction filter — only trade LB in EMA direction
  3. Day-of-week breakdown  — find days to skip per strategy
  4. Asia ORB               — Tokyo session range, London breakout
  5. London Close Reversal  — fade the morning move at 16:00 UTC
  6. Best portfolio summary

Run: python backtest_research.py
"""

import pandas as pd
import numpy as np
import warnings
import os
from dataclasses import dataclass
from collections import defaultdict

warnings.filterwarnings('ignore')

ACCOUNT    = 70_000
TRAIL_ORB  = 0.10
COST_SCALE = 1.5

RISKS = {
    'LB_EUR':   0.004,  'LB_GBP':   0.004,
    'DAX_ORB':  0.0075, 'NAS_ORB':  0.0075, 'SP5_ORB':  0.004,
    'ASIA_EUR': 0.004,  'ASIA_GBP': 0.004,
    'LC_EUR':   0.004,  'LC_GBP':   0.004,  'LC_DAX':   0.0075,
}
COST_R_BASE = {
    'LB_EUR':   0.08,  'LB_GBP':   0.08,
    'DAX_ORB':  0.07,  'NAS_ORB':  0.06,  'SP5_ORB':  0.06,
    'ASIA_EUR': 0.08,  'ASIA_GBP': 0.08,
    'LC_EUR':   0.08,  'LC_GBP':   0.08,  'LC_DAX':   0.07,
}
CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',   'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv','NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv',
}

_cache = {}

@dataclass
class Trade:
    date: str
    pnl_raw: float
    tag: str
    dow: int

# ── Data ──────────────────────────────────────────────────────────────────────
def load_h1(key):
    if key in _cache: return _cache[key]
    fname = CSVSYMS.get(key)
    if not fname or not os.path.exists(fname):
        print(f"  MISSING: {fname} — run backtest_core6.py first")
        _cache[key] = None; return None
    df = pd.read_csv(fname)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time')[['open','high','low','close']].dropna()
    _cache[key] = df if len(df) > 200 else None
    return _cache[key]

# ── Core sim (identical to backtest_core6) ────────────────────────────────────
def sim(df, entry_pos, direction, entry, sl, max_bars=48):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0
    trail = sl_d * TRAIL_ORB; cur_sl = sl; best = entry; be = False
    last_px = entry
    for _, b in df.iloc[entry_pos+1 : entry_pos+1+max_bars].iterrows():
        last_px = b['close']
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
    return ((last_px - entry) if direction == 1 else (entry - last_px)) / sl_d

def ipos(df, ts):
    a = df.index.searchsorted(ts)
    if a >= len(df): return -1
    return int(a) if df.index[int(a)] == ts else -1

def make_trade(df, ep, direction, entry, sl, tag, ds, dow):
    r   = sim(df, ep, direction, entry, sl)
    pnl = r * RISKS[tag] * ACCOUNT
    return Trade(date=ds, pnl_raw=pnl, tag=tag, dow=dow)

def net(t):
    return t.pnl_raw - COST_R_BASE[t.tag] * COST_SCALE * RISKS[t.tag] * ACCOUNT

def stats(trades):
    if not trades: return None
    arr  = np.array([net(t) for t in trades])
    wins = arr[arr > 5]; loss = arr[arr < -5]
    if len(arr) < 20: return None
    dates = sorted(set(t.date for t in trades))
    span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    return {
        'n':   len(arr),
        'wr':  round(len(wins) / len(arr) * 100, 1),
        'pf':  round(wins.sum() / abs(loss.sum()), 2) if len(loss) else 0.0,
        'mo':  round(arr.sum() / span * 21, 0),
        'tpm': round(len(arr) / span * 21, 1),
    }

# ── ATR filter builder ────────────────────────────────────────────────────────
def build_atr_filter(df, window=20):
    """True on days where yesterday's ATR >= rolling median → trade allowed."""
    h = df['high'].resample('D').max()
    l = df['low'].resample('D').min()
    bars = df.resample('D').size()
    rng  = (h - l)[bars >= 4]           # trading days only
    med  = rng.rolling(window).median().shift(1)  # yesterday's median
    prev = rng.shift(1)                            # yesterday's range
    ok   = prev >= med
    return {str(d.date()): bool(v) for d, v in ok.items() if pd.notna(v)}

# ── Trend filter builder ──────────────────────────────────────────────────────
def build_trend_filter(df, window=20):
    """Returns +1 (uptrend) or -1 (downtrend) per day based on EMA-20 of daily closes."""
    dc   = df['close'].resample('D').last().dropna()
    ema  = dc.ewm(span=window, adjust=False).mean().shift(1)
    trend = np.sign(dc - ema)
    return {str(d.date()): int(v) for d, v in trend.items() if pd.notna(v) and v != 0}

# ── Strategy runners ──────────────────────────────────────────────────────────
def run_lb(key, tag, pip=0.0001, atr=None, trend=None):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 1: continue
        ds = str(date)
        if atr and not atr.get(ds, True): continue
        prev = day - pd.Timedelta(days=1)
        rdf  = df[(df.index >= prev + pd.Timedelta(hours=22)) &
                  (df.index <  day  + pd.Timedelta(hours=7))]
        if len(rdf) < 5: continue
        a_hi = rdf['high'].max(); a_lo = rdf['low'].min()
        rng  = a_hi - a_lo
        if not (10 <= rng / pip <= 100): continue
        buf  = rng * 0.15
        edf  = df[(df.index >= day + pd.Timedelta(hours=7)) &
                  (df.index <  day + pd.Timedelta(hours=10))]
        td   = trend.get(ds, 0) if trend else 0
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > a_hi and td >= 0:
                trades.append(make_trade(df, p, 1,  a_hi, a_lo-buf, tag, ds, day.dayofweek)); break
            if b['low']  < a_lo and td <= 0:
                trades.append(make_trade(df, p, -1, a_lo, a_hi+buf, tag, ds, day.dayofweek)); break
    return trades

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=frozenset(), atr=None):
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        ds = str(date)
        if atr and not atr.get(ds, True): continue
        rb = df[df.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue
        edf = df[(df.index >= day + pd.Timedelta(hours=es)) &
                 (df.index <  day + pd.Timedelta(hours=ee))]
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                trades.append(make_trade(df, p, 1,  rhi, rlo, tag, ds, day.dayofweek)); break
            if b['low']  < rlo:
                trades.append(make_trade(df, p, -1, rlo, rhi, tag, ds, day.dayofweek)); break
    return trades

def run_asia_orb(key, tag, pip=0.0001, rmin_pip=5, rmax_pip=60):
    """00:00-03:00 UTC range, 03:00-07:00 UTC entry. Skip Monday (weekend gap)."""
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 0: continue
        rdf = df[(df.index >= day) & (df.index < day + pd.Timedelta(hours=3))]
        if len(rdf) < 2: continue
        a_hi = rdf['high'].max(); a_lo = rdf['low'].min()
        rng  = a_hi - a_lo
        if not (rmin_pip * pip <= rng <= rmax_pip * pip): continue
        buf  = rng * 0.10
        edf  = df[(df.index >= day + pd.Timedelta(hours=3)) &
                  (df.index <  day + pd.Timedelta(hours=7))]
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > a_hi:
                trades.append(make_trade(df, p, 1,  a_hi, a_lo-buf, tag, ds, day.dayofweek)); break
            if b['low']  < a_lo:
                trades.append(make_trade(df, p, -1, a_lo, a_hi+buf, tag, ds, day.dayofweek)); break
    return trades

def run_london_close(key, tag, min_move):
    """
    At 16:00 UTC, fade the morning direction.
    Morning: 07:00 open → 15:00 close. If moved > min_move bullish → go short.
    SL: beyond the day's high/low (07:00-16:00 range).
    Exit: trail (same as ORB) or max 19:00 UTC.
    Skip Friday.
    """
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 4: continue  # no Friday

        ob = df[df.index == day + pd.Timedelta(hours=7)]
        cb = df[df.index == day + pd.Timedelta(hours=15)]
        if len(ob) == 0 or len(cb) == 0: continue

        morning_open  = ob.iloc[0]['open']
        morning_close = cb.iloc[0]['close']
        move = morning_close - morning_open
        if abs(move) < min_move: continue

        day_df   = df[(df.index >= day + pd.Timedelta(hours=7)) &
                      (df.index <= day + pd.Timedelta(hours=16))]
        if len(day_df) == 0: continue
        day_high = day_df['high'].max()
        day_low  = day_df['low'].min()
        buf      = (day_high - day_low) * 0.03

        entry_df = df[df.index == day + pd.Timedelta(hours=16)]
        if len(entry_df) == 0: continue
        p = ipos(df, day + pd.Timedelta(hours=16))
        if p < 0: continue

        entry = entry_df.iloc[0]['open']
        ds    = str(date)

        if move > min_move:
            sl = day_high + buf
            if sl <= entry: continue
            trades.append(make_trade(df, p, -1, entry, sl, tag, ds, day.dayofweek))
        else:
            sl = day_low - buf
            if sl >= entry: continue
            trades.append(make_trade(df, p, 1, entry, sl, tag, ds, day.dayofweek))
    return trades

# ── Print helpers ─────────────────────────────────────────────────────────────
DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

def row(label, trades, note=''):
    s = stats(trades)
    if not s:
        print(f"  {label:<32} —  insufficient data")
        return
    ok = '✅' if s['pf'] >= 1.5 else ('⚠ ' if s['pf'] >= 1.2 else '❌')
    print(f"  {label:<32} Tr:{s['n']:>5}  T/mo:{s['tpm']:>4.1f}  "
          f"WR:{s['wr']:>5.1f}%  PF:{s['pf']:>5.2f}  £{s['mo']:>7,.0f}/mo  {ok} {note}")

def compare(label, base, filtered, note=''):
    sb = stats(base); sf = stats(filtered)
    if not sb or not sf: return
    delta_pf = sf['pf'] - sb['pf']
    delta_mo = sf['mo'] - sb['mo']
    icon = '✅' if delta_pf > 0.05 else ('⚠ ' if delta_pf > -0.05 else '❌')
    print(f"  {label:<32} PF {sb['pf']:.2f}→{sf['pf']:.2f} ({delta_pf:+.2f})  "
          f"£/mo {sb['mo']:,.0f}→{sf['mo']:,.0f} ({delta_mo:+,.0f})  "
          f"Tr {sb['n']}→{sf['n']}  {icon} {note}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 74

    print("\n" + "=" * W)
    print("  STRATEGY RESEARCH LAB  —  8-year MT5 H1 data")
    print("=" * W)

    # Pre-load all data
    print("\n  Loading data...")
    for k in CSVSYMS: load_h1(k)
    print("  Done.\n")

    # ── Run base strategies ───────────────────────────────────────────────────
    print("  Running base strategies...")
    base = {
        'LB_EUR':  run_lb('EURUSD',  'LB_EUR'),
        'LB_GBP':  run_lb('GBPUSD',  'LB_GBP'),
        'DAX_ORB': run_orb('DAX',    'DAX_ORB', 8,  9, 12,  30,  300),
        'NAS_ORB': run_orb('NAS100', 'NAS_ORB', 13, 14, 16,  50, 1500, {0}),
        'SP5_ORB': run_orb('SP500',  'SP5_ORB', 13, 14, 16,   5,  300, {0}),
    }
    print("  Done.\n")

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. ATR VOLATILITY FILTER
    # ═══════════════════════════════════════════════════════════════════════════
    print("=" * W)
    print("  1. ATR VOLATILITY FILTER  (trade only above-median ATR days)")
    print("=" * W + "\n")

    atrf = {
        'EURUSD': build_atr_filter(load_h1('EURUSD')),
        'GBPUSD': build_atr_filter(load_h1('GBPUSD')),
        'DAX':    build_atr_filter(load_h1('DAX')),
        'NAS100': build_atr_filter(load_h1('NAS100')),
        'SP500':  build_atr_filter(load_h1('SP500')),
    }

    atr_filtered = {
        'LB_EUR':  run_lb('EURUSD',  'LB_EUR',  atr=atrf['EURUSD']),
        'LB_GBP':  run_lb('GBPUSD',  'LB_GBP',  atr=atrf['GBPUSD']),
        'DAX_ORB': run_orb('DAX',    'DAX_ORB', 8, 9,  12,  30,  300,    atr=atrf['DAX']),
        'NAS_ORB': run_orb('NAS100', 'NAS_ORB', 13,14, 16,  50, 1500,{0},atr=atrf['NAS100']),
        'SP5_ORB': run_orb('SP500',  'SP5_ORB', 13,14, 16,   5,  300,{0},atr=atrf['SP500']),
    }

    for tag in ['LB_EUR','LB_GBP','DAX_ORB','NAS_ORB','SP5_ORB']:
        compare(tag, base[tag], atr_filtered[tag])

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. TREND DIRECTION FILTER ON LB
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * W}")
    print("  2. TREND DIRECTION FILTER ON LB  (EMA-20 daily, only trade with trend)")
    print("=" * W + "\n")

    trendf = {
        'EURUSD': build_trend_filter(load_h1('EURUSD')),
        'GBPUSD': build_trend_filter(load_h1('GBPUSD')),
    }

    variants = {
        'LB_EUR trend only':     run_lb('EURUSD','LB_EUR', trend=trendf['EURUSD']),
        'LB_EUR ATR+trend':      run_lb('EURUSD','LB_EUR', atr=atrf['EURUSD'], trend=trendf['EURUSD']),
        'LB_GBP trend only':     run_lb('GBPUSD','LB_GBP', trend=trendf['GBPUSD']),
        'LB_GBP ATR+trend':      run_lb('GBPUSD','LB_GBP', atr=atrf['GBPUSD'], trend=trendf['GBPUSD']),
    }

    compare('LB_EUR base→trend',     base['LB_EUR'], variants['LB_EUR trend only'])
    compare('LB_EUR base→ATR+trend', base['LB_EUR'], variants['LB_EUR ATR+trend'])
    compare('LB_GBP base→trend',     base['LB_GBP'], variants['LB_GBP trend only'])
    compare('LB_GBP base→ATR+trend', base['LB_GBP'], variants['LB_GBP ATR+trend'])

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. DAY-OF-WEEK BREAKDOWN
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * W}")
    print("  3. DAY-OF-WEEK BREAKDOWN  (find which days to skip)")
    print("=" * W)

    for tag in ['LB_EUR','LB_GBP','DAX_ORB','NAS_ORB','SP5_ORB']:
        print(f"\n  {tag}:")
        print(f"  {'Day':<6} {'Tr':>5} {'WR%':>6} {'PF':>6} {'£/mo':>8}")
        print("  " + "─" * 35)
        for dow in range(5):
            dt = [t for t in base[tag] if t.dow == dow]
            s  = stats(dt)
            if not s: print(f"  {DOW[dow]:<6}  no data"); continue
            ok = '✅' if s['pf'] >= 1.4 else ('⚠ ' if s['pf'] >= 1.0 else '❌')
            print(f"  {DOW[dow]:<6} {s['n']:>5} {s['wr']:>5.1f}% {s['pf']:>6.2f} "
                  f"£{s['mo']:>7,.0f}  {ok}")

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. ASIA ORB
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * W}")
    print("  4. ASIA ORB  (00:00-03:00 UTC range → 03:00-07:00 entry)")
    print("  Tokyo/Asian banks set tight range, London order flow breaks it.")
    print("=" * W + "\n")

    asia_eur = run_asia_orb('EURUSD', 'ASIA_EUR')
    asia_gbp = run_asia_orb('GBPUSD', 'ASIA_GBP')

    row('ASIA_EUR (EURUSD)',         asia_eur)
    row('ASIA_GBP (GBPUSD)',         asia_gbp)
    row('ASIA combined',             asia_eur + asia_gbp)

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. LONDON CLOSE REVERSAL
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * W}")
    print("  5. LONDON CLOSE REVERSAL  (16:00 UTC — fade morning direction)")
    print("  London desks unwind at close → partial reversal of morning trend.")
    print("=" * W + "\n")

    lc_eur = run_london_close('EURUSD', 'LC_EUR', min_move=0.0020)
    lc_gbp = run_london_close('GBPUSD', 'LC_GBP', min_move=0.0025)
    lc_dax = run_london_close('DAX',    'LC_DAX', min_move=30.0)

    row('LC_EUR  (EURUSD, 20pip min)', lc_eur)
    row('LC_GBP  (GBPUSD, 25pip min)', lc_gbp)
    row('LC_DAX  (GER40,  30pt  min)', lc_dax)

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. BEST PORTFOLIO SUMMARY
    # ═══════════════════════════════════════════════════════════════════════════
    print(f"\n{'=' * W}")
    print("  6. FULL CANDIDATE RANKING  (all strategies, all variants)")
    print("=" * W + "\n")

    candidates = [
        ('DAX_ORB  (base)',          base['DAX_ORB']),
        ('SP5_ORB  (base)',          base['SP5_ORB']),
        ('DAX_ORB  (ATR filter)',    atr_filtered['DAX_ORB']),
        ('SP5_ORB  (ATR filter)',    atr_filtered['SP5_ORB']),
        ('NAS_ORB  (base)',          base['NAS_ORB']),
        ('NAS_ORB  (ATR filter)',    atr_filtered['NAS_ORB']),
        ('LB_EUR   (base)',          base['LB_EUR']),
        ('LB_EUR   (trend)',         variants['LB_EUR trend only']),
        ('LB_EUR   (ATR+trend)',     variants['LB_EUR ATR+trend']),
        ('LB_GBP   (base)',          base['LB_GBP']),
        ('LB_GBP   (trend)',         variants['LB_GBP trend only']),
        ('LB_GBP   (ATR+trend)',     variants['LB_GBP ATR+trend']),
        ('ASIA_EUR',                 asia_eur),
        ('ASIA_GBP',                 asia_gbp),
        ('LC_EUR',                   lc_eur),
        ('LC_GBP',                   lc_gbp),
        ('LC_DAX',                   lc_dax),
    ]

    include = []
    print(f"  {'Strategy':<32} {'Tr':>5}  {'T/mo':>4}  {'WR':>6}  {'PF':>6}  {'£/mo':>8}  Verdict")
    print("  " + "─" * (W - 2))
    for name, trades in candidates:
        s = stats(trades)
        if not s:
            print(f"  {name:<32} —  insufficient data"); continue
        if s['pf'] >= 1.5:
            verdict = '✅ INCLUDE'
            include.append((name, trades))
        elif s['pf'] >= 1.3:
            verdict = '⚠  MAYBE'
        else:
            verdict = '❌ SKIP'
        print(f"  {name:<32} {s['n']:>5}  {s['tpm']:>4.1f}  {s['wr']:>5.1f}%  "
              f"{s['pf']:>6.2f}  £{s['mo']:>7,.0f}  {verdict}")

    # Best combined
    if include:
        all_t = []
        for _, t in include: all_t += t
        s = stats(all_t)
        if s:
            print(f"\n  ── Best combined ({len(include)} strategies) ──")
            print(f"  Trades/mo: {s['tpm']:.1f}  |  WR: {s['wr']:.1f}%  |  "
                  f"PF: {s['pf']:.2f}  |  £/mo: £{s['mo']:,.0f}")
