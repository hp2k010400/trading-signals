"""
scalping_m5_ftmo.py

High-frequency scalping, as requested. Built on M5 bars (not M1) --
deliberately not going all the way down to raw M1 wicks, since
single-candle-wick dependency on the fastest timeframe is exactly what
made the ORIGINAL bot's backtest look great on OANDA and then blow up
on real broker data at the start of this whole session. M5 is fast
enough to be genuine scalping (many signals/day per instrument) while
still being built on a bar with enough real trading activity in it to
be less broker-feed-fragile.

MECHANISM (micro-range breakout, robust multi-bar construction):
  1. On M5 bars, a "breakout" bar closes beyond the high/low of the
     prior RANGE_LOOKBACK bars (a real short-term range, not a single
     candle's wick), during London/NY power hours only (real
     liquidity, not just "looks vvolatile").
  2. Entry at the next bar's open. Stop = ATR_STOP_MULT x ATR(14) on
     M5. Target = RR x stop (kept realistic/tight -- scalping doesn't
     get to assume a big reward-to-risk).
  3. Time-stop at MAX_HOLD_BARS (~1 hour) if neither hit.

HONEST EXPECTATION GOING IN: tight stops on a fast timeframe mean real
spread costs are a much larger fraction of each trade's risk than on
slower strategies tonight -- this is exactly why professional-grade
scalping edges are rare and usually require genuine execution/latency
advantages retail trading doesn't have. Real 1.5x cost-stress
multiplier applied, same as everything else -- if this fails, that's
the actual, honest result, not a reason to loosen the cost assumption.

Same walk-forward discipline and blind selection/holdout split as
everything else tonight before trusting any full-history number.

Run in Codespace: python -u scalping_m5_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
RANGE_LOOKBACK = 12       # 1 hour of M5 bars
ATR_PERIOD = 14
ATR_STOP_MULT = 1.0
RR = 1.2
MAX_HOLD_BARS = 12        # ~1 hour
COST_MULT = 1.5
MIN_STOP_DIST_PCT = 0.0003
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


def is_power_hour(hour_utc):
    return (8 <= hour_utc <= 10) or (13 <= hour_utc <= 16)


def load_m5(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    m5 = df.resample('5min').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    del df
    m5 = m5[m5['open'] > 0]
    prev_close = m5['close'].shift(1)
    tr = pd.concat([m5['high']-m5['low'], (m5['high']-prev_close).abs(), (m5['low']-prev_close).abs()], axis=1).max(axis=1)
    m5['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    m5['range_high'] = m5['high'].rolling(RANGE_LOOKBACK).max().shift(1)
    m5['range_low'] = m5['low'].rolling(RANGE_LOOKBACK).min().shift(1)
    return m5.dropna()


def find_trades(symbol, m5):
    idx = m5.index
    n = len(m5)
    trades = []
    in_position_until = -1

    opens = m5['open'].values; highs = m5['high'].values; lows = m5['low'].values; closes = m5['close'].values
    atr = m5['atr'].values; rh = m5['range_high'].values; rl = m5['range_low'].values

    for i in range(n - 1):
        if i <= in_position_until:
            continue
        bar_time = idx[i]
        if bar_time.dayofweek >= 5 or not is_power_hour(bar_time.hour):
            continue
        a = atr[i]
        if pd.isna(a) or a <= 0:
            continue

        direction = 0
        if closes[i] > rh[i]:
            direction = 1
        elif closes[i] < rl[i]:
            direction = -1
        if direction == 0:
            continue

        entry_idx = i + 1
        entry_price = float(opens[entry_idx])
        stop_dist = ATR_STOP_MULT * a
        if stop_dist < entry_price * MIN_STOP_DIST_PCT:
            continue
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        window_end = min(entry_idx + 1 + MAX_HOLD_BARS, n)
        r_gross = None
        exit_idx = window_end - 1
        for k in range(entry_idx + 1, window_end):
            if direction == 1:
                if highs[k] >= tp_price: r_gross = RR; exit_idx = k; break
                if lows[k] <= stop_price: r_gross = -1.0; exit_idx = k; break
            else:
                if lows[k] <= tp_price: r_gross = RR; exit_idx = k; break
                if highs[k] >= stop_price: r_gross = -1.0; exit_idx = k; break
        if r_gross is None:
            final_close = closes[min(window_end - 1, n - 1)]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)
            r_gross = max(-2.0, min(RR + 0.5, r_gross))

        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        trades.append({'symbol': symbol, 'entry_time': idx[entry_idx], 'r_net': r_gross - cost_r})
        in_position_until = exit_idx

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


def report(label, sub_df, instruments):
    print(f'\n{"="*90}')
    print(f'  {label}  (N={len(sub_df)})')
    print(f'{"="*90}')
    if len(sub_df) == 0:
        print('  No trades in this period.')
        return
    if len(sub_df) < 80:
        print('  WARNING: fewer than 80 trades -- treat every number below as unreliable.')

    n, wr, pf, tot = compute_stats(sub_df['r_net'].values)
    print_row('OVERALL', n, wr, pf, tot)

    print(f'\n  WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    periods = sub_df['entry_time'].dt.to_period('M')
    all_periods = sorted(periods.unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        window_rv = sub_df[periods.isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    print(f'\n  Per-instrument:')
    for symbol in instruments:
        rv = sub_df[sub_df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {symbol}', n2, wr2, pf2, tot2)

    print(f'\n  MONTHLY P&L (each month fresh from £{START_BAL:,.0f}, {RISK_PCT}% risk per trade, additive)')
    rpt = RISK_PCT / 100.0
    rows = []
    for period, g in sub_df.groupby(periods):
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


all_trades = []
loaded = []
for symbol in FILES:
    m5 = load_m5(symbol)
    if m5 is None:
        continue
    loaded.append(symbol)
    trades = find_trades(symbol, m5)
    print(f'  {symbol}: {len(m5)} M5 bars, {len(trades)} trades')
    all_trades.extend(trades)
    del m5
    gc.collect()

print(f'\nLoaded {len(loaded)} instruments: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')

if len(df) > 0:
    report('FULL HISTORY', df, loaded)

    HOLDOUT_START = pd.Timestamp('2025-01-01', tz='UTC')
    MIN_SELECTION_TRADES = 100
    SELECTION_PF_THRESHOLD = 1.0

    sel_df = df[df['entry_time'] < HOLDOUT_START]
    selected = []
    print(f'\n{"="*90}')
    print(f'  INSTRUMENT SELECTION on data before {HOLDOUT_START.date()} '
          f'(PF >= {SELECTION_PF_THRESHOLD}, N >= {MIN_SELECTION_TRADES})')
    print(f'{"="*90}')
    for symbol in loaded:
        rv = sel_df[sel_df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        keep = n2 >= MIN_SELECTION_TRADES and pf2 >= SELECTION_PF_THRESHOLD
        if keep:
            selected.append(symbol)
        print_row(f'  {symbol}{" [SELECTED]" if keep else ""}', n2, wr2, pf2, tot2)
    print(f'\n  Selected {len(selected)} instruments: {selected}')

    holdout_df = df[(df['entry_time'] >= HOLDOUT_START) & (df['symbol'].isin(selected))].reset_index(drop=True)
    report(f'BLIND HOLDOUT ({HOLDOUT_START.date()} onward, selected instruments only, '
           f'never seen during selection)', holdout_df, selected)

print('\nDone.')
