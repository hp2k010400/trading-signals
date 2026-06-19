"""
backtest_dax_orb_trail.py — DAX ORB with Trailing Stop
Same entry as backtest_dax_orb.py but exits via trailing stop instead of fixed TP.

Why: TP=1R→2R→3R all showed improving PF, meaning DAX trends all day after the
breakout. A trailing stop lets winners run as far as the trend goes rather than
capping them at an arbitrary target.

Trailing logic:
  - Once trade is +1R in profit → move SL to breakeven
  - After breakeven: trail SL at (highest_high - trail_dist) for longs
                              or (lowest_low  + trail_dist) for shorts
  - Close at 17:00 UTC if still open

Tests three trail distances: 0.5R, 1R, 1.5R (multiples of opening range size)
Run: python backtest_dax_orb_trail.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT     = 70000
RISK_PCT    = 0.005
MIN_RANGE   = 30
MAX_RANGE   = 300
ENTRY_HOUR  = 9
CANCEL_HOUR = 12
SESSION_END = 17

TRAIL_SCENARIOS = {
    "Trail=0.5R": 0.5,
    "Trail=1R":   1.0,
    "Trail=1.5R": 1.5,
}

def fetch_h1():
    df = yf.download("^GDAXI", interval="1h", period="730d",
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

def run_trail(df, trail_mult, label):
    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day    = pd.Timestamp(date, tz='UTC')
        orb_t  = day + pd.Timedelta(hours=8)
        if orb_t not in df.index:
            continue

        orb     = df.loc[orb_t]
        orb_hi  = orb['high']
        orb_lo  = orb['low']
        orb_rng = orb_hi - orb_lo
        trail_dist = orb_rng * trail_mult

        if orb_rng < MIN_RANGE or orb_rng > MAX_RANGE:
            continue

        entry_window = df[
            (df.index >= day + pd.Timedelta(hours=ENTRY_HOUR)) &
            (df.index <  day + pd.Timedelta(hours=CANCEL_HOUR))
        ]

        direction = entry_price = entry_time = None
        for bt, bar in entry_window.iterrows():
            if bar['high'] > orb_hi:
                direction, entry_price, entry_time = 'buy',  orb_hi, bt; break
            if bar['low']  < orb_lo:
                direction, entry_price, entry_time = 'sell', orb_lo, bt; break

        if direction is None:
            continue

        initial_sl = orb_lo if direction == 'buy' else orb_hi
        sl_dist    = abs(entry_price - initial_sl)
        if sl_dist <= 0:
            continue

        # Simulate with trailing stop
        sim = df[(df.index > entry_time) &
                 (df.index <= day + pd.Timedelta(hours=SESSION_END))]

        sl_cur     = initial_sl
        be_done    = False          # moved to breakeven yet?
        best_price = entry_price    # highest high (buy) or lowest low (sell)
        ex_price   = sim.iloc[-1]['close'] if len(sim) else entry_price
        reason     = 'timeout'

        for _, bar in sim.iterrows():
            if direction == 'buy':
                # Check stop first
                if bar['low'] <= sl_cur:
                    ex_price = sl_cur; reason = 'trail_stop'; break
                # Update best price
                if bar['high'] > best_price:
                    best_price = bar['high']
                # Move to breakeven once +1R
                if not be_done and best_price >= entry_price + sl_dist:
                    be_done = True
                    sl_cur  = entry_price
                # Trail behind best price
                if be_done:
                    new_sl = best_price - trail_dist
                    if new_sl > sl_cur:
                        sl_cur = new_sl
            else:
                if bar['high'] >= sl_cur:
                    ex_price = sl_cur; reason = 'trail_stop'; break
                if bar['low'] < best_price:
                    best_price = bar['low']
                if not be_done and best_price <= entry_price - sl_dist:
                    be_done = True
                    sl_cur  = entry_price
                if be_done:
                    new_sl = best_price + trail_dist
                    if new_sl < sl_cur:
                        sl_cur = new_sl

        pnl_r   = ((ex_price - entry_price) if direction == 'buy'
                   else (entry_price - ex_price)) / sl_dist
        pnl_gbp = risk * pnl_r

        trades.append({
            'date': day, 'direction': direction, 'reason': reason,
            'pnl_r': round(pnl_r, 2), 'pnl_gbp': round(pnl_gbp, 2),
            'range': round(orb_rng, 0), 'be_done': be_done,
        })

    if not trades:
        return None

    df_t     = pd.DataFrame(trades)
    wins     = df_t[df_t['pnl_gbp'] >  5]
    losses   = df_t[df_t['pnl_gbp'] < -5]
    n        = len(df_t)
    wr       = len(wins) / n * 100
    gp       = wins['pnl_gbp'].sum()         if len(wins)   > 0 else 0
    gl       = abs(losses['pnl_gbp'].sum())  if len(losses) > 0 else 1
    pf       = gp / gl
    total    = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd   = (df_t['cum'] - df_t['peak']).min()
    days     = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly  = total / days * 30
    tpm      = n / (days / 30)
    avg_r    = df_t['pnl_r'].mean()
    be_pct   = df_t['be_done'].mean() * 100
    ts_pct   = (df_t['reason'] == 'trail_stop').mean() * 100
    to_pct   = (df_t['reason'] == 'timeout').mean() * 100
    verdict  = "✅ STRONG" if pf >= 1.5 else ("⚠️  OK" if pf >= 1.2 else "❌ WEAK")

    print(f"\n  ── {label} ──────────────────────────────────────────────────────────")
    print(f"  Trades/month:    {tpm:.1f}   (total {n})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Profit factor:   {pf:.2f}  {verdict}")
    print(f"  Avg R/trade:     {avg_r:.2f}R")
    print(f"  Monthly @0.5%:   £{monthly:,.0f}")
    print(f"  Monthly @1%:     £{monthly*2:,.0f}")
    print(f"  Max DD @0.5%:    £{max_dd:,.0f}")
    print(f"  Max DD @1%:      £{max_dd*2:,.0f}  {'✅ safe' if abs(max_dd*2) < 6500 else '⚠️  tight'}")
    print(f"  Reached BE:      {be_pct:.0f}% of trades")
    print(f"  Exit: TrailStop:{ts_pct:.0f}%  Timeout:{to_pct:.0f}%")

    df_t['month'] = df_t['date'].dt.to_period('M')
    monthly_pnl   = df_t.groupby('month')['pnl_gbp'].sum()
    green = sum(1 for v in monthly_pnl if v > 0)
    red   = sum(1 for v in monthly_pnl if v <= 0)
    print(f"  Profitable months: {green}/{green+red}")

    print(f"\n  Monthly P&L @0.5% risk:")
    for m, pnl in monthly_pnl.items():
        blocks = '█' * min(int(abs(pnl) / 100), 30)
        sign   = '+' if pnl >= 0 else '-'
        print(f"    {m}  {sign}£{abs(pnl):>5,.0f}  {blocks}")

    return {
        'label': label, 'tpm': tpm, 'wr': wr, 'pf': pf,
        'monthly': monthly, 'max_dd': max_dd, 'avg_r': avg_r,
    }

if __name__ == "__main__":
    print("\n" + "="*72)
    print("  DAX ORB — TRAILING STOP (vs fixed TP)")
    print("  Entry: first H1 break of 08:00 ORB range (09:00–12:00 UTC)")
    print("  Exit:  trail SL (activates at +1R) | force-close 17:00 UTC")
    print("  2 years H1 | SL = opposite ORB edge | Trail = % of range")
    print("="*72)

    print("\n  Fetching DAX H1 data...")
    df = fetch_h1()
    if df is None:
        print("  ERROR: no data"); exit(1)
    print(f"  Got {len(df)} bars\n")

    results = {}
    for label, trail_mult in TRAIL_SCENARIOS.items():
        r = run_trail(df, trail_mult, label)
        if r:
            results[label] = r

    print(f"\n{'='*72}")
    print(f"  COMPARISON — TRAILING STOP vs FIXED TP (from previous backtest)")
    print(f"{'='*72}")
    print(f"\n  {'Strategy':<16} {'T/mo':>6}  {'Win%':>6}  {'PF':>6}  "
          f"{'Monthly@1%':>12}  {'DD@1%':>10}  {'AvgR':>6}")
    print(f"  {'─'*68}")

    # Fixed TP reference (from previous test)
    refs = [
        ("Fixed TP=1R",  18.7, 53.1, 1.13,  720, -7048, 0.06),
        ("Fixed TP=2R",  18.7, 46.2, 1.27, 1618, -8287, 0.12),
        ("Fixed TP=3R",  18.7, 45.4, 1.36, 2166, -8312, 0.17),
    ]
    for name, tpm, wr, pf, mo, dd, ar in refs:
        verdict = "✅" if pf >= 1.5 else ("⚠️ " if pf >= 1.2 else "❌")
        print(f"  {name:<16} {tpm:>6.1f}  {wr:>6.1f}%  {pf:>6.2f}  "
              f"£{mo:>10,.0f}  £{dd:>8,.0f}  {ar:>6.2f}R  {verdict}")

    print(f"  {'─'*68}")
    for label, r in results.items():
        verdict = "✅" if r['pf'] >= 1.5 else ("⚠️ " if r['pf'] >= 1.2 else "❌")
        print(f"  {label:<16} {r['tpm']:>6.1f}  {r['wr']:>6.1f}%  {r['pf']:>6.2f}  "
              f"£{r['monthly']*2:>10,.0f}  £{r['max_dd']*2:>8,.0f}  "
              f"{r['avg_r']:>6.2f}R  {verdict}")

    best = max(results.values(), key=lambda x: x['pf']) if results else None
    if best:
        print(f"\n  Best trailing config: {best['label']}")
        print(f"  At 0.75% risk: £{best['monthly']*1.5:,.0f}/mo | DD £{best['max_dd']*1.5:,.0f}")
        print(f"\n  FTMO limits: daily DD £3,500 | total DD £7,000\n")
