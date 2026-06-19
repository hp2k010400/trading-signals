"""
backtest_vwap.py — VWAP Pullback Strategy Backtester
Instrument: GER40 (DAX) — tested on M15 and H1
Strategy: Price above/below daily VWAP = bias. Trade pullbacks TO VWAP with candle confirmation.
Data: yfinance 1H data (~2 years) + 15m data (60 days)

Run: python backtest_vwap.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

SYMBOL        = "^GDAXI"
ACCOUNT       = 70000
RISK_PCT      = 0.005    # 0.5% per trade = £350
SESSION_START = 8        # UTC
SESSION_END   = 16       # UTC
ADX_MIN       = 20       # trend strength gate
ATR_PERIOD    = 14
SL_ATR_MULT   = 1.0      # SL = 1 ATR (tighter than H4 because entry is precise)
TP_ATR_MULT   = 2.0      # TP = 2 ATR = 2R
BE_ATR_MULT   = 0.8      # move SL to entry after 0.8 ATR profit
VWAP_ZONE     = 0.0015   # price must be within 0.15% of VWAP to qualify
MAX_BARS      = 48       # max hold = 48 bars (12 hrs on H1, 12 hrs on M15)

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

# ── VWAP calculation ───────────────────────────────────────────────────────────

def add_vwap(df):
    """Daily VWAP — resets each trading day."""
    df = df.copy()
    df['typical'] = (df['high'] + df['low'] + df['close']) / 3

    vwap_vals = []
    current_date = None
    cum_tp_vol = 0.0
    cum_vol    = 0.0

    for idx, row in df.iterrows():
        bar_date = idx.date()
        if bar_date != current_date:
            current_date = bar_date
            cum_tp_vol   = 0.0
            cum_vol      = 0.0

        vol = row['volume'] if row['volume'] > 0 else 1.0
        cum_tp_vol += row['typical'] * vol
        cum_vol    += vol
        vwap_vals.append(cum_tp_vol / cum_vol)

    df['vwap'] = vwap_vals
    df['vwap_dist_pct'] = (df['close'] - df['vwap']) / df['vwap']  # + = above, - = below
    return df

# ── Indicators ─────────────────────────────────────────────────────────────────

def add_indicators(df):
    df = df.copy()

    # ATR
    hi, lo, cl = df['high'], df['low'], df['close']
    tr  = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.ewm(com=ATR_PERIOD-1, adjust=False).mean()

    # ADX
    dmp = ((hi-hi.shift()) > (lo.shift()-lo)).astype(float) * (hi-hi.shift()).clip(lower=0)
    dmm = ((lo.shift()-lo) > (hi-hi.shift())).astype(float) * (lo.shift()-lo).clip(lower=0)
    atr_s = tr.ewm(com=ATR_PERIOD-1, adjust=False).mean()
    dip   = 100 * dmp.ewm(com=ATR_PERIOD-1, adjust=False).mean() / atr_s
    dim   = 100 * dmm.ewm(com=ATR_PERIOD-1, adjust=False).mean() / atr_s
    dx    = (100 * (dip-dim).abs() / (dip+dim).replace(0,1)).fillna(0)
    df['adx'] = dx.ewm(com=ATR_PERIOD-1, adjust=False).mean()

    # RSI
    delta = df['close'].diff()
    gain  = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))

    # EMA 20 for trend bias confirmation
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

    return df

# ── Candle patterns ────────────────────────────────────────────────────────────

def is_bull_candle(df, i):
    """Bullish engulfing or pin bar."""
    if i < 1: return False
    bar  = df.iloc[i]
    prev = df.iloc[i-1]
    r    = bar['high'] - bar['low']
    if r == 0: return False

    body       = abs(bar['close'] - bar['open'])
    lower_wick = min(bar['open'], bar['close']) - bar['low']

    engulf = (prev['close'] < prev['open'] and
              bar['close'] > bar['open'] and
              bar['open'] < prev['close'] and
              bar['close'] > prev['open'])
    pin    = lower_wick >= r * 0.55 and body <= r * 0.35

    return engulf or pin

def is_bear_candle(df, i):
    """Bearish engulfing or pin bar."""
    if i < 1: return False
    bar  = df.iloc[i]
    prev = df.iloc[i-1]
    r    = bar['high'] - bar['low']
    if r == 0: return False

    body       = abs(bar['close'] - bar['open'])
    upper_wick = bar['high'] - max(bar['open'], bar['close'])

    engulf = (prev['close'] > prev['open'] and
              bar['close'] < bar['open'] and
              bar['open'] > prev['close'] and
              bar['close'] < prev['open'])
    pin    = upper_wick >= r * 0.55 and body <= r * 0.35

    return engulf or pin

# ── Signal detection ───────────────────────────────────────────────────────────

def get_signal(df, i):
    """
    VWAP pullback signal:
    Bull: price was above VWAP, pulled back TO VWAP zone, bullish candle + ADX ok
    Bear: price was below VWAP, rallied TO VWAP zone, bearish candle + ADX ok
    """
    if i < 20: return None

    bar  = df.iloc[i]
    prev = df.iloc[i-1]

    vwap     = bar['vwap']
    dist_pct = bar['vwap_dist_pct']   # how far price is from VWAP
    atr      = bar['atr']
    if atr <= 0 or vwap <= 0: return None

    # Must be near VWAP
    if abs(dist_pct) > VWAP_ZONE: return None

    # ADX gate — need some trend, not complete chaos
    if bar['adx'] < ADX_MIN: return None

    # Determine VWAP bias from recent price history
    # Look at where price was 5 bars ago relative to VWAP
    lookback = min(5, i)
    prev_above = sum(1 for j in range(i-lookback, i) if df.iloc[j]['close'] > df.iloc[j]['vwap'])
    prev_below = lookback - prev_above

    # Bull setup: price was predominantly above VWAP, pulled back, bullish candle
    if prev_above >= 3 and bar['rsi'] < 55 and is_bull_candle(df, i):
        # Extra filter: current bar low touched or pierced VWAP (genuine pullback)
        if bar['low'] <= vwap * 1.002:
            return 'buy'

    # Bear setup: price was predominantly below VWAP, rallied up, bearish candle
    if prev_below >= 3 and bar['rsi'] > 45 and is_bear_candle(df, i):
        # Extra filter: current bar high touched or pierced VWAP
        if bar['high'] >= vwap * 0.998:
            return 'sell'

    return None

# ── Trade simulation ───────────────────────────────────────────────────────────

def sim_trade(df, entry_i, entry, sl, tp, direction, atr_val):
    sl_cur  = sl
    be_done = False
    be_pts  = BE_ATR_MULT * atr_val
    be_level = entry + be_pts if direction == 'buy' else entry - be_pts

    for j in range(entry_i+1, min(entry_i+MAX_BARS, len(df))):
        bar = df.iloc[j]

        if direction == 'buy':
            if bar['low']  <= sl_cur: return sl_cur, 'sl',  j-entry_i
            if bar['high'] >= tp:     return tp,     'tp',  j-entry_i
            if not be_done and bar['high'] >= be_level:
                be_done = True
                sl_cur  = entry
            if be_done:
                new_sl = bar['high'] - atr_val
                if new_sl > sl_cur: sl_cur = new_sl
        else:
            if bar['high'] >= sl_cur: return sl_cur, 'sl',  j-entry_i
            if bar['low']  <= tp:     return tp,     'tp',  j-entry_i
            if not be_done and bar['low'] <= be_level:
                be_done = True
                sl_cur  = entry
            if be_done:
                new_sl = bar['low'] + atr_val
                if new_sl < sl_cur: sl_cur = new_sl

    last = df.iloc[min(entry_i+MAX_BARS-1, len(df)-1)]
    return last['close'], 'timeout', min(MAX_BARS-1, len(df)-entry_i-1)

# ── Backtest runner ────────────────────────────────────────────────────────────

def run(df, label):
    trades = []
    last_i = -3
    risk   = ACCOUNT * RISK_PCT

    for i in range(25, len(df)-1):
        bar = df.iloc[i]
        h   = bar.name.hour
        if h < SESSION_START or h >= SESSION_END: continue
        if i - last_i < 2: continue
        if trades and trades[-1].get('exit_i', 0) > i: continue

        direction = get_signal(df, i)
        if direction is None: continue

        entry   = bar['close']
        atr_val = bar['atr']
        vwap    = bar['vwap']
        if atr_val <= 0: continue

        sl_dist = SL_ATR_MULT * atr_val
        tp_dist = TP_ATR_MULT * atr_val
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
            'vwap':      round(vwap, 1),
            'exit':      round(ex_price, 1),
            'adx':       round(bar['adx'], 1),
            'rsi':       round(bar['rsi'], 1),
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
        print(f"  No trades generated for {label}")
        return {}

    df_t   = pd.DataFrame(trades)
    wins   = df_t[df_t['pnl_gbp'] >  5]
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
    print(f"  │  Monthly est.:   £{monthly:,.0f}/month  (at 0.5% risk)")
    print(f"  │  Monthly @ 1%:   £{monthly*2:,.0f}/month")
    print(f"  │  Monthly @ 2%:   £{monthly*4:,.0f}/month")
    print(f"  │  Avg win:        £{avg_win:,.2f}")
    print(f"  │  Avg loss:       £{avg_loss:,.2f}")
    print(f"  │  Profit factor:  {pf:.2f}")
    print(f"  │  Max DD @ 0.5%:  £{max_dd:,.2f}")
    print(f"  │  Max DD @ 1%:    £{max_dd*2:,.2f}")
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
    print("  VWAP PULLBACK STRATEGY BACKTESTER — DAX (GER40)")
    print("  Strategy: Trade pullbacks to daily VWAP with candle confirm")
    print("  ADX > 20 gate | SL: 1×ATR | TP: 2×ATR | BE at 0.8×ATR")
    print("  Session: 08:00-16:00 UTC (European)")
    print("="*62)

    results = []

    # H1 on 2 years of data
    print(f"\n{'='*62}\n  H1 Timeframe — 2 years\n{'='*62}")
    df_1h = fetch(SYMBOL, "1h", "730d")
    df_1h = add_vwap(df_1h)
    df_1h = add_indicators(df_1h)
    r = run(df_1h, "DAX H1 VWAP Pullback")
    if r: results.append(r)

    # M15 on 60 days (yfinance limit)
    print(f"\n{'='*62}\n  M15 Timeframe — 60 days\n{'='*62}")
    df_15 = fetch(SYMBOL, "15m", "60d")
    df_15 = add_vwap(df_15)
    df_15 = add_indicators(df_15)
    r = run(df_15, "DAX M15 VWAP Pullback (60d)")
    if r: results.append(r)

    # Comparison with H4 EMA result for context
    print(f"\n{'='*62}")
    print(f"  VWAP STRATEGY SUMMARY")
    print(f"{'='*62}")
    print(f"  {'Strategy':<35} {'Win%':>5}  {'T/mo':>5}  {'Monthly@1%':>11}  {'PF':>5}")
    print(f"  {'─'*60}")
    for r in results:
        print(f"  {r['label']:<35} {r['win_rate']:>4.1f}%  {r['trades_pm']:>5.1f}  "
              f"£{r['monthly']*2:>9,.0f}  {r['profit_factor']:>5.2f}")

    print(f"\n  For reference — DAX H4 EMA (previous test):")
    print(f"  {'DAX H4 EMA Cross':<35} {'67.4%':>5}  {'1.4':>5}  £{'529':>9}  {'2.61':>5}")
    print(f"\n  FTMO daily limit: £3,500 | Total drawdown limit: £7,000")
    print(f"  At 1% risk, safe daily worst case: 5 losses × £700 = £3,500 (at limit)")
    print(f"  Recommendation: use 0.75% risk for safety margin\n")
