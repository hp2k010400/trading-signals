"""
intraday_meanreversion_ftmo.py

High frequency + high win rate, as requested -- a genuinely different
mechanism from everything tested tonight (all of which was breakout/
momentum/trend). This is classic intraday mean-reversion: fade extreme
short-term moves back toward a baseline. On H1 bars across 27
instruments this should fire many times a day, and mean-reversion
setups typically DO show a high win rate -- most extreme short-term
moves partially revert.

Honest caveat before a single result comes in: high win rate is not
the same as profitable. Reversal strategies characteristically have
small average wins and occasional large losses when the move doesn't
revert (keeps trending instead) -- the real edge lives or dies on
whether win-rate x avg-win still beats loss-rate x avg-loss after real
costs, not on the win percentage alone.

MECHANISM (robust, multi-bar construction -- not single-candle wicks,
same discipline as everything that's actually shown signal tonight):
  1. Bollinger Bands (20-period, 2 std) AND RSI(14) on H1 bars.
  2. Short when price closes above the upper band AND RSI > RSI_OB
     (overbought) -- both conditions required, not just one, to avoid
     firing on a strong band-riding trend that RSI alone wouldn't
     catch.
  3. Long when price closes below the lower band AND RSI < RSI_OS.
  4. Entry at the next bar's open. Stop = ATR_STOP_MULT x ATR(14)
     beyond entry. Target = the 20-period moving average (the
     reversion target, not an arbitrary R-multiple) capped at
     MAX_RR x stop distance so a target that's too far away doesn't
     produce an unrealistic reward profile.
  5. Time-stop at MAX_HOLD_HOURS if neither hit.

Real spread costs (1.5x stress multiplier), confirmed UTC+3 offset,
walk-forward discipline, and the same genuine blind selection/holdout
split before trusting any full-history number, per tonight's rule.

Run in Codespace: python -u intraday_meanreversion_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_OB = 65
RSI_OS = 35
ATR_PERIOD = 14
ATR_STOP_MULT = 1.0
MAX_RR = 2.0
MAX_HOLD_HOURS = 24
COST_MULT = 1.5
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


def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def load_h1(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    del df
    h1 = h1[h1['open'] > 0]

    close = h1['close']; high = h1['high']; low = h1['low']
    bb_mid = close.rolling(BB_PERIOD).mean()
    bb_std = close.rolling(BB_PERIOD).std()
    h1['bb_mid'] = bb_mid
    h1['bb_upper'] = bb_mid + BB_STD * bb_std
    h1['bb_lower'] = bb_mid - BB_STD * bb_std
    h1['rsi'] = compute_rsi(close, RSI_PERIOD)
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)   # no lookahead
    # shift the reversion-target/signal columns that use the CURRENT bar's
    # close so the signal check uses only fully-closed-bar information
    h1['bb_mid_sig'] = bb_mid.shift(1)
    h1['bb_upper_sig'] = h1['bb_upper'].shift(1)
    h1['bb_lower_sig'] = h1['bb_lower'].shift(1)
    h1['rsi_sig'] = h1['rsi'].shift(1)
    return h1.dropna()


def find_trades(symbol, h1):
    idx = h1.index
    n = len(h1)
    trades = []
    in_position_until = -1

    closes = h1['close'].values
    upper = h1['bb_upper_sig'].values
    lower = h1['bb_lower_sig'].values
    mid = h1['bb_mid_sig'].values
    rsi = h1['rsi_sig'].values
    atr = h1['atr'].values
    opens = h1['open'].values
    highs = h1['high'].values
    lows = h1['low'].values

    for i in range(n - 1):
        if i <= in_position_until:
            continue
        a = atr[i]
        if pd.isna(a) or a <= 0:
            continue

        direction = 0
        if closes[i] > upper[i] and rsi[i] > RSI_OB:
            direction = -1
        elif closes[i] < lower[i] and rsi[i] < RSI_OS:
            direction = 1
        if direction == 0:
            continue

        entry_idx = i + 1
        entry_price = float(opens[entry_idx])
        stop_dist = ATR_STOP_MULT * a
        if stop_dist < entry_price * MIN_STOP_DIST_PCT:
            continue
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist

        # target = reversion to the mid band, capped at MAX_RR x stop distance
        target_dist = abs(mid[i] - entry_price)
        target_dist = min(target_dist, MAX_RR * stop_dist)
        if target_dist <= 0:
            continue
        tp_price = entry_price + target_dist if direction == 1 else entry_price - target_dist
        rr_actual = target_dist / stop_dist

        window_end = min(entry_idx + 1 + MAX_HOLD_HOURS, n)
        r_gross = None
        exit_idx = window_end - 1
        for k in range(entry_idx + 1, window_end):
            if direction == 1:
                if highs[k] >= tp_price: r_gross = rr_actual; exit_idx = k; break
                if lows[k] <= stop_price: r_gross = -1.0; exit_idx = k; break
            else:
                if lows[k] <= tp_price: r_gross = rr_actual; exit_idx = k; break
                if highs[k] >= stop_price: r_gross = -1.0; exit_idx = k; break
        if r_gross is None:
            final_close = closes[min(window_end - 1, n - 1)]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)
            r_gross = max(-2.0, min(rr_actual + 0.5, r_gross))

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
    h1 = load_h1(symbol)
    if h1 is None:
        continue
    loaded.append(symbol)
    trades = find_trades(symbol, h1)
    print(f'  {symbol}: {len(h1)} H1 bars, {len(trades)} trades')
    all_trades.extend(trades)
    del h1
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
