"""
backtest_core6.py  —  Focused backtest: 6 core ORB/LB strategies only
Uses MT5 Python API — pulls real broker H1 data directly from your running MT5 terminal.

  1. NAS_ORB   US100.cash  14:00-16:00 UTC  Tue-Fri  0.75% risk
  2. SP5_ORB   US500.cash  14:00-16:00 UTC  Tue-Fri  0.40% risk
  3. DAX_ORB   GER40.cash  09:00-12:00 UTC  all days 0.75% risk
  4. NG_ORB    XNGUSD      14:00-16:00 UTC  all days 0.75% risk  (removed from live bot)
  5. LB_EUR    EURUSD      07:00-10:00 UTC  skip Tue 0.40% risk
  6. LB_GBP    GBPUSD      07:00-10:00 UTC  skip Tue 0.40% risk

Requirements:
  pip install MetaTrader5 pandas numpy
  MT5 must be running and logged into your account before you run this.

Outputs:
  A. Full 2-year stats at 1.0x / 1.5x / 2.0x spread costs
  B. Quarterly P&L breakdown (consistency check)
  C. Per-strategy breakdown
  D. Walk-forward IS vs OOS + rolling 6-split walk-forward
  E. Monthly P&L chart
  F. Monthly distribution stats
  G. FTMO Phase 1 Monte Carlo (10,000 sims, no time limit)
"""

import pandas as pd
import numpy as np
import warnings
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

# Auto-detect data source: MT5 if available and running, else yfinance
try:
    import MetaTrader5 as mt5
    USE_MT5 = mt5.initialize()
    if not USE_MT5:
        mt5 = None
        print("  MT5 not available — falling back to yfinance")
except ImportError:
    mt5 = None
    USE_MT5 = False

if not USE_MT5:
    import yfinance as yf

# ── Config ────────────────────────────────────────────────────────────────────
ACCOUNT    = 70_000
TRAIL_ORB  = 0.10    # trail after 1R BE, 0.1R distance — matches live EA
COST_SCALE = 1.5

RISKS = {
    'LB_EUR':  0.004,
    'LB_GBP':  0.004,
    'DAX_ORB': 0.0075,
    'NAS_ORB': 0.0075,
    'SP5_ORB': 0.004,
    'NG_ORB':  0.0075,
}

COST_R_BASE = {   # spread + slippage per trade in R at 1.0x
    'LB_EUR':  0.08,
    'LB_GBP':  0.08,
    'DAX_ORB': 0.07,
    'NAS_ORB': 0.06,
    'SP5_ORB': 0.06,
    'NG_ORB':  0.06,
}

# MT5 symbol names — adjust if your broker uses different names
MT5SYMS = {
    'EURUSD': 'EURUSD',
    'GBPUSD': 'GBPUSD',
    'DAX':    'GER40.cash',
    'NAS100': 'US100.cash',
    'SP500':  'US500.cash',
    'NATGAS': 'XNGUSD',
}

# CSV filenames produced by ExportH1Data.mq5
CSVSYMS = {
    'EURUSD': 'EURUSD_H1.csv',
    'GBPUSD': 'GBPUSD_H1.csv',
    'DAX':    'GER40_cash_H1.csv',
    'NAS100': 'US100_cash_H1.csv',
    'SP500':  'US500_cash_H1.csv',
    'NATGAS': 'XNGUSD_H1.csv',
}

YFSYMS = {
    'EURUSD': 'EURUSD=X',
    'GBPUSD': 'GBPUSD=X',
    'DAX':    '^GDAXI',
    'NAS100': 'NQ=F',
    'SP500':  'ES=F',
    'NATGAS': 'NG=F',
}

WF_SPLIT = pd.Timestamp('2025-01-01', tz='UTC')
H1_BARS  = 25_000   # enough for 3+ years of H1 data on any instrument

# ── Trade dataclass ────────────────────────────────────────────────────────────
@dataclass
class Trade:
    date: str
    pnl_raw: float
    tag: str

# ── MT5 data loading ──────────────────────────────────────────────────────────
_cache = {}

def _load_from_csv(key):
    import os
    fname = CSVSYMS.get(key)
    if not fname or not os.path.exists(fname):
        return None
    try:
        df = pd.read_csv(fname)
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
        df = df.set_index('time')[['open', 'high', 'low', 'close']].dropna()
        if len(df) < 200:
            return None
        print(f"    {fname}: {len(df):,} H1 bars  "
              f"({df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')})  [CSV]")
        return df
    except Exception as e:
        print(f"    WARNING: failed to read {fname} — {e}")
        return None

def load_h1(key):
    if key in _cache:
        return _cache[key]

    # Priority 1: CSV files exported from MT5 (6 years, any platform)
    df = _load_from_csv(key)

    # Priority 2: Live MT5 connection (Windows only)
    if df is None and USE_MT5:
        sym = MT5SYMS.get(key)
        if sym:
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H1, 0, H1_BARS)
            if rates is not None and len(rates) >= 200:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
                df = df.set_index('time')[['open', 'high', 'low', 'close']].dropna()
                print(f"    {sym}: {len(df):,} H1 bars  "
                      f"({df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')})  [MT5]")
            else:
                print(f"    WARNING: {sym} — no MT5 data. Add to Market Watch.")

    # Priority 3: yfinance fallback (2 years, any platform)
    if df is None and not USE_MT5:
        sym = YFSYMS.get(key)
        if sym:
            try:
                raw = yf.download(sym, interval='1h', period='730d',
                                  auto_adjust=True, progress=False)
                if isinstance(raw.columns, pd.MultiIndex):
                    raw.columns = raw.columns.get_level_values(0)
                raw.columns = [c.lower() for c in raw.columns]
                raw = raw.dropna()
                if raw.index.tz is None: raw.index = raw.index.tz_localize('UTC')
                else:                    raw.index = raw.index.tz_convert('UTC')
                if len(raw) >= 200:
                    df = raw
                    print(f"    {sym}: {len(df):,} H1 bars  "
                          f"({df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')})  [yfinance]")
            except Exception as e:
                print(f"    WARNING: {sym} yfinance failed — {e}")

    if df is None:
        print(f"    SKIP: {key} — no data from any source")

    _cache[key] = df
    return df

def calc_atr(df, p=14):
    h = df['high']; l = df['low']; pc = df['close'].shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=p, adjust=False).mean()

# ── Trade simulator (trail activates after 1R BE — matches live EA) ───────────
def sim(df, entry_pos, direction, entry, sl, max_bars=48):
    sl_d = abs(entry - sl)
    if sl_d <= 0: return 0.0
    trail  = sl_d * TRAIL_ORB
    cur_sl = sl
    best   = entry
    be     = False
    bars   = df.iloc[entry_pos + 1 : entry_pos + 1 + max_bars]
    last_px = entry
    for _, b in bars.iterrows():
        last_px = b['close']
        if direction == 1:
            if b['low'] <= cur_sl: return (cur_sl - entry) / sl_d
            best = max(best, b['high'])
            if not be and best >= entry + sl_d:
                be = True; cur_sl = entry
            if be:
                ns = best - trail
                if ns > cur_sl: cur_sl = ns
        else:
            if b['high'] >= cur_sl: return (entry - cur_sl) / sl_d
            best = min(best, b['low'])
            if not be and best <= entry - sl_d:
                be = True; cur_sl = entry
            if be:
                ns = best + trail
                if ns < cur_sl: cur_sl = ns
    pts = (last_px - entry) if direction == 1 else (entry - last_px)
    return pts / sl_d

def ipos(df, ts):
    arr = df.index.searchsorted(ts)
    if arr >= len(df): return -1
    return int(arr) if df.index[int(arr)] == ts else -1

def make_trade(df, entry_pos, direction, entry, sl, risk_pct, tag, date_str):
    r   = sim(df, entry_pos, direction, entry, sl)
    pnl = r * risk_pct * ACCOUNT
    return Trade(date=date_str, pnl_raw=pnl, tag=tag)

# ── Strategy functions ────────────────────────────────────────────────────────
def run_lb(key, tag, pip=0.0001):
    """London Breakout — skip Tuesday, enter at breakout of Asian range."""
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek == 1: continue  # skip Tuesday
        prev = day - pd.Timedelta(days=1)
        rng_df = df[(df.index >= prev + pd.Timedelta(hours=22)) &
                    (df.index <  day  + pd.Timedelta(hours=7))]
        if len(rng_df) < 5: continue
        a_hi = rng_df['high'].max(); a_lo = rng_df['low'].min()
        rng  = a_hi - a_lo
        if not (10 <= rng / pip <= 100): continue
        buf  = rng * 0.15
        edf  = df[(df.index >= day + pd.Timedelta(hours=7)) &
                  (df.index <  day + pd.Timedelta(hours=10))]
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > a_hi:
                trades.append(make_trade(df, p, 1,  a_hi, a_lo - buf, RISKS[tag], tag, ds)); break
            if b['low']  < a_lo:
                trades.append(make_trade(df, p, -1, a_lo, a_hi + buf, RISKS[tag], tag, ds)); break
    return trades

def run_orb(key, tag, ref_h, es, ee, rmin, rmax, skip_dow=frozenset()):
    """Opening Range Breakout — enter at range high/low during entry window."""
    df = load_h1(key)
    if df is None: return []
    trades = []
    for date in sorted(set(df.index.normalize().date)):
        day = pd.Timestamp(date, tz='UTC')
        if day.dayofweek in skip_dow: continue
        rb = df[df.index == day + pd.Timedelta(hours=ref_h)]
        if len(rb) == 0: continue
        rhi = rb.iloc[0]['high']; rlo = rb.iloc[0]['low']
        if not (rmin <= rhi - rlo <= rmax): continue
        edf = df[(df.index >= day + pd.Timedelta(hours=es)) &
                 (df.index <  day + pd.Timedelta(hours=ee))]
        ds = str(date)
        for j in range(len(edf)):
            b = edf.iloc[j]; p = ipos(df, edf.index[j])
            if p < 0: continue
            if b['high'] > rhi:
                trades.append(make_trade(df, p, 1,  rhi, rlo, RISKS[tag], tag, ds)); break
            if b['low']  < rlo:
                trades.append(make_trade(df, p, -1, rlo, rhi, RISKS[tag], tag, ds)); break
    return trades

# ── Portfolio ─────────────────────────────────────────────────────────────────
_RAW = None

def get_raw():
    global _RAW
    if _RAW is not None: return _RAW
    print("  Loading data from MT5 and running strategies...")
    raw = []
    raw += run_lb('EURUSD',  'LB_EUR');              print("    LB_EUR done")
    raw += run_lb('GBPUSD',  'LB_GBP');              print("    LB_GBP done")
    raw += run_orb('DAX',    'DAX_ORB', 8, 9,  12, 30,  300);       print("    DAX_ORB done")
    raw += run_orb('NAS100', 'NAS_ORB', 13,14, 16, 50, 1500, {0});  print("    NAS_ORB done")
    raw += run_orb('SP500',  'SP5_ORB', 13,14, 16,  5,  300, {0});  print("    SP5_ORB done")
    raw += run_orb('NATGAS', 'NG_ORB',  13,14, 16, 0.03, 1.0);      print("    NG_ORB done (removed from live bot)")
    _RAW = raw
    print(f"  Total raw trades: {len(raw):,}\n")
    return raw

def apply_cost(trade):
    base = COST_R_BASE[trade.tag]
    cost = base * COST_SCALE * RISKS[trade.tag] * ACCOUNT
    return trade.pnl_raw - cost

def get_pnls(date_from=None, date_to=None):
    raw = get_raw()
    df  = str(date_from.date()) if date_from else None
    dt  = str(date_to.date())   if date_to   else None
    out = []
    for t in raw:
        if df and t.date < df: continue
        if dt and t.date >= dt: continue
        out.append((t.date, t.tag, apply_cost(t)))
    return out

def stats(pnls):
    if not pnls: return None
    arr   = np.array([p for _, _, p in pnls])
    wins  = arr[arr >  5]
    loss  = arr[arr < -5]
    dates = sorted(set(d for d, _, _ in pnls))
    span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
    mo    = arr.sum() / span * 21
    pf    = wins.sum() / abs(loss.sum()) if len(loss) else 0.0
    wr    = len(wins) / len(arr) * 100
    return {
        'n': len(arr), 'wr': round(wr, 1), 'pf': round(pf, 2),
        'mo': round(mo, 0), 'total': round(arr.sum(), 0),
        'avg_w': round(wins.mean(), 0) if len(wins) else 0,
        'avg_l': round(abs(loss.mean()), 0) if len(loss) else 0,
        'tpm': round(len(arr) / span * 21, 1),
        'arr': arr,
    }

# ── Max drawdown ──────────────────────────────────────────────────────────────
def max_drawdown(pnls):
    equity = ACCOUNT + np.cumsum([p for _, _, p in sorted(pnls)])
    peak   = np.maximum.accumulate(equity)
    dd     = peak - equity
    max_dd = dd.max()
    max_dd_pct = max_dd / peak[np.argmax(dd)] * 100
    return round(max_dd, 0), round(max_dd_pct, 2)

# ── Sharpe (annualised) ───────────────────────────────────────────────────────
def sharpe(pnls):
    by_day = defaultdict(float)
    for d, _, p in pnls: by_day[d] += p
    daily = np.array(list(by_day.values()))
    if daily.std() == 0: return 0.0
    return round((daily.mean() / daily.std()) * (252 ** 0.5), 2)

# ── FTMO Monte Carlo ──────────────────────────────────────────────────────────
def ftmo_monte_carlo(pnls, n_sim=10_000, phase1_target=7_000,
                     daily_limit=3_500, total_limit=7_000, max_days=None):
    by_day = defaultdict(float)
    for d, _, p in pnls: by_day[d] += p
    daily_pnls = np.array(list(by_day.values()))

    cap   = max_days if max_days else 500
    rng   = np.random.default_rng(42)
    pass_count = bust_count = running_count = 0

    for _ in range(n_sim):
        equity = ACCOUNT
        peak   = ACCOUNT
        passed = busted = False
        for day_pnl in rng.choice(daily_pnls, size=cap, replace=True):
            if day_pnl < -daily_limit:
                busted = True; break
            equity += day_pnl
            peak    = max(peak, equity)
            if peak - equity > total_limit:
                busted = True; break
            if equity - ACCOUNT >= phase1_target:
                passed = True; break
        if   busted: bust_count    += 1
        elif passed: pass_count    += 1
        else:        running_count += 1

    return (pass_count / n_sim * 100, bust_count / n_sim * 100, running_count / n_sim * 100)

# ── Text bar chart ────────────────────────────────────────────────────────────
def bar_chart(monthly_dict, width=40):
    if not monthly_dict: return
    vals    = list(monthly_dict.values())
    max_abs = max(abs(v) for v in vals) if vals else 1
    print()
    for month, val in sorted(monthly_dict.items()):
        bar_len = int(abs(val) / max_abs * width)
        bar     = ('█' * bar_len) if val >= 0 else ('░' * bar_len)
        sign    = '+' if val >= 0 else '-'
        print(f"  {month}  {sign}£{abs(val):>6,.0f}  {bar}")

# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    W = 68

    print("\n" + "=" * W)
    print("  6botV2 — CORE 5 STRATEGY BACKTEST  (MT5 data)")
    print("  NAS_ORB · SP5_ORB · DAX_ORB · LB_EUR · LB_GBP")
    print("=" * W + "\n")

    if USE_MT5:
        info = mt5.account_info()
        if info:
            print(f"  Data source: MT5 — {info.name} | {info.server} | Balance: {info.balance:.2f} {info.currency}\n")
        else:
            print("  Data source: MT5 (connected)\n")
    else:
        print("  Data source: yfinance (MT5 not available)\n")

    _ = get_raw()   # populate cache

    # ── A. Cost scenario comparison ───────────────────────────────────────────
    print("=" * W)
    print("  A. FULL RESULTS BY COST SCENARIO")
    print("=" * W)
    print(f"\n  {'Scenario':<22}  {'Tr':>5}  {'T/mo':>5}  {'WR%':>5}  "
          f"{'PF':>5}  {'AvgW':>6}  {'AvgL':>6}  {'£/mo':>7}  {'MaxDD':>8}")
    print("  " + "─" * (W - 2))

    for scale, label in [(1.0, '1.0x optimistic'), (1.5, '1.5x realistic'), (2.0, '2.0x conservative')]:
        COST_SCALE = scale
        p  = get_pnls()
        s  = stats(p)
        dd, dd_pct = max_drawdown(p)
        print(f"  {label:<22}  {s['n']:>5,}  {s['tpm']:>5.1f}  {s['wr']:>5.1f}%  "
              f"{s['pf']:>5.2f}  £{s['avg_w']:>5,}  £{s['avg_l']:>5,}  "
              f"£{s['mo']:>6,}  £{dd:>7,} ({dd_pct:.1f}%)")

    # ── B. Quarterly breakdown ────────────────────────────────────────────────
    COST_SCALE = 1.5
    print(f"\n{'=' * W}")
    print("  B. QUARTERLY BREAKDOWN  (1.5x costs — consistency check)")
    print(f"{'=' * W}")
    print(f"\n  {'Quarter':<14}  {'Tr':>4}  {'WR%':>5}  {'PF':>5}  "
          f"{'£/mo':>7}  {'P&L':>8}")
    print("  " + "─" * (W - 2))

    quarters = [
        ('Q3 2023',   pd.Timestamp('2023-07-01', tz='UTC'), pd.Timestamp('2023-10-01', tz='UTC')),
        ('Q4 2023',   pd.Timestamp('2023-10-01', tz='UTC'), pd.Timestamp('2024-01-01', tz='UTC')),
        ('Q1 2024',   pd.Timestamp('2024-01-01', tz='UTC'), pd.Timestamp('2024-04-01', tz='UTC')),
        ('Q2 2024',   pd.Timestamp('2024-04-01', tz='UTC'), pd.Timestamp('2024-07-01', tz='UTC')),
        ('Q3 2024',   pd.Timestamp('2024-07-01', tz='UTC'), pd.Timestamp('2024-10-01', tz='UTC')),
        ('Q4 2024',   pd.Timestamp('2024-10-01', tz='UTC'), pd.Timestamp('2025-01-01', tz='UTC')),
        ('Q1 2025',   pd.Timestamp('2025-01-01', tz='UTC'), pd.Timestamp('2025-04-01', tz='UTC')),
        ('Q2 2025',   pd.Timestamp('2025-04-01', tz='UTC'), pd.Timestamp('2025-07-01', tz='UTC')),
        ('Q3 2025',   pd.Timestamp('2025-07-01', tz='UTC'), pd.Timestamp('2025-10-01', tz='UTC')),
        ('Q4 2025',   pd.Timestamp('2025-10-01', tz='UTC'), pd.Timestamp('2026-01-01', tz='UTC')),
        ('Q1/2 2026', pd.Timestamp('2026-01-01', tz='UTC'), None),
    ]

    for qname, qfrom, qto in quarters:
        p = get_pnls(date_from=qfrom, date_to=qto)
        if not p: continue
        s = stats(p)
        if s['n'] < 10: continue
        tag = '✅' if s['pf'] >= 1.4 else ('⚠ ' if s['pf'] >= 1.0 else '❌')
        print(f"  {qname:<14}  {s['n']:>4}  {s['wr']:>5.1f}%  "
              f"{s['pf']:>5.2f}  £{s['mo']:>6,}  £{s['total']:>7,}  {tag}")

    # ── C. Per-strategy breakdown ─────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  C. PER-STRATEGY  (1.5x costs, full history)")
    print(f"{'=' * W}")
    print(f"\n  {'Strategy':<12}  {'Tr':>4}  {'WR%':>5}  {'PF':>5}  "
          f"{'AvgW':>6}  {'AvgL':>6}  {'£/mo':>7}")
    print("  " + "─" * (W - 2))

    COST_SCALE = 1.5
    all_p  = get_pnls()
    by_tag = defaultdict(list)
    for d, tag, pnl in all_p:
        by_tag[tag].append((d, pnl))

    for tag in ['NAS_ORB', 'SP5_ORB', 'DAX_ORB', 'LB_EUR', 'LB_GBP', 'NG_ORB']:
        rows = by_tag[tag]
        if not rows: continue
        arr  = np.array([p for _, p in rows])
        wins = arr[arr >  5]; loss = arr[arr < -5]
        dates = sorted(set(d for d, _ in rows))
        span  = max((pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days, 1)
        mo    = arr.sum() / span * 21
        pf    = wins.sum() / abs(loss.sum()) if len(loss) else 0.0
        wr    = len(wins) / len(arr) * 100
        ok    = '✅' if pf >= 1.5 else ('⚠ ' if pf >= 1.2 else '❌')
        note  = ' (removed from live)' if tag == 'NG_ORB' else ''
        print(f"  {tag:<12}  {len(arr):>4}  {wr:>5.1f}%  {pf:>5.2f}  "
              f"£{round(wins.mean()):>5,}  £{round(abs(loss.mean())):>5,}  "
              f"£{round(mo):>6,}  {ok}{note}")

    # ── D. Walk-forward IS vs OOS ─────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  D. WALK-FORWARD  IS (pre-Jan 2025)  vs  OOS (Jan 2025+)  [1.5x]")
    print(f"{'=' * W}")

    COST_SCALE = 1.5
    si   = stats(get_pnls(date_to=WF_SPLIT))
    so   = stats(get_pnls(date_from=WF_SPLIT))
    sh_i = sharpe(get_pnls(date_to=WF_SPLIT))
    sh_o = sharpe(get_pnls(date_from=WF_SPLIT))

    print(f"\n  {'Metric':<20}  {'In-Sample':>14}  {'Out-of-Sample':>14}")
    print("  " + "─" * (W - 2))
    for label, vi, vo in [
        ('Trades',        f"{si['n']:,}",      f"{so['n']:,}"),
        ('Win Rate',      f"{si['wr']:.1f}%",  f"{so['wr']:.1f}%"),
        ('Profit Factor', f"{si['pf']:.2f}",   f"{so['pf']:.2f}"),
        ('Avg Win',       f"£{si['avg_w']:,}", f"£{so['avg_w']:,}"),
        ('Avg Loss',      f"£{si['avg_l']:,}", f"£{so['avg_l']:,}"),
        ('£/month',       f"£{si['mo']:,}",    f"£{so['mo']:,}"),
        ('Sharpe',        f"{sh_i}",           f"{sh_o}"),
    ]:
        print(f"  {label:<20}  {vi:>14}  {vo:>14}")

    ratio   = so['pf'] / si['pf'] * 100 if si['pf'] > 0 else 0
    verdict = ('✅ HOLDS WELL (>80%)'  if ratio >= 80 else
               '⚠  MODERATE (60-80%)' if ratio >= 60 else
               '❌ DEGRADED (<60%)')
    print(f"\n  OOS/IS PF ratio: {ratio:.0f}%  →  {verdict}")

    # ── D2. Rolling walk-forward ──────────────────────────────────────────────
    COST_SCALE = 1.5
    print(f"\n{'=' * W}")
    print("  D2. ROLLING WALK-FORWARD  (6 split dates, 1.5x costs)")
    print("  OOS PF >1.3 across ALL splits = structural edge, not overfitting.")
    print(f"{'=' * W}")
    print(f"\n  {'Split date':<14}  {'IS trades':>9}  {'IS PF':>6}  "
          f"{'OOS trades':>10}  {'OOS PF':>7}  {'Ratio':>6}  {'Hold?'}")
    print("  " + "─" * (W - 2))

    split_dates = [
        '2023-07-01', '2024-01-01', '2024-07-01',
        '2024-10-01', '2025-01-01', '2025-07-01',
    ]
    all_pass = True
    for sd in split_dates:
        sp = pd.Timestamp(sd, tz='UTC')
        pi = stats(get_pnls(date_to=sp))
        po = stats(get_pnls(date_from=sp))
        if not pi or not po or pi['n'] < 50 or po['n'] < 50:
            print(f"  {sd:<14}  (insufficient data)")
            continue
        r  = po['pf'] / pi['pf'] * 100 if pi['pf'] > 0 else 0
        ok = ('✅' if po['pf'] >= 1.3 else ('⚠ ' if po['pf'] >= 1.1 else '❌'))
        if po['pf'] < 1.3: all_pass = False
        print(f"  {sd:<14}  {pi['n']:>9,}  {pi['pf']:>6.2f}  "
              f"{po['n']:>10,}  {po['pf']:>7.2f}  {r:>5.0f}%  {ok}")

    conclusion = ("✅ Edge is consistent across all splits — structural"
                  if all_pass else
                  "⚠  Edge varies by period — some splits show weakness")
    print(f"\n  → {conclusion}")

    # ── E. Monthly P&L chart ──────────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  E. MONTHLY P&L  (1.5x costs, all strategies)")
    print(f"{'=' * W}")

    COST_SCALE = 1.5
    monthly = defaultdict(float)
    for d, _, pnl in get_pnls():
        monthly[d[:7]] += pnl
    bar_chart(monthly)
    pos_months = sum(1 for v in monthly.values() if v > 0)
    neg_months = sum(1 for v in monthly.values() if v <= 0)
    print(f"\n  Positive months: {pos_months}  |  Negative months: {neg_months}  "
          f"|  Hit rate: {pos_months / (pos_months + neg_months) * 100:.0f}%")

    # ── F. Monthly distribution ───────────────────────────────────────────────
    COST_SCALE = 1.5
    print(f"\n{'=' * W}")
    print("  F. MONTHLY DISTRIBUTION  (variance explanation)")
    print(f"{'=' * W}")

    mo_arr = np.array(sorted(monthly.values()))
    print(f"""
  Variance is a feature of breakout strategies, not a bug:
  Most days are quiet (market stays inside ORB range, small SL or scratch).
  A few times per month a big macro/news event drives a 200-400pt NAS move
  and the trail rides it for £1,000-3,000+ in a single session.
  This produces lumpy monthly returns — quiet months then monster months.

  Monthly stats (1.5x costs, {len(mo_arr)} months):
    Median:           £{np.median(mo_arr):>8,.0f}
    Average:          £{np.mean(mo_arr):>8,.0f}
    Best month:       £{np.max(mo_arr):>8,.0f}
    Worst month:      £{np.min(mo_arr):>8,.0f}
    Std deviation:    £{np.std(mo_arr):>8,.0f}
    Months above £0:  {sum(1 for v in mo_arr if v > 0) / len(mo_arr) * 100:.0f}%
    Months above £3k: {sum(1 for v in mo_arr if v > 3000) / len(mo_arr) * 100:.0f}%
    Months above £8k: {sum(1 for v in mo_arr if v > 8000) / len(mo_arr) * 100:.0f}%

  For FTMO with NO time limit: variance works FOR you.
  You keep running until a strong period pushes past +£7,000.
  Only risk is drawdown hitting -£7,000 from peak first.
""")

    # ── G. FTMO Monte Carlo ───────────────────────────────────────────────────
    print(f"{'=' * W}")
    print("  G. FTMO PHASE 1  —  NO TIME LIMIT  (10,000 sims, 1.5x costs)")
    print("  Runs until +£7,000 profit  OR  daily/total loss limits hit")
    print(f"{'=' * W}")

    COST_SCALE = 1.5
    p15      = get_pnls()
    dd15, _  = max_drawdown(p15)
    s15      = stats(p15)
    sh15     = sharpe(p15)
    pass_f, bust_f, run_f = ftmo_monte_carlo(p15, max_days=None)

    p_oos = get_pnls(date_from=WF_SPLIT)
    s_oos = stats(p_oos)
    pass_o, bust_o, run_o = ftmo_monte_carlo(p_oos, max_days=None)

    print(f"""
  Full data ({s15['n']:,} trades, PF {s15['pf']}, MaxDD £{dd15:,}):
  ┌─────────────────────────────────────────────────┐
  │  Pass (hit +£7k profit):        {pass_f:>5.1f}%          │
  │  Bust (hit loss limit):          {bust_f:>5.1f}%          │
  │  Still running at 500-day cap:   {run_f:>5.1f}%          │
  │  Eventual pass rate:            {pass_f / (pass_f + bust_f) * 100:>5.1f}%          │
  └─────────────────────────────────────────────────┘

  OOS only ({s_oos['n']:,} trades, PF {s_oos['pf']}) — most honest:
  ┌─────────────────────────────────────────────────┐
  │  Pass (hit +£7k profit):        {pass_o:>5.1f}%          │
  │  Bust (hit loss limit):          {bust_o:>5.1f}%          │
  │  Still running at 500-day cap:   {run_o:>5.1f}%          │
  │  Eventual pass rate:            {pass_o / (pass_o + bust_o) * 100:>5.1f}%          │
  └─────────────────────────────────────────────────┘
  Expected attempts needed: {1 / (pass_o / (pass_o + bust_o)):.2f}

  VERDICT:
    >90% eventual pass rate  →  Pay £489. Expected to pass first attempt.
    70-90%                   →  Pay, might need one retry.
    <70%                     →  More live validation first.
""")

    if USE_MT5:
        mt5.shutdown()
        print("  MT5 connection closed.\n")
