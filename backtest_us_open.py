"""
backtest_us_open.py — US Market Open Strategy (inspired by 9:30 AM open trading)
Concept: the hour before US open (13:00-14:00 UTC) forms a pre-market range.
At 14:00 UTC (9:30 AM EST) trade the first break of that range.
Trail stop to let winners run. Force-close at 20:00 UTC.

Tests: US30, NAS100, SP500 — all fire at the same time daily.
Same ORB + trailing stop framework proven on DAX (Trail=0.5R, PF 1.45).
Run: python backtest_us_open.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT      = 70000
RISK_PCT     = 0.005
TRAIL_MULT   = 0.5     # trail at 0.5× range — best config from DAX ORB test
MIN_RANGE    = 50      # minimum pre-market range in points
MAX_RANGE    = 800     # skip gap/news days
PRE_MKT_HOUR = 13     # pre-market reference bar (13:00-14:00 UTC)
ENTRY_HOUR   = 14     # US market opens 14:30 UTC, first full bar at 14:00
CANCEL_HOUR  = 16     # cancel if no breakout by 16:00 UTC
SESSION_END  = 20     # force-close at 20:00 UTC

INSTRUMENTS = [
    ("US30",   "YM=F",  50,  800),
    ("NAS100", "NQ=F",  50,  1500),
    ("SP500",  "ES=F",  10,  200),
]

def fetch_h1(symbol):
    try:
        df = yf.download(symbol, interval="1h", period="730d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 100:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')
        return df
    except:
        return None

def run_instrument(name, symbol, min_rng, max_rng):
    df = fetch_h1(symbol)
    if df is None:
        print(f"  {name:<10} — no data")
        return None

    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day = pd.Timestamp(date, tz='UTC')

        # Pre-market reference: the 13:00 UTC H1 bar
        ref_t = day + pd.Timedelta(hours=PRE_MKT_HOUR)
        if ref_t not in df.index:
            continue

        ref     = df.loc[ref_t]
        ref_hi  = ref['high']
        ref_lo  = ref['low']
        ref_rng = ref_hi - ref_lo

        if ref_rng < min_rng or ref_rng > max_rng:
            continue

        trail_dist = ref_rng * TRAIL_MULT

        # Entry window: 14:00–16:00 UTC (covers 9:30–11:00 AM EST)
        entry_window = df[
            (df.index >= day + pd.Timedelta(hours=ENTRY_HOUR)) &
            (df.index <  day + pd.Timedelta(hours=CANCEL_HOUR))
        ]
        if len(entry_window) == 0:
            continue

        direction = entry_price = entry_time = None
        for bt, bar in entry_window.iterrows():
            if bar['high'] > ref_hi:
                direction, entry_price, entry_time = 'buy',  ref_hi, bt; break
            if bar['low']  < ref_lo:
                direction, entry_price, entry_time = 'sell', ref_lo, bt; break

        if direction is None:
            continue

        initial_sl = ref_lo if direction == 'buy' else ref_hi
        sl_dist    = abs(entry_price - initial_sl)
        if sl_dist <= 0:
            continue

        # Simulate with trailing stop
        sim = df[(df.index > entry_time) &
                 (df.index <= day + pd.Timedelta(hours=SESSION_END))]

        sl_cur     = initial_sl
        be_done    = False
        best_price = entry_price
        ex_price   = sim.iloc[-1]['close'] if len(sim) else entry_price
        reason     = 'timeout'

        for _, bar in sim.iterrows():
            if direction == 'buy':
                if bar['low'] <= sl_cur:
                    ex_price, reason = sl_cur, 'trail_stop'; break
                if bar['high'] > best_price:
                    best_price = bar['high']
                if not be_done and best_price >= entry_price + sl_dist:
                    be_done = True; sl_cur = entry_price
                if be_done:
                    new_sl = best_price - trail_dist
                    if new_sl > sl_cur: sl_cur = new_sl
            else:
                if bar['high'] >= sl_cur:
                    ex_price, reason = sl_cur, 'trail_stop'; break
                if bar['low'] < best_price:
                    best_price = bar['low']
                if not be_done and best_price <= entry_price - sl_dist:
                    be_done = True; sl_cur = entry_price
                if be_done:
                    new_sl = best_price + trail_dist
                    if new_sl < sl_cur: sl_cur = new_sl

        pnl_r   = ((ex_price - entry_price) if direction == 'buy'
                   else (entry_price - ex_price)) / sl_dist
        pnl_gbp = risk * pnl_r

        trades.append({
            'date': day, 'direction': direction, 'reason': reason,
            'pnl_r': round(pnl_r, 2), 'pnl_gbp': round(pnl_gbp, 2),
        })

    if not trades:
        print(f"  {name:<10} — 0 trades")
        return None

    df_t    = pd.DataFrame(trades)
    wins    = df_t[df_t['pnl_gbp'] >  5]
    losses  = df_t[df_t['pnl_gbp'] < -5]
    n       = len(df_t)
    wr      = len(wins) / n * 100
    gp      = wins['pnl_gbp'].sum()         if len(wins)   > 0 else 0
    gl      = abs(losses['pnl_gbp'].sum())  if len(losses) > 0 else 1
    pf      = gp / gl
    total   = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd  = (df_t['cum'] - df_t['peak']).min()
    days    = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly = total / days * 30
    tpm     = n / (days / 30)
    avg_r   = df_t['pnl_r'].mean()
    ts_pct  = (df_t['reason'] == 'trail_stop').mean() * 100
    to_pct  = (df_t['reason'] == 'timeout').mean() * 100
    verdict = "✅ STRONG" if pf >= 1.5 else ("⚠️  OK" if pf >= 1.2 else "❌ WEAK")

    print(f"\n  ── {name} ──────────────────────────────────────────────────")
    print(f"  Trades/month:    {tpm:.1f}   (total {n})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Profit factor:   {pf:.2f}  {verdict}")
    print(f"  Avg R/trade:     {avg_r:.2f}R")
    print(f"  Monthly @0.5%:   £{monthly:,.0f}")
    print(f"  Monthly @1%:     £{monthly*2:,.0f}")
    print(f"  Max DD @1%:      £{max_dd*2:,.0f}  {'✅ safe' if abs(max_dd*2) < 6500 else '⚠️  tight'}")
    print(f"  Exit: Trail:{ts_pct:.0f}%  Timeout:{to_pct:.0f}%")

    df_t['month'] = df_t['date'].dt.to_period('M')
    monthly_pnl   = df_t.groupby('month')['pnl_gbp'].sum()
    green = sum(1 for v in monthly_pnl if v > 0)
    print(f"  Profitable months: {green}/{len(monthly_pnl)}")

    print(f"\n  Monthly P&L @0.5% risk:")
    for m, pnl in monthly_pnl.items():
        blocks = '█' * min(int(abs(pnl) / 150), 30)
        sign   = '+' if pnl >= 0 else '-'
        print(f"    {m}  {sign}£{abs(pnl):>5,.0f}  {blocks}")

    return {'name': name, 'tpm': tpm, 'wr': wr, 'pf': pf,
            'monthly': monthly, 'max_dd': max_dd}

if __name__ == "__main__":
    print("\n" + "="*72)
    print("  US MARKET OPEN STRATEGY — US30, NAS100, SP500")
    print("  Pre-market range: 13:00-14:00 UTC | Entry: 14:00-16:00 UTC")
    print("  Trail stop 0.5R | Force-close 20:00 UTC | 2 years H1 data")
    print("  Concept: same as DAX ORB but at 9:30 AM EST (NY open)")
    print("="*72)

    results = []
    for name, symbol, min_rng, max_rng in INSTRUMENTS:
        r = run_instrument(name, symbol, min_rng, max_rng)
        if r:
            results.append(r)

    print(f"\n{'='*72}")
    print(f"  SUMMARY")
    print(f"{'='*72}")
    print(f"\n  {'Instrument':<10} {'T/mo':>6}  {'Win%':>6}  {'PF':>6}  "
          f"{'Monthly@1%':>12}  {'DD@1%':>10}")
    print(f"  {'─'*60}")
    for r in results:
        verdict = "✅" if r['pf'] >= 1.5 else ("⚠️ " if r['pf'] >= 1.2 else "❌")
        print(f"  {r['name']:<10} {r['tpm']:>6.1f}  {r['wr']:>6.1f}%  {r['pf']:>6.2f}  "
              f"£{r['monthly']*2:>10,.0f}  £{r['max_dd']*2:>8,.0f}  {verdict}")

    if results:
        strong = [r for r in results if r['pf'] >= 1.5]
        ok     = [r for r in results if 1.2 <= r['pf'] < 1.5]
        best   = max(results, key=lambda x: x['pf'])

        print(f"\n  COMPARISON TO DAX ORB (Trail=0.5R, PF 1.45, £1,810/mo @0.75%):")
        for r in results:
            diff = r['pf'] - 1.45
            sign = '+' if diff >= 0 else ''
            print(f"  {r['name']:<10} PF {r['pf']:.2f} ({sign}{diff:.2f} vs DAX ORB)")

        print(f"\n  FULL PORTFOLIO IF ADDING BEST US OPEN INSTRUMENT:")
        print(f"  DAX H4 EMA:     £794/mo  @0.75%")
        print(f"  Oil H4 EMA:     £449/mo  @0.75%")
        print(f"  DAX ORB:        £1,810/mo @0.75%")
        print(f"  LB EURUSD:      £494/mo  @0.4%")
        print(f"  LB GBPUSD:      £485/mo  @0.4%")
        if best['pf'] >= 1.2:
            us_monthly = best['monthly'] * 1.5
            print(f"  {best['name']} Open:    £{us_monthly:,.0f}/mo @0.75%")
            total = 794 + 449 + 1810 + 494 + 485 + us_monthly
            print(f"  {'─'*35}")
            print(f"  TOTAL:          £{total:,.0f}/month")
        print(f"\n  FTMO: daily DD £3,500 | total DD £7,000\n")
