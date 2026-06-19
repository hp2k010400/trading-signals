"""
backtest_h4.py — H4 Trend Following Strategy Backtester
Instruments: XAUUSD (Gold), NAS100, GER40 (DAX)
Strategy: H4 EMA 10/20 cross + ADX > 25 + ATR-based SL/TP
Data: ~2 years of 1H data resampled to H4 via yfinance

Run: python backtest_h4.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

# ── Instrument configs ─────────────────────────────────────────────────────────

INSTRUMENTS = [
    {
        "name":         "XAUUSD — Gold",
        "symbol":       "GC=F",
        "session_start": 8,    # UTC — London + NY
        "session_end":   20,
        "atr_sl_mult":   1.5,
        "atr_tp_mult":   3.0,  # 2R
        "point_value":   100,  # $100 per point per lot (approx)
        "currency":      "USD",
    },
    {
        "name":         "NAS100 — Nasdaq",
        "symbol":       "NQ=F",
        "session_start": 13,   # UTC — NY session
        "session_end":   21,
        "atr_sl_mult":   1.5,
        "atr_tp_mult":   3.0,
        "point_value":   20,   # $20 per point per contract (approx)
        "currency":      "USD",
    },
    {
        "name":         "GER40 — DAX",
        "symbol":       "^GDAXI",
        "session_start": 8,    # UTC — European session
        "session_end":   16,
        "atr_sl_mult":   1.5,
        "atr_tp_mult":   3.0,
        "point_value":   25,   # €25 per point per lot (approx)
        "currency":      "EUR",
    },
]

ACCOUNT_BALANCE = 70000
RISK_PCT        = 0.005   # 0.5% risk per trade
EMA_FAST        = 10
EMA_SLOW        = 20
ADX_MIN         = 25
ADX_PERIOD      = 14
MIN_ADX_BARS    = 3       # ADX must be > min for this many consecutive bars (trend quality)

# ── Data ───────────────────────────────────────────────────────────────────────

def fetch_1h(symbol, period="730d"):
    print(f"  Fetching {symbol} 1H ({period})...", end=" ")
    df = yf.download(symbol, interval="1h", period=period,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna()
    print(f"{len(df)} bars ({df.index[0].date()} → {df.index[-1].date()})")
    return df

def resample_to_h4(df_1h):
    """Resample 1H OHLCV to H4."""
    df = df_1h.resample('4h').agg({
        'open':   'first',
        'high':   'max',
        'low':    'min',
        'close':  'last',
        'volume': 'sum'
    }).dropna()
    return df

# ── Indicators ─────────────────────────────────────────────────────────────────

def add_indicators(df):
    df = df.copy()

    # EMA
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()

    # ATR
    hi, lo, cl = df['high'], df['low'], df['close']
    tr = pd.concat([
        hi - lo,
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.ewm(com=ADX_PERIOD - 1, adjust=False).mean()

    # ADX
    dmp = ((hi - hi.shift()) > (lo.shift() - lo)).astype(float) * (hi - hi.shift()).clip(lower=0)
    dmm = ((lo.shift() - lo) > (hi - hi.shift())).astype(float) * (lo.shift() - lo).clip(lower=0)
    atr_s  = tr.ewm(com=ADX_PERIOD - 1, adjust=False).mean()
    dip    = 100 * dmp.ewm(com=ADX_PERIOD - 1, adjust=False).mean() / atr_s
    dim    = 100 * dmm.ewm(com=ADX_PERIOD - 1, adjust=False).mean() / atr_s
    dx     = (100 * (dip - dim).abs() / (dip + dim).replace(0, 1)).fillna(0)
    df['adx'] = dx.ewm(com=ADX_PERIOD - 1, adjust=False).mean()

    # RSI
    delta    = df['close'].diff()
    gain     = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss     = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

    return df

def add_candle_patterns(df):
    df = df.copy()
    o, h, l, c = df['open'], df['high'], df['low'], df['close']
    body   = (c - o).abs()
    r      = h - l

    # Bullish engulfing
    df['bull_engulf'] = (
        (c.shift() < o.shift()) &
        (c > o) &
        (o < c.shift()) &
        (c > o.shift())
    )

    # Bearish engulfing
    df['bear_engulf'] = (
        (c.shift() > o.shift()) &
        (c < o) &
        (o > c.shift()) &
        (c < o.shift())
    )

    # Bullish pin bar
    lower_wick = l.apply(lambda x: x)
    lower_wick = pd.Series([
        min(df['open'].iloc[i], df['close'].iloc[i]) - df['low'].iloc[i]
        for i in range(len(df))
    ], index=df.index)
    df['bull_pin'] = (lower_wick >= r * 0.6) & (body <= r * 0.3) & (r > 0)

    # Bearish pin bar
    upper_wick = pd.Series([
        df['high'].iloc[i] - max(df['open'].iloc[i], df['close'].iloc[i])
        for i in range(len(df))
    ], index=df.index)
    df['bear_pin'] = (upper_wick >= r * 0.6) & (body <= r * 0.3) & (r > 0)

    return df

# ── Trade simulation ───────────────────────────────────────────────────────────

def sim_trade(df, entry_i, entry, sl, tp, direction, atr_val):
    """Simulate trade bar by bar with breakeven and trail."""
    sl_cur  = sl
    be_done = False
    be_level = entry + (entry - sl) if direction == 'buy' else entry - (sl - entry)

    for j in range(entry_i + 1, min(entry_i + 120, len(df))):
        bar = df.iloc[j]

        # SL hit
        if direction == 'buy'  and bar['low']  <= sl_cur: return sl_cur, 'sl',  j - entry_i
        if direction == 'sell' and bar['high'] >= sl_cur: return sl_cur, 'sl',  j - entry_i

        # TP hit
        if direction == 'buy'  and bar['high'] >= tp: return tp, 'tp', j - entry_i
        if direction == 'sell' and bar['low']  <= tp: return tp, 'tp', j - entry_i

        # Breakeven at 1R
        if not be_done:
            if direction == 'buy'  and bar['high'] >= be_level:
                be_done = True
                sl_cur  = entry
            elif direction == 'sell' and bar['low'] <= be_level:
                be_done = True
                sl_cur  = entry

        # Trail after breakeven (1 ATR trail)
        if be_done:
            if direction == 'buy':
                new_sl = bar['high'] - atr_val
                if new_sl > sl_cur: sl_cur = new_sl
            else:
                new_sl = bar['low']  + atr_val
                if new_sl < sl_cur: sl_cur = new_sl

    last = df.iloc[min(entry_i + 119, len(df) - 1)]
    return last['close'], 'timeout', min(119, len(df) - entry_i - 1)

# ── Strategy signals ───────────────────────────────────────────────────────────

def get_signal(df, i):
    """
    Signal: EMA cross confirmation + ADX > ADX_MIN + candle pattern.
    Returns: 'buy', 'sell', or None
    """
    if i < ADX_PERIOD + 5: return None

    bar  = df.iloc[i]
    prev = df.iloc[i - 1]

    # ADX gate
    if bar['adx'] < ADX_MIN: return None

    # EMA cross this bar
    bull_cross = bar['ema_fast'] > bar['ema_slow'] and prev['ema_fast'] <= prev['ema_slow']
    bear_cross = bar['ema_fast'] < bar['ema_slow'] and prev['ema_fast'] >= prev['ema_slow']

    # Candle confirmation
    bull_candle = bar['bull_engulf'] or bar['bull_pin']
    bear_candle = bar['bear_engulf'] or bar['bear_pin']

    # Also allow trend continuation: EMA aligned, ADX strong, candle confirms
    bull_cont = bar['ema_fast'] > bar['ema_slow'] and bar['adx'] > ADX_MIN + 5 and bull_candle
    bear_cont = bar['ema_fast'] < bar['ema_slow'] and bar['adx'] > ADX_MIN + 5 and bear_candle

    if bull_cross or bull_cont: return 'buy'
    if bear_cross or bear_cont: return 'sell'
    return None

# ── Main backtest ──────────────────────────────────────────────────────────────

def run_backtest(cfg):
    print(f"\n{'='*62}")
    print(f"  {cfg['name']}")
    print(f"{'='*62}")

    df_1h = fetch_1h(cfg['symbol'])
    df    = resample_to_h4(df_1h)
    df    = add_indicators(df)
    df    = add_candle_patterns(df)

    print(f"  H4 bars: {len(df)} ({df.index[0].date()} → {df.index[-1].date()})")

    trades  = []
    last_i  = -5
    risk_am = ACCOUNT_BALANCE * RISK_PCT

    for i in range(50, len(df) - 1):
        bar = df.iloc[i]

        # Session filter (UTC)
        h = bar.name.hour
        if h < cfg['session_start'] or h >= cfg['session_end']: continue

        # Cooldown — 1 H4 bar gap minimum
        if i - last_i < 2: continue

        # Skip if last trade still open
        if trades and trades[-1].get('exit_i', 0) > i: continue

        direction = get_signal(df, i)
        if direction is None: continue

        entry   = bar['close']
        atr_val = bar['atr']
        if atr_val <= 0: continue

        sl_dist = cfg['atr_sl_mult'] * atr_val
        tp_dist = cfg['atr_tp_mult'] * atr_val

        sl = entry - sl_dist if direction == 'buy' else entry + sl_dist
        tp = entry + tp_dist if direction == 'buy' else entry - tp_dist

        ex_price, reason, bars = sim_trade(df, i, entry, sl, tp, direction, atr_val)

        # P&L in R multiples
        pnl_pts  = (ex_price - entry) if direction == 'buy' else (entry - ex_price)
        pnl_r    = pnl_pts / sl_dist
        pnl_gbp  = risk_am * pnl_r

        trades.append({
            'date':      bar.name,
            'direction': direction,
            'entry':     round(entry, 2),
            'exit':      round(ex_price, 2),
            'sl_dist':   round(sl_dist, 2),
            'tp_dist':   round(tp_dist, 2),
            'atr':       round(atr_val, 2),
            'adx':       round(bar['adx'], 1),
            'reason':    reason,
            'pnl_r':     round(pnl_r, 2),
            'pnl_gbp':   round(pnl_gbp, 2),
            'bars':      bars,
            'exit_i':    i + bars
        })

        last_i = i

    return print_results(trades, cfg['name'])

# ── Results ────────────────────────────────────────────────────────────────────

def print_results(trades, name):
    if not trades:
        print("  No trades generated.")
        return {}

    df_t   = pd.DataFrame(trades)
    wins   = df_t[df_t['pnl_gbp'] > 0]
    losses = df_t[df_t['pnl_gbp'] <= 0]

    n          = len(df_t)
    win_rate   = len(wins) / n * 100
    total_pnl  = df_t['pnl_gbp'].sum()
    avg_win    = wins['pnl_gbp'].mean()   if len(wins)   > 0 else 0
    avg_loss   = losses['pnl_gbp'].mean() if len(losses) > 0 else 0
    avg_r      = df_t['pnl_r'].mean()
    gp         = wins['pnl_gbp'].sum()   if len(wins)   > 0 else 0
    gl         = abs(losses['pnl_gbp'].sum()) if len(losses) > 0 else 1
    pf         = gp / gl

    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    df_t['dd']   = df_t['cum'] - df_t['peak']
    max_dd       = df_t['dd'].min()

    days      = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly   = total_pnl / days * 30
    trades_pm = n / (days / 30)

    by_reason = df_t.groupby('reason').agg(
        count   = ('pnl_gbp', 'count'),
        avg_pnl = ('pnl_gbp', 'mean'),
        avg_r   = ('pnl_r',   'mean'),
        total   = ('pnl_gbp', 'sum')
    ).round(2)

    # Avg ADX on winning vs losing trades
    adx_wins   = wins['adx'].mean()   if len(wins)   > 0 else 0
    adx_losses = losses['adx'].mean() if len(losses) > 0 else 0

    print(f"\n  ┌─ {name}")
    print(f"  │  Period:          {df_t['date'].iloc[0].date()} → {df_t['date'].iloc[-1].date()}")
    print(f"  │  Total trades:    {n}  (~{trades_pm:.1f}/month)")
    print(f"  │  Win rate:        {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L)")
    print(f"  │  Avg R per trade: {avg_r:.2f}R")
    print(f"  │  Total P&L:       £{total_pnl:,.2f}")
    print(f"  │  Monthly est.:    £{monthly:,.0f}/month")
    print(f"  │  Avg win:         £{avg_win:,.2f}")
    print(f"  │  Avg loss:        £{avg_loss:,.2f}")
    print(f"  │  Profit factor:   {pf:.2f}")
    print(f"  │  Max drawdown:    £{max_dd:,.2f}")
    print(f"  │  ADX avg (W/L):   {adx_wins:.1f} / {adx_losses:.1f}")
    print(f"  │")
    print(f"  │  Exit breakdown:")
    for reason, row in by_reason.iterrows():
        print(f"  │    {reason:<10} {int(row['count']):>3} trades | avg {row['avg_r']:>+.2f}R | avg £{row['avg_pnl']:>8.2f} | total £{row['total']:>9.2f}")
    print(f"  └{'─'*58}")

    return {
        'name': name, 'trades': n, 'trades_pm': trades_pm,
        'win_rate': win_rate, 'avg_r': avg_r,
        'total_pnl': total_pnl, 'monthly': monthly,
        'profit_factor': pf, 'max_dd': max_dd
    }

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*62)
    print("  H4 TREND FOLLOWING BACKTESTER")
    print("  Strategy: EMA 10/20 cross + ADX > 25 + candle confirmation")
    print("  Risk: 0.5% per trade | Breakeven at 1R | Trail after")
    print("  SL: 1.5× ATR  |  TP: 3× ATR (2R)")
    print("  Account: £70,000")
    print("="*62)

    results = []
    for cfg in INSTRUMENTS:
        r = run_backtest(cfg)
        if r:
            results.append(r)

    # Combined summary
    print(f"\n{'='*62}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*62}")
    print(f"  {'Instrument':<25} {'Win%':>5}  {'Avg R':>6}  {'Monthly':>9}  {'PF':>5}  {'Max DD':>9}")
    print(f"  {'─'*60}")
    for r in results:
        print(f"  {r['name']:<25} {r['win_rate']:>4.1f}%  {r['avg_r']:>+.2f}R  £{r['monthly']:>7,.0f}  {r['profit_factor']:>5.2f}  £{r['max_dd']:>7,.0f}")

    if results:
        total_monthly = sum(r['monthly'] for r in results)
        total_trades  = sum(r['trades_pm'] for r in results)
        print(f"\n  Combined (all 3 instruments):")
        print(f"  Monthly est:   £{total_monthly:,.0f}/month")
        print(f"  Trades/month:  ~{total_trades:.0f}")
        print(f"\n  Note: spread not included (~0.1-0.3% drag on each trade)")
        print(f"  Note: data is price proxies (futures/index) not exact CFD prices")
        print(f"  Note: PF > 1.3 = decent edge | PF > 1.5 = strong edge\n")
