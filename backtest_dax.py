"""
backtest_dax.py — DAX Strategy Backtester across timeframes
Tests GER40 on H4, H1 to find optimal timeframe for trade frequency vs edge.
Strategy: EMA 10/20 cross + ADX > 25 + candle confirmation + ATR SL/TP

Run: python backtest_dax.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

SYMBOL         = "^GDAXI"
ACCOUNT        = 70000
RISK_PCT       = 0.005   # 0.5% per trade = £350
EMA_FAST       = 10
EMA_SLOW       = 20
ADX_MIN        = 25
ADX_PERIOD     = 14
ATR_SL_MULT    = 1.5
ATR_TP_MULT    = 3.0     # 2R
SESSION_START  = 8       # UTC
SESSION_END    = 16      # UTC (DAX closes 16:30 UTC but avoid last 30 mins)

# ── Data ───────────────────────────────────────────────────────────────────────

def fetch(symbol, interval, period):
    print(f"  Fetching {symbol} {interval} ({period})...", end=" ")
    df = yf.download(symbol, interval=interval, period=period,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna()
    print(f"{len(df)} bars ({df.index[0].date()} → {df.index[-1].date()})")
    return df

def resample(df_1h, rule):
    df = df_1h.resample(rule).agg({
        'open': 'first', 'high': 'max',
        'low': 'min',    'close': 'last',
        'volume': 'sum'
    }).dropna()
    return df

# ── Indicators ─────────────────────────────────────────────────────────────────

def add_indicators(df):
    df = df.copy()

    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()

    hi, lo, cl = df['high'], df['low'], df['close']
    tr = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.ewm(com=ADX_PERIOD-1, adjust=False).mean()

    dmp = ((hi-hi.shift()) > (lo.shift()-lo)).astype(float) * (hi-hi.shift()).clip(lower=0)
    dmm = ((lo.shift()-lo) > (hi-hi.shift())).astype(float) * (lo.shift()-lo).clip(lower=0)
    atr_s = tr.ewm(com=ADX_PERIOD-1, adjust=False).mean()
    dip   = 100 * dmp.ewm(com=ADX_PERIOD-1, adjust=False).mean() / atr_s
    dim   = 100 * dmm.ewm(com=ADX_PERIOD-1, adjust=False).mean() / atr_s
    dx    = (100 * (dip-dim).abs() / (dip+dim).replace(0,1)).fillna(0)
    df['adx'] = dx.ewm(com=ADX_PERIOD-1, adjust=False).mean()

    # RSI
    delta = df['close'].diff()
    gain  = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

    # Candle patterns
    o, h, l, c = df['open'], df['high'], df['low'], df['close']
    body = (c-o).abs()
    r    = h - l

    df['bull_engulf'] = (c.shift() < o.shift()) & (c > o) & (o < c.shift()) & (c > o.shift())
    df['bear_engulf'] = (c.shift() > o.shift()) & (c < o) & (o > c.shift()) & (c < o.shift())

    lower_wick = pd.Series([
        min(df['open'].iloc[i], df['close'].iloc[i]) - df['low'].iloc[i]
        for i in range(len(df))
    ], index=df.index)
    upper_wick = pd.Series([
        df['high'].iloc[i] - max(df['open'].iloc[i], df['close'].iloc[i])
        for i in range(len(df))
    ], index=df.index)

    df['bull_pin'] = (lower_wick >= r * 0.6) & (body <= r * 0.3) & (r > 0)
    df['bear_pin'] = (upper_wick >= r * 0.6) & (body <= r * 0.3) & (r > 0)

    return df

# ── Signal ─────────────────────────────────────────────────────────────────────

def get_signal(df, i):
    if i < ADX_PERIOD + 5: return None
    bar  = df.iloc[i]
    prev = df.iloc[i-1]

    if bar['adx'] < ADX_MIN: return None

    bull_cross = bar['ema_fast'] > bar['ema_slow'] and prev['ema_fast'] <= prev['ema_slow']
    bear_cross = bar['ema_fast'] < bar['ema_slow'] and prev['ema_fast'] >= prev['ema_slow']
    bull_cont  = bar['ema_fast'] > bar['ema_slow'] and bar['adx'] > ADX_MIN + 5 and (bar['bull_engulf'] or bar['bull_pin'])
    bear_cont  = bar['ema_fast'] < bar['ema_slow'] and bar['adx'] > ADX_MIN + 5 and (bar['bear_engulf'] or bar['bear_pin'])

    if bull_cross or bull_cont: return 'buy'
    if bear_cross or bear_cont: return 'sell'
    return None

# ── Simulate trade ─────────────────────────────────────────────────────────────

def sim_trade(df, entry_i, entry, sl, tp, direction, atr_val, max_bars=120):
    sl_cur  = sl
    be_done = False
    be_level = entry + abs(entry - sl) if direction == 'buy' else entry - abs(entry - sl)

    for j in range(entry_i+1, min(entry_i+max_bars, len(df))):
        bar = df.iloc[j]

        if direction == 'buy':
            if bar['low']  <= sl_cur: return sl_cur, 'sl',      j-entry_i
            if bar['high'] >= tp:     return tp,     'tp',      j-entry_i
            if not be_done and bar['high'] >= be_level:
                be_done = True; sl_cur = entry
            if be_done:
                new_sl = bar['high'] - atr_val
                if new_sl > sl_cur: sl_cur = new_sl
        else:
            if bar['high'] >= sl_cur: return sl_cur, 'sl',      j-entry_i
            if bar['low']  <= tp:     return tp,     'tp',      j-entry_i
            if not be_done and bar['low'] <= be_level:
                be_done = True; sl_cur = entry
            if be_done:
                new_sl = bar['low'] + atr_val
                if new_sl < sl_cur: sl_cur = new_sl

    last = df.iloc[min(entry_i+max_bars-1, len(df)-1)]
    return last['close'], 'timeout', min(max_bars-1, len(df)-entry_i-1)

# ── Run backtest ───────────────────────────────────────────────────────────────

def run(df, label, min_gap=2):
    trades = []
    last_i = -min_gap
    risk   = ACCOUNT * RISK_PCT

    for i in range(50, len(df)-1):
        bar = df.iloc[i]
        h   = bar.name.hour
        if h < SESSION_START or h >= SESSION_END: continue
        if i - last_i < min_gap: continue
        if trades and trades[-1].get('exit_i', 0) > i: continue

        direction = get_signal(df, i)
        if direction is None: continue

        entry   = bar['close']
        atr_val = bar['atr']
        if atr_val <= 0: continue

        sl_dist = ATR_SL_MULT * atr_val
        tp_dist = ATR_TP_MULT * atr_val
        sl = entry - sl_dist if direction=='buy' else entry + sl_dist
        tp = entry + tp_dist if direction=='buy' else entry - tp_dist

        ex_price, reason, bars = sim_trade(df, i, entry, sl, tp, direction, atr_val)

        pnl_pts = (ex_price - entry) if direction=='buy' else (entry - ex_price)
        pnl_r   = pnl_pts / sl_dist
        pnl_gbp = risk * pnl_r

        trades.append({
            'date':      bar.name,
            'direction': direction,
            'entry':     round(entry, 1),
            'exit':      round(ex_price, 1),
            'adx':       round(bar['adx'], 1),
            'atr':       round(atr_val, 1),
            'reason':    reason,
            'pnl_r':     round(pnl_r, 2),
            'pnl_gbp':   round(pnl_gbp, 2),
            'bars':      bars,
            'exit_i':    i + bars
        })
        last_i = i

    return print_results(trades, label)

# ── Results ────────────────────────────────────────────────────────────────────

def print_results(trades, label):
    if not trades:
        print(f"  No trades for {label}")
        return {}

    df_t   = pd.DataFrame(trades)
    wins   = df_t[df_t['pnl_gbp'] > 5]
    losses = df_t[df_t['pnl_gbp'] < -5]
    scratch= df_t[(df_t['pnl_gbp'] >= -5) & (df_t['pnl_gbp'] <= 5)]

    n         = len(df_t)
    win_rate  = len(wins) / n * 100
    total_pnl = df_t['pnl_gbp'].sum()
    avg_win   = wins['pnl_gbp'].mean()   if len(wins)   > 0 else 0
    avg_loss  = losses['pnl_gbp'].mean() if len(losses) > 0 else 0
    avg_r     = df_t['pnl_r'].mean()
    gp        = wins['pnl_gbp'].sum()   if len(wins)   > 0 else 0
    gl        = abs(losses['pnl_gbp'].sum()) if len(losses) > 0 else 1
    pf        = gp / gl

    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    df_t['dd']   = df_t['cum'] - df_t['peak']
    max_dd       = df_t['dd'].min()

    days      = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly   = total_pnl / days * 30
    trades_pm = n / (days / 30)

    by_reason = df_t.groupby('reason').agg(
        count=('pnl_gbp','count'),
        avg_r=('pnl_r','mean'),
        total=('pnl_gbp','sum')
    ).round(2)

    print(f"\n  ┌─ {label}")
    print(f"  │  Period:         {df_t['date'].iloc[0].date()} → {df_t['date'].iloc[-1].date()}")
    print(f"  │  Total trades:   {n}  (~{trades_pm:.1f}/month)")
    print(f"  │  Win rate:       {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L / {len(scratch)} scratch)")
    print(f"  │  Avg R:          {avg_r:+.3f}R")
    print(f"  │  Total P&L:      £{total_pnl:,.2f}")
    print(f"  │  Monthly est.:   £{monthly:,.0f}/month")
    print(f"  │  Avg win:        £{avg_win:,.2f}")
    print(f"  │  Avg loss:       £{avg_loss:,.2f}")
    print(f"  │  Profit factor:  {pf:.2f}")
    print(f"  │  Max drawdown:   £{max_dd:,.2f}")
    print(f"  │")
    print(f"  │  Exit breakdown:")
    for reason, row in by_reason.iterrows():
        print(f"  │    {reason:<10} {int(row['count']):>3} | avg {row['avg_r']:>+.2f}R | total £{row['total']:>8.2f}")
    print(f"  └{'─'*56}")

    return {
        'label': label, 'trades': n, 'trades_pm': trades_pm,
        'win_rate': win_rate, 'avg_r': avg_r,
        'total_pnl': total_pnl, 'monthly': monthly,
        'profit_factor': pf, 'max_dd': max_dd
    }

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*62)
    print("  DAX TIMEFRAME COMPARISON — GER40")
    print("  Strategy: EMA 10/20 + ADX > 25 + candle confirmation")
    print("  Risk: 0.5% | SL: 1.5×ATR | TP: 3×ATR (2R) | BE at 1R")
    print("="*62)

    # Fetch 2 years of 1H data
    print("\n  Loading data...")
    df_1h = fetch(SYMBOL, "1h", "730d")

    results = []

    # H4 (resampled)
    print(f"\n{'='*62}\n  H4 Timeframe (resampled from 1H)\n{'='*62}")
    df_h4 = resample(df_1h, '4h')
    df_h4 = add_indicators(df_h4)
    print(f"  H4 bars: {len(df_h4)}")
    r = run(df_h4, "DAX H4", min_gap=2)
    if r: results.append(r)

    # H1
    print(f"\n{'='*62}\n  H1 Timeframe\n{'='*62}")
    df_h1 = add_indicators(df_1h.copy())
    print(f"  H1 bars: {len(df_h1)}")
    r = run(df_h1, "DAX H1", min_gap=2)
    if r: results.append(r)

    # H1 with higher ADX filter (quality filter)
    print(f"\n{'='*62}\n  H1 Timeframe — Higher ADX filter (ADX > 30)\n{'='*62}")
    original_adx = ADX_MIN
    import sys
    # Monkey-patch ADX_MIN for this run
    _orig = ADX_MIN

    class _Cfg:
        pass

    # Run with stricter ADX by filtering df
    df_h1_strict = df_h1.copy()
    trades_strict = []
    last_i = -2
    risk   = ACCOUNT * RISK_PCT
    for i in range(50, len(df_h1_strict)-1):
        bar = df_h1_strict.iloc[i]
        h   = bar.name.hour
        if h < SESSION_START or h >= SESSION_END: continue
        if i - last_i < 2: continue
        if trades_strict and trades_strict[-1].get('exit_i', 0) > i: continue
        if bar['adx'] < 30: continue  # stricter filter

        prev = df_h1_strict.iloc[i-1]
        bull_cross = bar['ema_fast'] > bar['ema_slow'] and prev['ema_fast'] <= prev['ema_slow']
        bear_cross = bar['ema_fast'] < bar['ema_slow'] and prev['ema_fast'] >= prev['ema_slow']
        bull_cont  = bar['ema_fast'] > bar['ema_slow'] and bar['adx'] > 35 and (bar['bull_engulf'] or bar['bull_pin'])
        bear_cont  = bar['ema_fast'] < bar['ema_slow'] and bar['adx'] > 35 and (bar['bear_engulf'] or bar['bear_pin'])

        if bull_cross or bull_cont: direction = 'buy'
        elif bear_cross or bear_cont: direction = 'sell'
        else: continue

        entry   = bar['close']
        atr_val = bar['atr']
        if atr_val <= 0: continue

        sl_dist = ATR_SL_MULT * atr_val
        tp_dist = ATR_TP_MULT * atr_val
        sl = entry - sl_dist if direction=='buy' else entry + sl_dist
        tp = entry + tp_dist if direction=='buy' else entry - tp_dist

        ex_price, reason, bars = sim_trade(df_h1_strict, i, entry, sl, tp, direction, atr_val)
        pnl_pts = (ex_price - entry) if direction=='buy' else (entry - ex_price)
        pnl_r   = pnl_pts / sl_dist
        pnl_gbp = risk * pnl_r

        trades_strict.append({
            'date': bar.name, 'direction': direction,
            'entry': round(entry,1), 'exit': round(ex_price,1),
            'adx': round(bar['adx'],1), 'atr': round(atr_val,1),
            'reason': reason, 'pnl_r': round(pnl_r,2),
            'pnl_gbp': round(pnl_gbp,2), 'bars': bars, 'exit_i': i+bars
        })
        last_i = i

    r = print_results(trades_strict, "DAX H1 (ADX > 30)")
    if r: results.append(r)

    # Summary
    print(f"\n{'='*62}")
    print(f"  TIMEFRAME COMPARISON SUMMARY")
    print(f"{'='*62}")
    print(f"  {'Timeframe':<25} {'Win%':>5}  {'T/mo':>5}  {'Monthly':>9}  {'PF':>5}  {'Max DD':>9}")
    print(f"  {'─'*60}")
    for r in results:
        print(f"  {r['label']:<25} {r['win_rate']:>4.1f}%  {r['trades_pm']:>5.1f}  "
              f"£{r['monthly']:>7,.0f}  {r['profit_factor']:>5.2f}  £{r['max_dd']:>7,.0f}")

    print(f"\n  At 1% risk (double everything above):")
    for r in results:
        print(f"  {r['label']:<25} Monthly: £{r['monthly']*2:,.0f}  Max DD: £{r['max_dd']*2:,.0f}")

    print(f"\n  At 2% risk (4x everything above):")
    for r in results:
        print(f"  {r['label']:<25} Monthly: £{r['monthly']*4:,.0f}  Max DD: £{r['max_dd']*4:,.0f}")

    print(f"\n  FTMO daily limit (5% = £3,500). Watch max DD at higher risk.\n")
