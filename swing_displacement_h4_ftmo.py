"""
swing_displacement_h4_ftmo.py

Objective, backtestable version of the "supply and demand" swing style:
instead of freehand-drawn zones (subjective, hindsight-prone, and close
in spirit to the single-candle pattern matching that blew up the
original bot), this formalizes it as three explicit, mechanical rules.
Holds trades for days (up to MAX_HOLD_BARS H4 bars, ~20 trading days),
tested across the full ~26-instrument universe built up tonight
(equity indices, FX majors, FX crosses, commodities) for genuine
diversification rather than one correlated basket.

MECHANISM:
  1. IMPULSE: an H4 candle whose range >= IMPULSE_ATR_MULT x ATR(20),
     breaking the prior BREAKOUT_LOOKBACK-bar high (bullish) or low
     (bearish). This is the objective stand-in for "strong
     institutional displacement" -- a real, sized move breaking a
     real range, not a subjectively "big-looking" candle.
  2. ZONE: the impulse candle's own high-low range. No freehand
     drawing -- the zone is just that one candle's real extent.
  3. RETRACEMENT + REJECTION: watch up to RETRACE_WINDOW_BARS forward
     bars for the first one whose low (bullish) / high (bearish)
     trades back into the zone. If THAT bar's close confirms
     rejection (closes back in the impulse direction), enter at the
     next bar's open. Single-shot rule -- first touch only, no
     re-scanning -- to avoid smuggling in hindsight/curve-fitting.
  4. Stop = the far side of the zone. Target = stop distance x RR.
     Time-stop at MAX_HOLD_BARS.

Works entirely on H4 bars (not M1) -- a big daily/4h close is far more
reliable than one M1 candle's exact wick, and it sidesteps the memory
pressure that OOM-killed the news-breakout script (H4 bar counts are
~1/240th of M1). No cluster risk-sizing applied here (unlike
news-breakout): entries are triggered by each instrument's own
independent impulse/retracement pattern rather than a shared
same-minute calendar event, so correlated timing is a much smaller
concern -- still real (correlated markets can trend together), just
not the "same literal timestamp fired 11x" issue that caused the
trillion-percent blowup.

Same real spread costs (1.5x stress multiplier), confirmed UTC+3
broker offset correction, and walk-forward discipline as everything
else tonight.

Run in Codespace: python -u swing_displacement_h4_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

IMPULSE_ATR_MULT = 1.5
ATR_PERIOD = 20
BREAKOUT_LOOKBACK = 20
RETRACE_WINDOW_BARS = 30      # ~5 days on H4
RR = 2.0
COST_MULT = 1.5
MAX_HOLD_BARS = 120           # ~20 trading days on H4 (6 bars/day)
MIN_STOP_DIST_PCT = 0.0005
WALK_FORWARD_MONTHS = 6
RISK_PCT = 0.30
START_BAL = 70000.0

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'GOLD':  'XAUUSD_M1_ftmo.csv',
    'NATGAS':'NATGAS_cash_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'AUDNZD':'AUDNZD_M1_ftmo.csv',
    'AUDCAD':'AUDCAD_M1_ftmo.csv',
    'AUDCHF':'AUDCHF_M1_ftmo.csv',
    'USDCHF':'USDCHF_M1_ftmo.csv',
    'USDCAD':'USDCAD_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'WTIOIL':  'WTIOIL_M1_ftmo.csv',
    'BRENTOIL':'BRENTOIL_M1_ftmo.csv',
    'SILVER':  'SILVER_M1_ftmo.csv',
    'COPPER':  'COPPER_M1_ftmo.csv',
    'PLATINUM':'PLATINUM_M1_ftmo.csv',
    'PALLADIUM':'PALLADIUM_M1_ftmo.csv',
    'USDINDEX':'USDINDEX_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
    'NATGAS':0.008, 'UK100':1.8,
    'AUDNZD':0.0004, 'AUDCAD':0.0004, 'AUDCHF':0.0004, 'USDCHF':0.00015, 'USDCAD':0.00015,
    'FRA40':1.5, 'JP225':8.0, 'AUS200':2.0, 'EU50':1.2, 'US2000':0.4, 'HK50':10.0,
    'WTIOIL':0.04, 'BRENTOIL':0.04, 'SILVER':0.025, 'COPPER':0.008,
    'PLATINUM':0.5, 'PALLADIUM':2.0, 'USDINDEX':0.02,
}


def load_h4(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h4 = df.resample('4h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    del df   # M1 no longer needed -- H4 is ~1/240th the size, all we work with from here
    h4 = h4[h4['open'] > 0]
    prev_close = h4['close'].shift(1)
    tr = pd.concat([h4['high']-h4['low'], (h4['high']-prev_close).abs(), (h4['low']-prev_close).abs()], axis=1).max(axis=1)
    h4['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    h4['range_high'] = h4['high'].rolling(BREAKOUT_LOOKBACK).max().shift(1)
    h4['range_low'] = h4['low'].rolling(BREAKOUT_LOOKBACK).min().shift(1)
    return h4.dropna()


def find_trades(symbol, h4):
    idx = h4.index
    n = len(h4)
    trades = []
    in_position_until = -1
    i = 0
    while i < n - 1:
        if i <= in_position_until:
            i += 1
            continue
        row = h4.iloc[i]
        o, h, l, c, atr = row['open'], row['high'], row['low'], row['close'], row['atr']
        if pd.isna(atr) or atr <= 0:
            i += 1; continue

        is_impulse = (h - l) >= IMPULSE_ATR_MULT * atr
        direction = 0
        if is_impulse and c > o and h > row['range_high']:
            direction = 1
        elif is_impulse and c < o and l < row['range_low']:
            direction = -1
        if direction == 0:
            i += 1; continue

        zone_high, zone_low = h, l
        watch_end = min(i + 1 + RETRACE_WINDOW_BARS, n)
        entry_idx = None
        for j in range(i + 1, watch_end):
            rb = h4.iloc[j]
            touched = (rb['low'] <= zone_high) if direction == 1 else (rb['high'] >= zone_low)
            if touched:
                rejected = (rb['close'] > rb['open']) if direction == 1 else (rb['close'] < rb['open'])
                if rejected:
                    entry_idx = j + 1
                break   # first touch only -- single-shot rule, no re-scanning

        if entry_idx is None or entry_idx >= n:
            i += 1; continue

        entry_price = float(h4['open'].iloc[entry_idx])
        stop_price = zone_low if direction == 1 else zone_high
        stop_dist = abs(entry_price - stop_price)
        if stop_dist <= 0 or stop_dist < entry_price * MIN_STOP_DIST_PCT:
            i += 1; continue
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        window_end = min(entry_idx + 1 + MAX_HOLD_BARS, n)
        future = h4.iloc[entry_idx + 1: window_end]
        r_gross = None
        exit_idx = window_end - 1
        if len(future) > 0:
            fh = future['high'].values; fl = future['low'].values; fc = future['close'].values
            for k in range(len(future)):
                if direction == 1:
                    if fh[k] >= tp_price: r_gross = RR; exit_idx = entry_idx + 1 + k; break
                    if fl[k] <= stop_price: r_gross = -1.0; exit_idx = entry_idx + 1 + k; break
                else:
                    if fl[k] <= tp_price: r_gross = RR; exit_idx = entry_idx + 1 + k; break
                    if fh[k] >= stop_price: r_gross = -1.0; exit_idx = entry_idx + 1 + k; break
            if r_gross is None:
                final_close = fc[-1]
                r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                           else (entry_price - final_close) / stop_dist)
                r_gross = max(-2.0, min(RR + 0.5, r_gross))
        else:
            r_gross = -1.0

        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        trades.append({'symbol': symbol, 'entry_time': idx[entry_idx], 'r_net': r_gross - cost_r})
        in_position_until = exit_idx
        i = exit_idx + 1

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


all_trades = []
loaded = []
for symbol in FILES:
    h4 = load_h4(symbol)
    if h4 is None:
        continue
    loaded.append(symbol)
    trades = find_trades(symbol, h4)
    print(f'  {symbol}: {len(h4)} H4 bars, {len(trades)} trades')
    all_trades.extend(trades)
    del h4
    gc.collect()

print(f'\nLoaded {len(loaded)} instruments: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print_row('OVERALL', n, wr, pf, tot)

if len(df) > 0:
    print(f'\n{"#"*90}')
    print(f'  WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    print(f'{"#"*90}')
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        window_rv = df[df['period'].isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    print(f'\n  Per-instrument:')
    for symbol in loaded:
        rv = df[df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {symbol}', n2, wr2, pf2, tot2)

    print(f'\n{"#"*90}')
    print(f'  MONTHLY P&L (each month fresh from £{START_BAL:,.0f}, {RISK_PCT}% risk per trade, additive)')
    print(f'{"#"*90}')
    rpt = RISK_PCT / 100.0
    rows = []
    for period, g in df.groupby('period'):
        pnl = START_BAL * rpt * g['r_net'].sum()
        rows.append({'month': str(period), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl / START_BAL * 100})
    monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
    print(f'  Months with activity: {len(monthly)}')
    print(f'  Best month:   {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  £{monthly["pnl_gbp"].max():>+9,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
    print(f'  Worst month:  {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  £{monthly["pnl_gbp"].min():>+9,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
    print(f'  Median month: £{monthly["pnl_gbp"].median():>+9,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
    print(f'  Mean month:   £{monthly["pnl_gbp"].mean():>+9,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
    pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
    print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

print('\nDone.')
