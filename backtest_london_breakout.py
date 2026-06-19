"""
backtest_london_breakout.py — London Breakout Strategy
Strategy: Asian session (22:00–07:00 UTC) forms a consolidation range.
At London open (07:00–10:00 UTC) trade the first breakout of that range.
Exit at TP, SL, or 13:00 UTC (London morning session only).

Instruments: EURUSD, GBPUSD, GBPJPY, USDJPY
Fires: Daily (highest frequency strategy in this project)
Run: python backtest_london_breakout.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT      = 70000
RISK_PCT     = 0.005   # 0.5% per trade
TP_R         = 2.0     # take profit at 2x SL distance
SL_BUFFER    = 0.15    # SL = opposite range edge + 15% of range size (buffer for noise)
MIN_RANGE_PIPS = 10    # skip days with tiny range (no clear consolidation)
MAX_RANGE_PIPS = 100   # skip days with huge range (overnight news, avoid)
ENTRY_FROM   = 7       # earliest UTC hour to look for breakout (07:00)
ENTRY_TO     = 10      # latest UTC hour to enter (cancel if not triggered by 10:00)
EXIT_BY      = 13      # force-close at 13:00 UTC

INSTRUMENTS = [
    # name, yfinance symbol, pip_size (for range filter)
    ("EURUSD", "EURUSD=X", 0.0001),
    ("GBPUSD", "GBPUSD=X", 0.0001),
    ("GBPJPY", "GBPJPY=X", 0.01),
    ("USDJPY", "USDJPY=X", 0.01),
    ("AUDUSD", "AUDUSD=X", 0.0001),
    ("EURCAD", "EURCAD=X", 0.0001),
]

# ── Data ──────────────────────────────────────────────────────────────────────

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
        # Normalise to UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')
        return df
    except Exception as e:
        return None

# ── Backtest single instrument ─────────────────────────────────────────────────

def run_instrument(name, symbol, pip_size):
    df = fetch_h1(symbol)
    if df is None:
        print(f"  {name:<10} — no data")
        return None

    trades = []
    risk = ACCOUNT * RISK_PCT

    # Iterate over each calendar date present in the data
    all_dates = sorted(set(df.index.normalize().date))

    for date in all_dates:
        day = pd.Timestamp(date, tz='UTC')
        prev_day = day - pd.Timedelta(days=1)

        # Asian session range: 22:00 prev day → 07:00 current day
        asian_start = prev_day + pd.Timedelta(hours=22)
        asian_end   = day       + pd.Timedelta(hours=7)

        asian_bars = df[(df.index >= asian_start) & (df.index < asian_end)]
        if len(asian_bars) < 4:
            continue

        asian_high = asian_bars['high'].max()
        asian_low  = asian_bars['low'].min()
        range_size = asian_high - asian_low
        range_pips = range_size / pip_size

        # Skip if range is too tight (choppy) or too wide (news spike overnight)
        if range_pips < MIN_RANGE_PIPS or range_pips > MAX_RANGE_PIPS:
            continue

        # London entry window: 07:00–10:00 UTC — first bar to break the range
        entry_window = df[
            (df.index >= day + pd.Timedelta(hours=ENTRY_FROM)) &
            (df.index <  day + pd.Timedelta(hours=ENTRY_TO))
        ]
        if len(entry_window) == 0:
            continue

        direction    = None
        entry_price  = None
        entry_time   = None

        for bar_time, bar in entry_window.iterrows():
            # Price broke above Asian high during this bar
            if bar['high'] > asian_high and direction is None:
                direction   = 'buy'
                entry_price = asian_high  # enter at breakout level (limit order filled)
                entry_time  = bar_time
                break
            # Price broke below Asian low during this bar
            if bar['low'] < asian_low and direction is None:
                direction   = 'sell'
                entry_price = asian_low
                entry_time  = bar_time
                break

        if direction is None:
            continue  # no breakout today

        # SL: opposite side of range + buffer
        sl_buf = range_size * SL_BUFFER
        if direction == 'buy':
            sl = asian_low  - sl_buf
            tp = entry_price + (entry_price - sl) * TP_R
        else:
            sl = asian_high + sl_buf
            tp = entry_price - (sl - entry_price) * TP_R

        sl_dist = abs(entry_price - sl)
        if sl_dist <= 0:
            continue

        # Simulate trade: bars from entry_time to EXIT_BY
        close_time = day + pd.Timedelta(hours=EXIT_BY)
        sim_bars = df[(df.index > entry_time) & (df.index <= close_time)]

        ex_price = None
        reason   = 'timeout'

        for _, bar in sim_bars.iterrows():
            if direction == 'buy':
                if bar['low'] <= sl:
                    ex_price = sl;  reason = 'sl';  break
                if bar['high'] >= tp:
                    ex_price = tp;  reason = 'tp';  break
            else:
                if bar['high'] >= sl:
                    ex_price = sl;  reason = 'sl';  break
                if bar['low'] <= tp:
                    ex_price = tp;  reason = 'tp';  break

        if ex_price is None:
            # Force-close at last bar available in window
            if len(sim_bars) > 0:
                ex_price = sim_bars.iloc[-1]['close']
                reason   = 'timeout'
            else:
                ex_price = entry_price
                reason   = 'timeout'

        pnl_r   = ((ex_price - entry_price) if direction == 'buy'
                   else (entry_price - ex_price)) / sl_dist
        pnl_gbp = risk * pnl_r

        trades.append({
            'date':       day,
            'direction':  direction,
            'pnl_r':      round(pnl_r, 2),
            'pnl_gbp':    round(pnl_gbp, 2),
            'reason':     reason,
            'range_pips': round(range_pips, 1),
        })

    if not trades:
        print(f"  {name:<10} — 0 trades")
        return None

    df_t     = pd.DataFrame(trades)
    wins     = df_t[df_t['pnl_gbp'] > 5]
    losses   = df_t[df_t['pnl_gbp'] < -5]
    n        = len(df_t)
    win_rate = len(wins) / n * 100
    gp       = wins['pnl_gbp'].sum()   if len(wins)   > 0 else 0
    gl       = abs(losses['pnl_gbp'].sum()) if len(losses) > 0 else 1
    pf       = gp / gl
    total    = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd   = (df_t['cum'] - df_t['peak']).min()
    days     = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly  = total / days * 30
    tpm      = n / (days / 30)
    avg_r    = df_t['pnl_r'].mean()

    # Reason breakdown
    tp_pct  = (df_t['reason'] == 'tp').mean() * 100
    sl_pct  = (df_t['reason'] == 'sl').mean() * 100
    to_pct  = (df_t['reason'] == 'timeout').mean() * 100

    verdict = "✅ STRONG" if pf >= 1.5 else ("⚠️  OK" if pf >= 1.2 else "❌ WEAK")
    print(f"  {name:<10} {win_rate:>5.1f}%  {tpm:>5.1f}/mo  "
          f"£{monthly*2:>7,.0f}@1%  PF:{pf:>5.2f}  DD:{max_dd*2:>7,.0f}  "
          f"TP:{tp_pct:.0f}% SL:{sl_pct:.0f}% TO:{to_pct:.0f}%  {verdict}")

    return {
        'name': name, 'trades': n, 'tpm': tpm, 'win_rate': win_rate,
        'avg_r': avg_r, 'total': total, 'monthly': monthly,
        'pf': pf, 'max_dd': max_dd,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  LONDON BREAKOUT — EURUSD, GBPUSD, GBPJPY, USDJPY, AUDUSD, EURCAD")
    print("  Asian range (22:00–07:00 UTC) | Breakout entry 07:00–10:00 | Exit 13:00")
    print("  2 years | 0.5% risk | TP=2R | SL=opposite range edge + buffer")
    print("="*80)
    print(f"\n  {'Symbol':<10} {'Win%':>5}  {'T/mo':>6}  {'Monthly@1%':>11}  {'PF':>7}  {'DD@1%':>8}"
          f"  {'TP% SL% TO%':>14}  Verdict")
    print(f"  {'─'*76}")

    results = []
    for name, symbol, pip_size in INSTRUMENTS:
        r = run_instrument(name, symbol, pip_size)
        if r:
            results.append(r)

    results.sort(key=lambda x: x['pf'], reverse=True)
    strong = [r for r in results if r['pf'] >= 1.5]
    ok     = [r for r in results if 1.2 <= r['pf'] < 1.5]

    print(f"\n{'='*80}")
    print(f"  LONDON BREAKOUT — RANKED RESULTS")
    print(f"{'='*80}")

    print(f"\n  ✅ STRONG EDGE (PF >= 1.5):")
    for r in strong:
        print(f"     {r['name']:<10} PF {r['pf']:.2f} | {r['win_rate']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    print(f"\n  ⚠️  MARGINAL (PF 1.2–1.5):")
    for r in ok:
        print(f"     {r['name']:<10} PF {r['pf']:.2f} | {r['win_rate']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    if strong:
        combined_monthly = sum(r['monthly'] * 2 for r in strong)
        combined_tpm     = sum(r['tpm'] for r in strong)
        combined_dd      = sum(r['max_dd'] * 2 for r in strong)
        print(f"\n  COMBINED (strong only, 1% risk each):")
        print(f"  Monthly:       £{combined_monthly:,.0f}/month")
        print(f"  Trades/month:  ~{combined_tpm:.0f} ({combined_tpm/4:.1f}/week)")
        print(f"  Key advantage: fires DAILY — higher frequency than H4 EMA")

    print(f"\n  FTMO: daily limit £3,500 | total drawdown limit £7,000")
    print(f"  Recommend: 0.75% risk per trade for FTMO safety margin\n")
