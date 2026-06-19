"""
backtest.py — ScalpBot & Gold Strategy Backtester
Tests both strategies on historical data and compares results.

Run: python backtest.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

# ── Config ─────────────────────────────────────────────────────────────────────

SCALP_CFG = {
    "name":           "ScalpBot EURUSD M5",
    "symbol":         "EURUSD=X",
    "interval":       "5m",
    "h1_symbol":      "EURUSD=X",
    "ema_fast":       8,
    "ema_slow":       21,
    "rsi_period":     14,
    "rsi_ob":         70.0,
    "rsi_os":         30.0,
    "sl_pips":        10,
    "tp_pips":        15,
    "be_pips":        8,
    "trail_pips":     10,
    "max_hold_bars":  4,       # 4 x 5min = 20 mins
    "pip_size":       0.0001,
    "session_start":  7,       # UTC hour (10 server - 3 = 7 UTC)
    "session_end":    16,      # UTC hour (19 server - 3 = 16 UTC)
    "risk_pct":       0.25,
    "balance":        70000,
}

GOLD_CFG = {
    "name":           "Gold Strategy XAUUSD M15",
    "symbol":         "GC=F",  # gold futures — closest free proxy to XAUUSD
    "interval":       "15m",
    "h4_symbol":      "GC=F",
    "ema_fast":       10,
    "ema_slow":       20,
    "h4_adx_min":     25,
    "rsi_period":     14,
    "rsi_ob":         75.0,
    "rsi_os":         20.0,
    "sl_min_pts":     12,
    "sl_buffer":      3,
    "tp_min_pts":     14,
    "be_pts":         8,
    "trail_pts":      12,
    "round_step":     25,
    "entry_tol":      10,
    "min_touches":    2,
    "touch_tol":      3,
    "session_start":  7,
    "session_end":    17,
    "risk_pct":       0.25,
    "balance":        70000,
}

# ── Data ───────────────────────────────────────────────────────────────────────

def fetch(symbol, interval, period="60d"):
    print(f"  Fetching {symbol} {interval}...", end=" ")
    df = yf.download(symbol, interval=interval, period=period,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df = df.dropna()
    print(f"{len(df)} bars ({df.index[0].date()} → {df.index[-1].date()})")
    return df

# ── Indicators ─────────────────────────────────────────────────────────────────

def add_ema(df, fast, slow):
    df = df.copy()
    df['ema_fast'] = df['close'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow, adjust=False).mean()
    return df

def add_rsi(df, period=14):
    delta = df['close'].diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss.replace(0, 1e-9)))
    return df

def add_adx(df, period=14):
    hi, lo, cl = df['high'], df['low'], df['close']
    tr = pd.concat([hi-lo, (hi-cl.shift()).abs(), (lo-cl.shift()).abs()], axis=1).max(axis=1)
    dmp = ((hi-hi.shift()) > (lo.shift()-lo)).astype(float) * (hi-hi.shift()).clip(lower=0)
    dmm = ((lo.shift()-lo) > (hi-hi.shift())).astype(float) * (lo.shift()-lo).clip(lower=0)
    atr   = tr.ewm(com=period-1, adjust=False).mean()
    dip   = 100 * dmp.ewm(com=period-1, adjust=False).mean() / atr
    dim   = 100 * dmm.ewm(com=period-1, adjust=False).mean() / atr
    dx    = (100 * (dip-dim).abs() / (dip+dim).replace(0,1)).fillna(0)
    df['adx'] = dx.ewm(com=period-1, adjust=False).mean()
    return df

# ── Candle patterns ────────────────────────────────────────────────────────────

def bull_engulf(df, i):
    if i < 1: return False
    p, c = df.iloc[i-1], df.iloc[i]
    return p['close'] < p['open'] and c['close'] > c['open'] and c['open'] < p['close'] and c['close'] > p['open']

def bear_engulf(df, i):
    if i < 1: return False
    p, c = df.iloc[i-1], df.iloc[i]
    return p['close'] > p['open'] and c['close'] < c['open'] and c['open'] > p['close'] and c['close'] < p['open']

def bull_pin(df, i):
    r = df.iloc[i]['high'] - df.iloc[i]['low']
    if r == 0: return False
    body  = abs(df.iloc[i]['close'] - df.iloc[i]['open'])
    lower = min(df.iloc[i]['open'], df.iloc[i]['close']) - df.iloc[i]['low']
    return lower >= r * 0.6 and body <= r * 0.3

def bear_pin(df, i):
    r = df.iloc[i]['high'] - df.iloc[i]['low']
    if r == 0: return False
    body  = abs(df.iloc[i]['close'] - df.iloc[i]['open'])
    upper = df.iloc[i]['high'] - max(df.iloc[i]['open'], df.iloc[i]['close'])
    return upper >= r * 0.6 and body <= r * 0.3

# ── S/R helpers (gold) ────────────────────────────────────────────────────────

def find_sr(df, i, price, tol=10, step=25, lookback=45):
    best, best_d = None, tol + 1
    base = round(price / step) * step
    for m in range(-8, 9):
        lvl = base + step * m
        d   = abs(price - lvl)
        if d <= tol and d < best_d:
            best_d, best = d, lvl
    start = max(0, i - lookback)
    for j in range(start + 5, i - 4):
        for lvl in [df.iloc[j]['high'], df.iloc[j]['low']]:
            d = abs(price - lvl)
            if d <= tol and d < best_d:
                best_d, best = d, lvl
    return best

def level_touches(df, i, lvl, direction, lookback=100, tol=3):
    count, start = 0, max(0, i - lookback)
    for j in range(start, i):
        ref = df.iloc[j]['high'] if direction == 'bear' else df.iloc[j]['low']
        if abs(ref - lvl) <= tol:
            count += 1
    return count

def find_tp(price, direction, step=25, min_dist=14):
    base = round(price / step) * step
    best, best_d = None, 1e9
    for m in range(-20, 21):
        lvl = base + step * m
        if direction == 'bull' and lvl > price + min_dist:
            d = lvl - price
            if d < best_d:
                best_d, best = d, lvl - 2
        elif direction == 'bear' and lvl < price - min_dist:
            d = price - lvl
            if d < best_d:
                best_d, best = d, lvl + 2
    return best

# ── Trade simulation ───────────────────────────────────────────────────────────

def sim_trade(df, entry_i, entry, sl, tp, direction,
              be_pts, trail_pts, pip=1.0, max_hold_bars=None):
    sl_cur = sl
    be_done = False

    for j in range(entry_i + 1, min(entry_i + 300, len(df))):
        bar       = df.iloc[j]
        bars_held = j - entry_i

        # Profit/loss in points this bar
        if direction == 'buy':
            profit_pts = (bar['high'] - entry) / pip
            loss_pts   = (entry - bar['low'])  / pip
        else:
            profit_pts = (entry - bar['low'])  / pip
            loss_pts   = (bar['high'] - entry) / pip

        # MaxHold — close at bar close if no breakeven reached
        if max_hold_bars and bars_held >= max_hold_bars and not be_done:
            return bar['close'], 'maxhold', bars_held

        # SL hit
        if direction == 'buy'  and bar['low']  <= sl_cur: return sl_cur, 'sl', bars_held
        if direction == 'sell' and bar['high'] >= sl_cur: return sl_cur, 'sl', bars_held

        # TP hit
        if direction == 'buy'  and bar['high'] >= tp: return tp, 'tp', bars_held
        if direction == 'sell' and bar['low']  <= tp: return tp, 'tp', bars_held

        # Breakeven
        if not be_done and profit_pts >= be_pts:
            be_done = True
            sl_cur = entry if direction == 'buy' else entry

        # Trail
        if be_done:
            if direction == 'buy':
                new_sl = bar['high'] - trail_pts * pip
                if new_sl > sl_cur: sl_cur = new_sl
            else:
                new_sl = bar['low'] + trail_pts * pip
                if new_sl < sl_cur: sl_cur = new_sl

    last = df.iloc[min(entry_i + 299, len(df) - 1)]
    return last['close'], 'end', min(299, len(df) - entry_i - 1)

# ── ScalpBot backtest ──────────────────────────────────────────────────────────

def run_scalp(cfg, use_h1=False):
    label = cfg['name'] + (" + H1 Bias" if use_h1 else " (No H1 Bias)")
    print(f"\n{'='*62}\n  {label}\n{'='*62}")

    df = fetch(cfg['symbol'], cfg['interval'])
    df = add_ema(df, cfg['ema_fast'], cfg['ema_slow'])
    df = add_rsi(df, cfg['rsi_period'])

    h1 = None
    if use_h1:
        h1 = fetch(cfg['h1_symbol'], '1h')
        h1 = add_ema(h1, cfg['ema_fast'], cfg['ema_slow'])

    pip    = cfg['pip_size']
    sl_d   = cfg['sl_pips'] * pip
    tp_d   = cfg['tp_pips'] * pip
    trades = []
    last_i = -5
    mom_fired = False

    for i in range(50, len(df) - 1):
        bar = df.iloc[i]

        # Session (UTC)
        h = bar.name.hour
        if h < cfg['session_start'] or h >= cfg['session_end']: continue
        if i - last_i < 1: continue

        # Skip if already in trade
        if trades and trades[-1]['exit_i'] > i: continue

        prev = df.iloc[i - 1]
        bull_x = bar['ema_fast'] > bar['ema_slow'] and prev['ema_fast'] <= prev['ema_slow']
        bear_x = bar['ema_fast'] < bar['ema_slow'] and prev['ema_fast'] >= prev['ema_slow']
        bull_m = bar['ema_fast'] > bar['ema_slow'] and 50 < bar['rsi'] < cfg['rsi_ob']
        bear_m = bar['ema_fast'] < bar['ema_slow'] and cfg['rsi_os'] < bar['rsi'] < 50

        action = sig = None
        if   bull_x and bar['rsi'] < cfg['rsi_ob']:  action='buy';  sig='cross';    mom_fired=False
        elif bear_x and bar['rsi'] > cfg['rsi_os']:  action='sell'; sig='cross';    mom_fired=False
        elif bull_m and not mom_fired:                action='buy';  sig='momentum'; mom_fired=True
        elif bear_m and not mom_fired:                action='sell'; sig='momentum'; mom_fired=True
        if action is None: continue

        # H1 bias filter
        if use_h1 and h1 is not None:
            idx = h1.index.searchsorted(bar.name) - 1
            if 0 <= idx < len(h1):
                h1b = 'bull' if h1.iloc[idx]['ema_fast'] > h1.iloc[idx]['ema_slow'] else 'bear'
                if h1b == 'bull' and action == 'sell': continue
                if h1b == 'bear' and action == 'buy':  continue

        entry = bar['close']
        sl = entry - sl_d if action == 'buy' else entry + sl_d
        tp = entry + tp_d if action == 'buy' else entry - tp_d

        ex_price, reason, bars = sim_trade(
            df, i, entry, sl, tp, action,
            cfg['be_pips'], cfg['trail_pips'],
            pip=pip, max_hold_bars=cfg['max_hold_bars']
        )

        pnl_pips = (ex_price - entry)/pip if action=='buy' else (entry - ex_price)/pip
        risk_amt = cfg['balance'] * cfg['risk_pct'] / 100
        lots     = risk_amt / (cfg['sl_pips'] * 10)
        pnl_gbp  = pnl_pips * lots * 10

        trades.append({
            'date': bar.name, 'action': action, 'signal': sig,
            'entry': entry, 'exit': ex_price, 'reason': reason,
            'pnl_pips': round(pnl_pips, 1), 'pnl_gbp': round(pnl_gbp, 2),
            'bars': bars, 'exit_i': i + bars
        })
        last_i = i

    return print_results(trades, label)

# ── Gold backtest ──────────────────────────────────────────────────────────────

def run_gold(cfg):
    label = cfg['name']
    print(f"\n{'='*62}\n  {label}\n{'='*62}")

    df = fetch(cfg['symbol'], cfg['interval'])
    df = add_ema(df, cfg['ema_fast'], cfg['ema_slow'])
    df = add_rsi(df, cfg['rsi_period'])

    h4 = fetch(cfg['h4_symbol'], '1h')
    h4 = add_ema(h4, cfg['ema_fast'], cfg['ema_slow'])
    h4 = add_adx(h4)

    trades = []
    last_i = -3

    for i in range(100, len(df) - 1):
        bar = df.iloc[i]

        h = bar.name.hour
        if h < cfg['session_start'] or h >= cfg['session_end']: continue
        if i - last_i < 3: continue
        if trades and trades[-1]['exit_i'] > i: continue

        # H4 bias + ADX gate
        h4i = h4.index.searchsorted(bar.name) - 1
        if not (0 <= h4i < len(h4)): continue
        h4b = h4.iloc[h4i]
        bias = 'bull' if h4b['ema_fast'] > h4b['ema_slow'] else 'bear'
        if h4b['adx'] < cfg['h4_adx_min']: continue

        # M15 trend must match H4 bias
        m15 = 'bull' if bar['ema_fast'] > bar['ema_slow'] else 'bear'
        if m15 != bias: continue

        # RSI filter
        rsi = bar['rsi']
        if m15 == 'bull' and rsi > cfg['rsi_ob']: continue
        if m15 == 'bear' and rsi < cfg['rsi_os']: continue

        # Candle confirmation
        if m15 == 'bull':
            if not bull_engulf(df, i) and not bull_pin(df, i): continue
        else:
            if not bear_engulf(df, i) and not bear_pin(df, i): continue

        entry = bar['close']

        # S/R level
        lvl = find_sr(df, i, entry, tol=cfg['entry_tol'], step=cfg['round_step'])
        if lvl is None: continue
        if level_touches(df, i, lvl, m15, tol=cfg['touch_tol']) < cfg['min_touches']: continue

        # SL
        struct_sl = (lvl - cfg['sl_buffer']) if m15=='bull' else (lvl + cfg['sl_buffer'])
        sl_dist   = max(abs(entry - struct_sl), cfg['sl_min_pts'])
        sl        = entry - sl_dist if m15=='bull' else entry + sl_dist

        # TP
        tp = find_tp(entry, m15, step=cfg['round_step'], min_dist=sl_dist + 2)
        if tp is None: continue
        if abs(tp - entry) < cfg['tp_min_pts']: continue

        ex_price, reason, bars = sim_trade(
            df, i, entry, sl, tp, m15,
            cfg['be_pts'], cfg['trail_pts'],
            pip=1.0, max_hold_bars=None
        )

        pnl_pts  = (ex_price - entry) if m15=='bull' else (entry - ex_price)
        risk_amt = cfg['balance'] * cfg['risk_pct'] / 100
        lots     = risk_amt / (sl_dist * 100)
        pnl_gbp  = pnl_pts * lots * 100

        trades.append({
            'date': bar.name, 'action': m15,
            'entry': round(entry,2), 'exit': round(ex_price,2), 'reason': reason,
            'sl_dist': round(sl_dist,1), 'tp_pts': round(abs(tp-entry),1),
            'h4_adx': round(h4b['adx'],1), 'rsi': round(rsi,1),
            'pnl_pts': round(pnl_pts,1), 'pnl_gbp': round(pnl_gbp,2),
            'bars': bars, 'exit_i': i + bars
        })
        last_i = i

    return print_results(trades, label)

# ── Results printer ────────────────────────────────────────────────────────────

def print_results(trades, label):
    if not trades:
        print("  No trades generated.")
        return {}

    df_t = pd.DataFrame(trades)
    wins     = df_t[df_t['pnl_gbp'] > 1]
    losses   = df_t[df_t['pnl_gbp'] <= 0]
    scratch  = df_t[(df_t['pnl_gbp'] > 0) & (df_t['pnl_gbp'] <= 1)]

    n          = len(df_t)
    win_rate   = len(wins) / n * 100
    total_pnl  = df_t['pnl_gbp'].sum()
    avg_win    = wins['pnl_gbp'].mean()   if len(wins)   > 0 else 0
    avg_loss   = losses['pnl_gbp'].mean() if len(losses) > 0 else 0
    gp         = wins['pnl_gbp'].sum()   if len(wins)   > 0 else 0
    gl         = abs(losses['pnl_gbp'].sum()) if len(losses) > 0 else 1
    pf         = gp / gl

    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    df_t['dd']   = df_t['cum'] - df_t['peak']
    max_dd       = df_t['dd'].min()

    days    = max((df_t['date'].iloc[-1] - df_t['date'].iloc[0]).days, 1)
    monthly = total_pnl / days * 30

    # Exit breakdown
    by_reason = df_t.groupby('reason').agg(
        count=('pnl_gbp','count'),
        avg_pnl=('pnl_gbp','mean'),
        total=('pnl_gbp','sum')
    ).round(2)

    print(f"\n  ┌─ Results: {label}")
    print(f"  │  Total trades:    {n}")
    print(f"  │  Win rate:        {win_rate:.1f}%  ({len(wins)}W / {len(losses)}L / {len(scratch)} scratch)")
    print(f"  │  Total P&L:       £{total_pnl:,.2f}")
    print(f"  │  Monthly est.:    £{monthly:,.0f}/month")
    print(f"  │  Avg win:         £{avg_win:,.2f}")
    print(f"  │  Avg loss:        £{avg_loss:,.2f}")
    print(f"  │  Profit factor:   {pf:.2f}  (>1.0 = profitable)")
    print(f"  │  Max drawdown:    £{max_dd:,.2f}")
    print(f"  │")
    print(f"  │  Exit breakdown:")
    for reason, row in by_reason.iterrows():
        print(f"  │    {reason:<10} {int(row['count']):>3} trades | avg £{row['avg_pnl']:>8.2f} | total £{row['total']:>9.2f}")
    print(f"  └{'─'*55}")

    return {
        'name': label, 'trades': n, 'win_rate': win_rate,
        'total_pnl': total_pnl, 'monthly': monthly,
        'profit_factor': pf, 'max_dd': max_dd
    }

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*62)
    print("  STRATEGY BACKTESTER  |  £70,000 account  |  0.25% risk")
    print("  Data: ~60 days intraday via yfinance")
    print("  Note: no spread/slippage modelled — live results will differ")
    print("="*62)

    results = []

    # ScalpBot — without H1 bias (how it ran yesterday)
    results.append(run_scalp(SCALP_CFG, use_h1=False))

    # ScalpBot — with H1 bias (how it ran this morning)
    results.append(run_scalp(SCALP_CFG, use_h1=True))

    # Gold strategy
    results.append(run_gold(GOLD_CFG))

    # Comparison table
    print(f"\n{'='*62}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*62}")
    print(f"  {'Strategy':<38} {'Win%':>5}  {'Monthly':>9}  {'PF':>5}")
    print(f"  {'─'*58}")
    for r in results:
        if r:
            print(f"  {r['name']:<38} {r['win_rate']:>4.1f}%  £{r['monthly']:>7,.0f}  {r['profit_factor']:>5.2f}")
    print(f"\n  PF > 1.0 = profitable  |  PF > 1.5 = strong edge")
    print(f"  Spread cost not included — subtract ~5-8% from win rate for live\n")
