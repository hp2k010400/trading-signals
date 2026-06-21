"""
backtest_m30_mt5.py — M30 ORB on 2 YEARS of data via MetaTrader5

Bypasses yfinance's 60-day limit on 30-min data by pulling directly
from MT5 broker history.

MT5 must be OPEN and logged into your FTMO account before running.

Symbols tested (FTMO naming):
  GER40.cash, UK100.cash, US100.cash, US500.cash, XNGUSD, EURUSD, GBPUSD

Same ORB logic as backtest_new_strategies.py — first M30 bar = range,
trade the break. Trail 0.2R.

Run: python backtest_m30_mt5.py
"""

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

try:
    import MetaTrader5 as mt5
    MT5_OK = True
except ImportError:
    MT5_OK = False

ACCOUNT = 70_000
RISK    = ACCOUNT * 0.005
TRAIL   = 0.2
BARS    = 52_000   # ~2 years of M30 bars (252 trading days × 8 sessions × 2 = ~4032/yr)

# ── MT5 connection ─────────────────────────────────────────────────────────────
def connect_mt5():
    if not MT5_OK:
        print("ERROR: MetaTrader5 package not installed. Run: pip install MetaTrader5")
        return False
    if not mt5.initialize():
        print(f"ERROR: MT5 failed to initialise — is MT5 open and logged in? {mt5.last_error()}")
        return False
    info = mt5.account_info()
    print(f"[MT5] Connected — {info.name} | {info.server} | Balance: £{info.balance:,.0f}")
    return True

def get_m30(symbol):
    if not MT5_OK: return None
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M30, 0, BARS)
    if rates is None or len(rates) == 0:
        print(f"  [!] No M30 data for {symbol} — check symbol name in Market Watch")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df.set_index('time', inplace=True)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={'tick_volume':'volume'})
    df = df[['open','high','low','close','volume']].dropna()
    print(f"  [✓] {symbol}: {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})")
    return df

# ── Simulator ──────────────────────────────────────────────────────────────────
def sim(bars_df, direction, entry, sl, max_bars=25):
    sl_dist = abs(entry - sl)
    if sl_dist <= 0 or len(bars_df) == 0: return 0.0
    trail  = sl_dist * TRAIL
    sl_cur = sl; best = entry; be = False
    rows   = bars_df.iloc[:max_bars]
    ex     = rows.iloc[-1]['close']
    for _, b in rows.iterrows():
        if direction == 'buy':
            if b['low']  <= sl_cur: return (sl_cur-entry)/sl_dist
            if b['high'] > best:    best = b['high']
            if not be and best >= entry+sl_dist: be=True; sl_cur=entry
            if be:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur: return (entry-sl_cur)/sl_dist
            if b['low']  < best:    best = b['low']
            if not be and best <= entry-sl_dist: be=True; sl_cur=entry
            if be:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns
    return ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist

# ── Stats ──────────────────────────────────────────────────────────────────────
def stats(trades):
    if len(trades) < 15: return None
    arr   = np.array([t['r'] for t in trades])
    gbp   = arr * RISK
    wins  = gbp[gbp >  5]; losses = gbp[gbp < -5]
    n     = len(arr)
    wr    = len(wins)/n*100
    pf_   = wins.sum() / (abs(losses.sum()) if len(losses) else 1)
    total = gbp.sum()
    cum   = np.cumsum(gbp); pk = np.maximum.accumulate(cum)
    dd    = (cum-pk).min()
    days  = max(1,(trades[-1]['date']-trades[0]['date']).days)
    mo    = total/days*30
    tpm   = n/days*30
    v     = "✅ STRONG" if pf_>=1.5 else ("⚠️  OK" if pf_>=1.2 else "❌")
    return {'wr':round(wr,1),'pf':round(pf_,2),'mo':round(mo*2,0),
            'dd':round(dd*2,0),'tpm':round(tpm,1),'n':n,'v':v}

# ── ORB runner ─────────────────────────────────────────────────────────────────
def run_m30_orb(name, df, rng_h, entry_h, exit_h, min_rng, max_rng):
    if df is None: return []
    trades = []
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day = pd.Timestamp(d, tz='UTC')
        if day.dayofweek >= 5: continue

        # First M30 bar of the session (the range)
        rb = df[(df.index >= day+pd.Timedelta(hours=rng_h)) &
                (df.index <  day+pd.Timedelta(hours=rng_h+0.5))]
        if len(rb) == 0: continue
        r_hi = rb['high'].max()
        r_lo = rb['low'].min()
        rng  = r_hi - r_lo
        if not (min_rng <= rng <= max_rng): continue

        # Entry bars — rest of session
        eb = df[(df.index >= day+pd.Timedelta(hours=entry_h)) &
                (df.index <  day+pd.Timedelta(hours=exit_h))]
        if len(eb) < 2: continue

        direction = entry = et = None
        for bt, b in eb.iterrows():
            if b['high'] > r_hi: direction='buy';  entry=r_hi; et=bt; break
            if b['low']  < r_lo: direction='sell'; entry=r_lo; et=bt; break
        if direction is None: continue

        buf = rng * 0.15
        sl  = (r_lo-buf) if direction=='buy' else (r_hi+buf)
        if abs(entry-sl) <= 0: continue

        exit_bars = df[(df.index > et) &
                       (df.index <= day+pd.Timedelta(hours=exit_h))]
        r = sim(exit_bars, direction, entry, sl)
        trades.append({'r':r,'date':day,'month':day.month})

    return trades

# ── Instruments ────────────────────────────────────────────────────────────────
# (name, mt5_symbol, range_hour, entry_hour, exit_hour, min_rng, max_rng)
M30_CONFIGS = [
    ("M30 DAX",    "GER40.cash",  8,   9,  13,  10,   400),
    ("M30 UK100",  "UK100.cash",  8,   9,  13,   8,   200),
    ("M30 NAS100", "US100.cash", 14,  15,  19,  25,  2000),
    ("M30 SP500",  "US500.cash", 14,  15,  19,   5,   300),
    ("M30 NatGas", "XNGUSD",    14,  15,  19, 0.01,   0.8),
    ("M30 EURUSD", "EURUSD",     7,   8,  11, 0.0003, 0.015),
    ("M30 GBPUSD", "GBPUSD",     7,   8,  11, 0.0003, 0.018),
]

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "="*80)
    print("  M30 ORB — 2 YEAR BACKTEST via MetaTrader5")
    print("  Trail 0.2R | 0.5% risk | £70k account")
    print("="*80)

    if not connect_mt5():
        print("\nCould not connect to MT5. Make sure MT5 is open and logged in.")
        exit(1)

    print("\n  Fetching M30 data...")
    data = {}
    for cfg in M30_CONFIGS:
        data[cfg[0]] = get_m30(cfg[1])

    print(f"\n  {'Strategy':<18} {'Win%':>5}  {'T/mo':>5}  {'Monthly@1%':>10}  "
          f"{'PF':>5}  {'DD@1%':>8}  {'Trades':>7}  Verdict")
    print(f"  {'─'*78}")

    results = []
    for cfg in M30_CONFIGS:
        name, sym, rng_h, entry_h, exit_h, min_r, max_r = cfg
        df     = data[name]
        trades = run_m30_orb(name, df, rng_h, entry_h, exit_h, min_r, max_r)
        s      = stats(trades)
        if not s:
            print(f"  {name:<18} — not enough trades ({len(trades)})")
            continue
        print(f"  {name:<18} {s['wr']:>5.1f}%  {s['tpm']:>5.1f}  "
              f"£{s['mo']:>8,.0f}  {s['pf']:>5.2f}  £{s['dd']:>7,.0f}  "
              f"{s['n']:>7}  {s['v']}")
        results.append({**s,'name':name})

    mt5.shutdown()

    # Ranking
    strong = sorted([r for r in results if r['pf']>=1.5], key=lambda x:-x['pf'])
    ok     = sorted([r for r in results if 1.2<=r['pf']<1.5], key=lambda x:-x['pf'])

    print(f"\n{'='*80}")
    print("  RANKING — 2-YEAR VALIDATED M30 ORB")
    print(f"{'='*80}")
    print(f"\n  ✅ STRONG (PF ≥ 1.5):")
    for r in strong:
        print(f"     {r['name']:<18} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['mo']:,.0f}/mo @1% | {r['n']} trades")
    print(f"\n  ⚠️  MARGINAL (PF 1.2–1.5):")
    for r in ok:
        print(f"     {r['name']:<18} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['mo']:,.0f}/mo @1% | {r['n']} trades")

    if strong:
        print(f"\n  Combined strong at 0.5%: £{sum(r['mo'] for r in strong)//2:,.0f}/mo")
    print()
