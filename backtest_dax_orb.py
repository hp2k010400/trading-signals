"""
backtest_dax_orb.py — DAX Opening Range Breakout
Strategy: 08:00-09:00 UTC H1 bar forms the opening range.
At 09:00 UTC trade the first break above/below that range.
Exit at TP, SL, or 17:00 UTC.

Why DAX: H4 EMA backtest showed PF 2.61 — strongest instrument tested.
ORB captures the same trend-following edge but fires DAILY instead of 1.4x/month.
Run: python backtest_dax_orb.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT     = 70000
RISK_PCT    = 0.005    # 0.5% per trade
MIN_RANGE   = 30       # skip days where opening range < 30 DAX points (too tight)
MAX_RANGE   = 300      # skip days where range > 300 points (news/gap days)
ENTRY_HOUR  = 9        # first hour to look for breakout
CANCEL_HOUR = 12       # cancel if no breakout by noon
SESSION_END = 17       # force-close at 17:00 UTC

# Test two TP sizes simultaneously to find the optimal
TP_SCENARIOS = {
    "TP=1R": 1.0,
    "TP=2R": 2.0,
    "TP=3R": 3.0,
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

def run_orb(df, tp_mult, label):
    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day     = pd.Timestamp(date, tz='UTC')
        orb_t   = day + pd.Timedelta(hours=8)
        if orb_t not in df.index:
            continue

        orb     = df.loc[orb_t]
        orb_hi  = orb['high']
        orb_lo  = orb['low']
        orb_rng = orb_hi - orb_lo

        if orb_rng < MIN_RANGE or orb_rng > MAX_RANGE:
            continue

        # Scan 09:00–12:00 UTC for first breakout
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

        sl_dist = orb_rng
        if direction == 'buy':
            sl = entry_price - sl_dist
            tp = entry_price + sl_dist * tp_mult
        else:
            sl = entry_price + sl_dist
            tp = entry_price - sl_dist * tp_mult

        # Simulate to session end
        sim = df[(df.index > entry_time) &
                 (df.index <= day + pd.Timedelta(hours=SESSION_END))]

        ex_price, reason = (sim.iloc[-1]['close'] if len(sim) else entry_price), 'timeout'
        for _, b in sim.iterrows():
            if direction == 'buy':
                if b['low']  <= sl: ex_price, reason = sl, 'sl'; break
                if b['high'] >= tp: ex_price, reason = tp, 'tp'; break
            else:
                if b['high'] >= sl: ex_price, reason = sl, 'sl'; break
                if b['low']  <= tp: ex_price, reason = tp, 'tp'; break

        pnl_r   = ((ex_price - entry_price) if direction == 'buy'
                   else (entry_price - ex_price)) / sl_dist
        pnl_gbp = risk * pnl_r

        trades.append({
            'date': day, 'direction': direction, 'reason': reason,
            'pnl_r': round(pnl_r, 2), 'pnl_gbp': round(pnl_gbp, 2),
            'range': round(orb_rng, 0)
        })

    if not trades:
        return None

    df_t     = pd.DataFrame(trades)
    wins     = df_t[df_t['pnl_gbp'] >  5]
    losses   = df_t[df_t['pnl_gbp'] < -5]
    n        = len(df_t)
    wr       = len(wins) / n * 100
    gp       = wins['pnl_gbp'].sum()          if len(wins)   > 0 else 0
    gl       = abs(losses['pnl_gbp'].sum())   if len(losses) > 0 else 1
    pf       = gp / gl
    total    = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd   = (df_t['cum'] - df_t['peak']).min()
    days     = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly  = total / days * 30
    tpm      = n / (days / 30)
    tp_pct   = (df_t['reason'] == 'tp').mean() * 100
    sl_pct   = (df_t['reason'] == 'sl').mean() * 100
    to_pct   = (df_t['reason'] == 'timeout').mean() * 100
    verdict  = "✅ STRONG" if pf >= 1.5 else ("⚠️  OK" if pf >= 1.2 else "❌ WEAK")

    print(f"\n  ── {label} ──────────────────────────────────────────────────────────")
    print(f"  Trades/month:    {tpm:.1f}   (total {n})")
    print(f"  Win rate:        {wr:.1f}%")
    print(f"  Profit factor:   {pf:.2f}  {verdict}")
    print(f"  Avg R/trade:     {df_t['pnl_r'].mean():.2f}R")
    print(f"  Monthly @0.5%:   £{monthly:,.0f}")
    print(f"  Monthly @1%:     £{monthly*2:,.0f}")
    print(f"  Max DD @1%:      £{max_dd*2:,.0f}  {'✅ safe' if abs(max_dd*2) < 6000 else '⚠️  tight'}")
    print(f"  Exit breakdown:  TP:{tp_pct:.0f}%  SL:{sl_pct:.0f}%  Timeout:{to_pct:.0f}%")

    # Month-by-month P&L
    df_t['month'] = df_t['date'].dt.to_period('M')
    monthly_pnl   = df_t.groupby('month')['pnl_gbp'].sum()
    green = sum(1 for v in monthly_pnl if v > 0)
    red   = sum(1 for v in monthly_pnl if v <= 0)
    print(f"  Profitable months: {green}/{green+red}")
    print(f"\n  Monthly P&L @0.5% risk:")
    for m, pnl in monthly_pnl.items():
        blocks = '█' * min(int(abs(pnl) / 100), 30)
        sign   = '+' if pnl >= 0 else '-'
        colour = '' if pnl >= 0 else ''
        print(f"    {m}  {sign}£{abs(pnl):>5,.0f}  {blocks}")

    return {'label': label, 'tpm': tpm, 'wr': wr, 'pf': pf,
            'monthly': monthly, 'max_dd': max_dd, 'df_t': df_t}

if __name__ == "__main__":
    print("\n" + "="*72)
    print("  DAX OPENING RANGE BREAKOUT — TP COMPARISON")
    print("  Range = 08:00 UTC H1 bar | Entry 09:00–12:00 | Exit 17:00 UTC")
    print("  2 years H1 data | SL = opposite ORB edge | Testing TP 1R / 2R / 3R")
    print("="*72)

    print("\n  Fetching DAX H1 data...")
    df = fetch_h1()
    if df is None:
        print("  ERROR: Could not fetch DAX data")
        exit(1)
    print(f"  Got {len(df)} H1 bars\n")

    results = {}
    for label, tp_mult in TP_SCENARIOS.items():
        r = run_orb(df, tp_mult, label)
        if r:
            results[label] = r

    print(f"\n{'='*72}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*72}")
    print(f"\n  {'Scenario':<12} {'T/mo':>6}  {'Win%':>6}  {'PF':>6}  {'Monthly@1%':>12}  {'DD@1%':>10}")
    print(f"  {'─'*60}")
    for label, r in results.items():
        verdict = "✅" if r['pf'] >= 1.5 else ("⚠️ " if r['pf'] >= 1.2 else "❌")
        print(f"  {label:<12} {r['tpm']:>6.1f}  {r['wr']:>6.1f}%  {r['pf']:>6.2f}  "
              f"£{r['monthly']*2:>10,.0f}  £{r['max_dd']*2:>8,.0f}  {verdict}")

    print(f"\n  FTMO limits: daily DD £3,500 | total DD £7,000")
    print(f"  At 0.75% risk/trade, scale monthly by 1.5× and DD by 1.5×\n")
