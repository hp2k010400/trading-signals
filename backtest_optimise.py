"""
backtest_optimise.py — Three optimisation tests run together
  1. DAX ORB + Trend Filter
  2. DAX ORB + Tue-Thu Filter
  3. London Breakout range sweet spot (20-50 pips vs 10-100)

Run: python backtest_optimise.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT  = 70000
RISK_PCT = 0.005

# ── Data ───────────────────────────────────────────────────────────────────────

def fetch_h1(symbol, days=730):
    df = yf.download(symbol, interval="1h", period=f"{days}d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    else:
        df.index = df.index.tz_convert('UTC')
    return df

def get_daily_trend(df, date):
    """Bull if close > 20-day EMA on previous close, bear if below."""
    prev = date - pd.Timedelta(days=1)
    hist = df[df.index.date <= prev.date()].resample('1D').last().dropna()
    if len(hist) < 21:
        return 'flat'
    hist['ema20'] = hist['close'].ewm(span=20, adjust=False).mean()
    last = hist.iloc[-1]
    diff = (last['close'] - last['ema20']) / last['ema20'] * 100
    if diff > 0.3:  return 'bull'
    if diff < -0.3: return 'bear'
    return 'flat'

# ── Trade simulator (trailing stop) ───────────────────────────────────────────

def sim(df, entry_time, direction, entry, sl, trail_mult, exit_hour):
    sl_dist  = abs(entry - sl)
    trail    = sl_dist * trail_mult
    day      = entry_time.normalize()
    sim_bars = df[(df.index > entry_time) &
                  (df.index <= day + pd.Timedelta(hours=exit_hour))]

    sl_cur  = sl
    best    = entry
    be_done = False
    ex      = sim_bars.iloc[-1]['close'] if len(sim_bars) else entry
    reason  = 'timeout'

    for _, b in sim_bars.iterrows():
        if direction == 'buy':
            if b['low'] <= sl_cur:  ex = sl_cur; reason = 'sl';   break
            if b['high'] > best:    best = b['high']
            if not be_done and best >= entry + sl_dist:
                be_done = True; sl_cur = entry
            if be_done:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur: ex = sl_cur; reason = 'sl';   break
            if b['low'] < best:     best = b['low']
            if not be_done and best <= entry - sl_dist:
                be_done = True; sl_cur = entry
            if be_done:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns

    pnl_r = ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist
    return round(pnl_r, 2), reason

def stats(trades, label):
    if not trades:
        print(f"  {label:<40} — 0 trades"); return None
    df_t    = pd.DataFrame(trades)
    wins    = df_t[df_t['pnl_gbp'] >  5]
    losses  = df_t[df_t['pnl_gbp'] < -5]
    n       = len(df_t)
    wr      = len(wins)/n*100
    gp      = wins['pnl_gbp'].sum()         if len(wins)   > 0 else 0
    gl      = abs(losses['pnl_gbp'].sum())  if len(losses) > 0 else 1
    pf      = gp/gl
    total   = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd  = (df_t['cum']-df_t['peak']).min()
    days    = max((df_t['date'].iloc[-1]-df_t['date'].iloc[0]).days, 1)
    monthly = total/days*30
    tpm     = n/(days/30)
    verdict = "✅ STRONG" if pf>=1.5 else ("⚠️  OK" if pf>=1.2 else "❌ WEAK")
    print(f"  {label:<40} {tpm:>5.1f}/mo  {wr:>5.1f}%  PF:{pf:>5.2f}  "
          f"£{monthly*2:>7,.0f}@1%  DD:£{max_dd*2:>7,.0f}  {verdict}")
    return {'label':label,'tpm':tpm,'wr':wr,'pf':pf,'monthly':monthly,'max_dd':max_dd}

# ── 1. DAX ORB variations ──────────────────────────────────────────────────────

def run_dax_orb(df, use_trend=False, use_dow=False, label=""):
    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day = pd.Timestamp(date, tz='UTC')

        if use_dow and day.dayofweek in [0, 4]:
            continue

        if use_trend:
            trend = get_daily_trend(df, day)
        else:
            trend = None

        orb_t = day + pd.Timedelta(hours=8)
        rows  = df[df.index == orb_t]
        if len(rows) == 0: continue

        orb = rows.iloc[0]
        hi, lo, rng = orb['high'], orb['low'], orb['high']-orb['low']
        if not (30 <= rng <= 300): continue

        since = df[(df.index >= day + pd.Timedelta(hours=9)) &
                   (df.index <  day + pd.Timedelta(hours=12))]
        if len(since) == 0: continue

        direction = None
        entry_time = None
        for bt, b in since.iterrows():
            if b['high'] > hi:
                if use_trend and trend == 'bear': break
                direction = 'buy'; entry_time = bt; break
            if b['low'] < lo:
                if use_trend and trend == 'bull': break
                direction = 'sell'; entry_time = bt; break

        if direction is None: continue

        entry  = hi if direction == 'buy' else lo
        sl     = lo if direction == 'buy' else hi
        pnl_r, reason = sim(df, entry_time, direction, entry, sl, 0.5, 17)
        pnl_gbp = risk * pnl_r
        trades.append({'date':day,'pnl_r':pnl_r,'pnl_gbp':pnl_gbp,'reason':reason})

    return stats(trades, label)

# ── 2. London Breakout range filter ───────────────────────────────────────────

def run_lb(df_eur, df_gbp, min_pips, max_pips, label=""):
    trades = []
    risk   = ACCOUNT * RISK_PCT

    for df, pip in [(df_eur, 0.0001), (df_gbp, 0.0001)]:
        dates = sorted(set(df.index.normalize().date))
        for date in dates:
            day  = pd.Timestamp(date, tz='UTC')
            prev = day - pd.Timedelta(days=1)

            asian = df[(df.index >= prev + pd.Timedelta(hours=22)) &
                       (df.index <  day  + pd.Timedelta(hours=7))]
            if len(asian) < 4: continue

            a_hi, a_lo = asian['high'].max(), asian['low'].min()
            rng  = a_hi - a_lo
            pips = rng / pip

            if not (min_pips <= pips <= max_pips): continue

            london = df[(df.index >= day + pd.Timedelta(hours=7)) &
                        (df.index <  day + pd.Timedelta(hours=10))]
            if len(london) == 0: continue

            direction = None
            entry_time = None
            for bt, b in london.iterrows():
                if b['high'] > a_hi:
                    direction = 'buy';  entry_time = bt; break
                if b['low']  < a_lo:
                    direction = 'sell'; entry_time = bt; break

            if direction is None: continue

            entry = a_hi if direction == 'buy' else a_lo
            sl    = (a_lo - rng*0.15) if direction == 'buy' else (a_hi + rng*0.15)
            pnl_r, reason = sim(df, entry_time, direction, entry, sl, 1.0, 13)
            pnl_gbp = risk * pnl_r
            trades.append({'date':day,'pnl_r':pnl_r,'pnl_gbp':pnl_gbp,'reason':reason})

    return stats(trades, label)

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  OPTIMISATION TESTS")
    print("="*80)

    # DAX ORB tests
    print("\n  Fetching DAX data...")
    dax = fetch_h1("^GDAXI")
    print(f"  Got {len(dax)} H1 bars\n")

    print("  ── DAX ORB ────────────────────────────────────────────────────────────")
    print(f"  {'Version':<40} {'T/mo':>6}  {'Win%':>5}  {'PF':>6}  "
          f"{'Monthly@1%':>11}  {'DD@1%':>8}")
    print(f"  {'─'*76}")
    r_orb_base    = run_dax_orb(dax, False, False, "Baseline (no filter)")
    r_orb_trend   = run_dax_orb(dax, True,  False, "Trend filter only")
    r_orb_dow     = run_dax_orb(dax, False, True,  "Tue-Thu only")
    r_orb_both    = run_dax_orb(dax, True,  True,  "Trend + Tue-Thu")

    # London Breakout tests
    print("\n  Fetching EURUSD & GBPUSD data...")
    eur = fetch_h1("EURUSD=X")
    gbp = fetch_h1("GBPUSD=X")
    print(f"  Got {len(eur)} EUR bars, {len(gbp)} GBP bars\n")

    print("  ── LONDON BREAKOUT range filter ───────────────────────────────────────")
    print(f"  {'Version':<40} {'T/mo':>6}  {'Win%':>5}  {'PF':>6}  "
          f"{'Monthly@1%':>11}  {'DD@1%':>8}")
    print(f"  {'─'*76}")
    r_lb_wide   = run_lb(eur, gbp, 10,  100, "Baseline (10-100 pips)")
    r_lb_mid    = run_lb(eur, gbp, 20,  60,  "Sweet spot (20-60 pips)")
    r_lb_tight  = run_lb(eur, gbp, 25,  50,  "Tight (25-50 pips)")
    r_lb_narrow = run_lb(eur, gbp, 15,  45,  "Narrow (15-45 pips)")

    # Summary
    print(f"\n{'='*80}")
    print("  SUMMARY — best version of each strategy")
    print(f"{'='*80}\n")

    orb_results = [r for r in [r_orb_base, r_orb_trend, r_orb_dow, r_orb_both] if r]
    lb_results  = [r for r in [r_lb_wide,  r_lb_mid,   r_lb_tight, r_lb_narrow] if r]

    if orb_results:
        best_orb = max(orb_results, key=lambda x: x['pf'])
        print(f"  DAX ORB best:  {best_orb['label']}")
        print(f"  PF {best_orb['pf']:.2f} | {best_orb['tpm']:.1f}/mo | "
              f"£{best_orb['monthly']*2:,.0f}/mo @1% | DD £{best_orb['max_dd']*2:,.0f}")

    if lb_results:
        best_lb = max(lb_results, key=lambda x: x['pf'])
        print(f"\n  LB best:       {best_lb['label']}")
        print(f"  PF {best_lb['pf']:.2f} | {best_lb['tpm']:.1f}/mo | "
              f"£{best_lb['monthly']*2:,.0f}/mo @1% | DD £{best_lb['max_dd']*2:,.0f}")

    print(f"\n  FTMO: daily DD £3,500 | total DD £7,000\n")
