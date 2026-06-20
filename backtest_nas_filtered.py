"""
backtest_nas_filtered.py — NAS100 US Open with filters
Tests 4 versions side by side:
  A. No filter (baseline — PF 2.06 from previous test)
  B. Trend filter only (daily EMA — only trade in trend direction)
  C. Day filter only (Tue-Thu only, skip Mon/Fri)
  D. Both filters combined

Run: python backtest_nas_filtered.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT  = 70000
RISK_PCT = 0.005
SYMBOL   = "NQ=F"
MIN_RNG  = 50
MAX_RNG  = 1500
TRAIL    = 0.5

def fetch():
    df = yf.download(SYMBOL, interval="1h", period="730d",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna()
    if df.index.tz is None:
        df.index = df.index.tz_localize('UTC')
    else:
        df.index = df.index.tz_convert('UTC')
    # Daily data for trend filter
    daily = df.resample('1D').agg({'close':'last'}).dropna()
    daily['ema20'] = daily['close'].ewm(span=20, adjust=False).mean()
    return df, daily

def get_trend(daily, date):
    """Returns 'bull', 'bear', or 'flat' based on 20-day EMA on previous day"""
    prev = date - pd.Timedelta(days=1)
    rows = daily[daily.index.date == prev.date()]
    if len(rows) == 0:
        return 'flat'
    row = rows.iloc[-1]
    diff = (row['close'] - row['ema20']) / row['ema20'] * 100
    if diff > 0.3:   return 'bull'
    if diff < -0.3:  return 'bear'
    return 'flat'

def run(df, daily, use_trend=False, use_dow=False, label=""):
    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day = pd.Timestamp(date, tz='UTC')

        # Day of week filter — skip Monday (0) and Friday (4)
        if use_dow and day.dayofweek in [0, 4]:
            continue

        # Trend filter
        trend = get_trend(daily, day) if use_trend else None

        ref_t = day + pd.Timedelta(hours=13)
        rows  = df[df.index == ref_t]
        if len(rows) == 0:
            continue

        ref = rows.iloc[0]
        hi, lo, rng = ref['high'], ref['low'], ref['high'] - ref['low']
        if not (MIN_RNG <= rng <= MAX_RNG):
            continue

        since = df[
            (df.index >= day + pd.Timedelta(hours=14)) &
            (df.index <  day + pd.Timedelta(hours=16))
        ]
        if len(since) == 0:
            continue

        hi_seen = since['high'].max()
        lo_seen = since['low'].min()
        trail_d = rng * TRAIL
        direction = None

        if hi_seen > hi:
            if use_trend and trend == 'bear': continue  # against trend
            direction = 'buy'; entry = hi; sl = lo
        elif lo_seen < lo:
            if use_trend and trend == 'bull': continue  # against trend
            direction = 'sell'; entry = lo; sl = hi
        else:
            continue

        sl_dist = abs(entry - sl)
        if sl_dist <= 0: continue
        tp = entry + sl_dist if direction == 'buy' else entry - sl_dist

        sim = df[(df.index >= day + pd.Timedelta(hours=14)) &
                 (df.index <= day + pd.Timedelta(hours=20))]

        ex_price, reason = (sim.iloc[-1]['close'] if len(sim) else entry), 'timeout'
        sl_cur = sl; best = entry; be_done = False

        for _, b in sim.iterrows():
            if direction == 'buy':
                if b['low'] <= sl_cur: ex_price, reason = sl_cur, 'sl'; break
                if b['high'] > best: best = b['high']
                if not be_done and best >= entry + sl_dist:
                    be_done = True; sl_cur = entry
                if be_done:
                    ns = best - trail_d
                    if ns > sl_cur: sl_cur = ns
            else:
                if b['high'] >= sl_cur: ex_price, reason = sl_cur, 'sl'; break
                if b['low'] < best: best = b['low']
                if not be_done and best <= entry - sl_dist:
                    be_done = True; sl_cur = entry
                if be_done:
                    ns = best + trail_d
                    if ns < sl_cur: sl_cur = ns

        pnl_r   = ((ex_price-entry) if direction=='buy' else (entry-ex_price)) / sl_dist
        pnl_gbp = risk * pnl_r
        trades.append({'date': day, 'pnl_r': round(pnl_r,2),
                       'pnl_gbp': round(pnl_gbp,2), 'reason': reason})

    if not trades:
        print(f"  {label}: 0 trades"); return None

    df_t    = pd.DataFrame(trades)
    wins    = df_t[df_t['pnl_gbp'] >  5]
    losses  = df_t[df_t['pnl_gbp'] < -5]
    n       = len(df_t)
    wr      = len(wins)/n*100
    gp      = wins['pnl_gbp'].sum()        if len(wins)   > 0 else 0
    gl      = abs(losses['pnl_gbp'].sum()) if len(losses) > 0 else 1
    pf      = gp/gl
    total   = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd  = (df_t['cum']-df_t['peak']).min()
    days    = max((df_t['date'].iloc[-1]-df_t['date'].iloc[0]).days, 1)
    monthly = total/days*30
    tpm     = n/(days/30)
    verdict = "✅ STRONG" if pf>=1.5 else ("⚠️  OK" if pf>=1.2 else "❌ WEAK")

    print(f"  {label:<30} {tpm:>5.1f}/mo  {wr:>5.1f}%  PF:{pf:>5.2f}  "
          f"£{monthly*2:>7,.0f}@1%  DD:£{max_dd*2:>7,.0f}  {verdict}")

    return {'label':label,'tpm':tpm,'wr':wr,'pf':pf,'monthly':monthly,'max_dd':max_dd}

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  NAS100 US OPEN — FILTER COMPARISON")
    print("  Baseline vs Trend Filter vs Day Filter vs Both Combined")
    print("  2 years | Trail=0.5R | 0.5% risk")
    print("="*80)
    print(f"\n  {'Version':<30} {'T/mo':>6}  {'Win%':>5}  {'PF':>6}  "
          f"{'Monthly@1%':>11}  {'DD@1%':>8}")
    print(f"  {'─'*76}")

    print("\n  Fetching NAS100 data...")
    df, daily = fetch()
    print(f"  Got {len(df)} H1 bars\n")

    results = []
    results.append(run(df, daily, False, False, "A. No filter (baseline)"))
    results.append(run(df, daily, True,  False, "B. Trend filter only"))
    results.append(run(df, daily, False, True,  "C. Tue-Thu only"))
    results.append(run(df, daily, True,  True,  "D. Trend + Tue-Thu (best?)"))

    print(f"\n{'='*80}")
    valid = [r for r in results if r]
    if valid:
        best = max(valid, key=lambda x: x['pf'])
        print(f"\n  Best version: {best['label']}")
        print(f"  PF {best['pf']:.2f} | {best['wr']:.1f}% win | "
              f"{best['tpm']:.1f}/mo | £{best['monthly']*2:,.0f}/mo @1%")
        base = valid[0]
        print(f"\n  Improvement over baseline:")
        print(f"  PF:      {base['pf']:.2f} → {best['pf']:.2f} "
              f"(+{best['pf']-base['pf']:.2f})")
        print(f"  Monthly: £{base['monthly']*2:,.0f} → £{best['monthly']*2:,.0f}")
        print(f"  DD:      £{base['max_dd']*2:,.0f} → £{best['max_dd']*2:,.0f}")
    print()
