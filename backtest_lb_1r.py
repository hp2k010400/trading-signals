"""
backtest_lb_1r.py — London Breakout TP comparison (1R vs 1.5R vs 2R)
Same strategy as backtest_london_breakout.py but tests three TP sizes side by side.

Problem identified: at TP=2R only 8-10% of trades hit TP in the 5-hour window.
Price IS moving in the right direction (64% of timeouts are net positive)
but 2R is too far. This script finds the optimal TP.

Run: python backtest_lb_1r.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT        = 70000
RISK_PCT       = 0.005
SL_BUFFER      = 0.15     # SL = opposite range edge + 15% buffer
MIN_RANGE_PIPS = 10
MAX_RANGE_PIPS = 100
ENTRY_FROM     = 7         # 07:00 UTC — start scanning for breakout
ENTRY_TO       = 10        # 10:00 UTC — cancel if no breakout
EXIT_BY        = 13        # force-close at 13:00 UTC

TP_SCENARIOS = {
    "TP=1R":   1.0,
    "TP=1.5R": 1.5,
    "TP=2R":   2.0,
}

INSTRUMENTS = [
    ("EURUSD", "EURUSD=X", 0.0001),
    ("GBPUSD", "GBPUSD=X", 0.0001),
]

def fetch_h1(symbol):
    try:
        df = yf.download(symbol, interval="1h", period="730d",
                         auto_adjust=True, progress=False)
        if df is None or len(df) < 200:
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

def run_lb(df, pip_size, tp_mult):
    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day      = pd.Timestamp(date, tz='UTC')
        prev_day = day - pd.Timedelta(days=1)

        asian = df[
            (df.index >= prev_day + pd.Timedelta(hours=22)) &
            (df.index <  day     + pd.Timedelta(hours=7))
        ]
        if len(asian) < 4:
            continue

        a_hi   = asian['high'].max()
        a_lo   = asian['low'].min()
        rng    = a_hi - a_lo
        pips   = rng / pip_size

        if pips < MIN_RANGE_PIPS or pips > MAX_RANGE_PIPS:
            continue

        entry_window = df[
            (df.index >= day + pd.Timedelta(hours=ENTRY_FROM)) &
            (df.index <  day + pd.Timedelta(hours=ENTRY_TO))
        ]
        if len(entry_window) == 0:
            continue

        direction = entry_price = entry_time = None
        for bt, bar in entry_window.iterrows():
            if bar['high'] > a_hi:
                direction, entry_price, entry_time = 'buy',  a_hi, bt; break
            if bar['low']  < a_lo:
                direction, entry_price, entry_time = 'sell', a_lo, bt; break

        if direction is None:
            continue

        sl_buf = rng * SL_BUFFER
        if direction == 'buy':
            sl = a_lo - sl_buf
            tp = entry_price + abs(entry_price - sl) * tp_mult
        else:
            sl = a_hi + sl_buf
            tp = entry_price - abs(sl - entry_price) * tp_mult

        sl_dist = abs(entry_price - sl)
        if sl_dist <= 0:
            continue

        sim = df[(df.index > entry_time) &
                 (df.index <= day + pd.Timedelta(hours=EXIT_BY))]

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
            'date': day, 'reason': reason,
            'pnl_r': round(pnl_r, 2), 'pnl_gbp': round(pnl_gbp, 2)
        })

    if not trades:
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
    tp_pct  = (df_t['reason'] == 'tp').mean() * 100
    sl_pct  = (df_t['reason'] == 'sl').mean() * 100
    to_pct  = (df_t['reason'] == 'timeout').mean() * 100

    return {
        'n': n, 'tpm': tpm, 'wr': wr, 'pf': pf,
        'monthly': monthly, 'max_dd': max_dd,
        'tp_pct': tp_pct, 'sl_pct': sl_pct, 'to_pct': to_pct,
    }

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  LONDON BREAKOUT — TP SIZE COMPARISON  (1R vs 1.5R vs 2R)")
    print("  Asian range 22:00–07:00 UTC | Breakout 07:00–10:00 | Force-close 13:00")
    print("  EURUSD + GBPUSD | 2 years | 0.5% risk")
    print("="*80)

    all_results = {}

    for name, symbol, pip_size in INSTRUMENTS:
        print(f"\n  Fetching {name}...")
        df = fetch_h1(symbol)
        if df is None:
            print(f"  {name}: no data")
            continue

        print(f"\n  {'─'*76}")
        print(f"  {name}")
        print(f"  {'─'*76}")
        print(f"  {'Scenario':<12} {'T/mo':>6}  {'Win%':>6}  {'PF':>6}  {'Monthly@1%':>12}  "
              f"{'DD@1%':>10}  {'TP%':>5} {'SL%':>5} {'TO%':>5}")
        print(f"  {'─'*76}")

        sym_results = {}
        for label, tp_mult in TP_SCENARIOS.items():
            r = run_lb(df, pip_size, tp_mult)
            if r:
                sym_results[label] = r
                verdict = "✅" if r['pf'] >= 1.5 else ("⚠️ " if r['pf'] >= 1.2 else "❌")
                print(f"  {label:<12} {r['tpm']:>6.1f}  {r['wr']:>6.1f}%  {r['pf']:>6.2f}  "
                      f"£{r['monthly']*2:>10,.0f}  £{r['max_dd']*2:>8,.0f}  "
                      f"{r['tp_pct']:>5.0f}%{r['sl_pct']:>5.0f}%{r['to_pct']:>5.0f}%  {verdict}")

        all_results[name] = sym_results

    # Best scenario for each instrument
    print(f"\n{'='*80}")
    print(f"  VERDICT — BEST TP SIZE PER INSTRUMENT")
    print(f"{'='*80}")
    for name, sym_r in all_results.items():
        if not sym_r:
            continue
        best = max(sym_r.items(), key=lambda x: x[1]['pf'])
        label, r = best
        verdict = "✅ STRONG" if r['pf'] >= 1.5 else ("⚠️  OK" if r['pf'] >= 1.2 else "❌ WEAK")
        print(f"\n  {name}: best is {label}")
        print(f"     PF {r['pf']:.2f} | {r['wr']:.1f}% win | {r['tpm']:.1f}/mo | "
              f"£{r['monthly']*2:,.0f}/mo @1% | DD £{r['max_dd']*2:,.0f} @1%  {verdict}")

    # Combined best scenario
    print(f"\n  COMBINED (EURUSD + GBPUSD at optimal TP, 0.5% risk each):")
    for label in TP_SCENARIOS:
        totals = []
        for name, sym_r in all_results.items():
            if label in sym_r:
                totals.append(sym_r[label])
        if len(totals) == 2:
            combined_monthly = sum(r['monthly'] for r in totals)
            combined_tpm     = sum(r['tpm'] for r in totals)
            avg_pf           = sum(r['pf'] for r in totals) / 2
            # DDs are correlated — use the larger as approximate combined DD
            combined_dd      = min(r['max_dd'] for r in totals) * 2
            print(f"  {label:<10}  £{combined_monthly*2:,.0f}/mo @1% each | "
                  f"~{combined_tpm:.0f} trades/mo | "
                  f"avg PF {avg_pf:.2f} | "
                  f"DD ~£{abs(combined_dd):,.0f}")

    print(f"\n  FTMO: daily DD limit £3,500 | total DD limit £7,000")
    print(f"  Note: EURUSD + GBPUSD are ~85% correlated — use 0.4% risk each")
    print(f"  to keep combined DD comfortably under £7,000\n")
