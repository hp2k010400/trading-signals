"""
time_series_momentum_ftmo.py

A genuinely famous, real, decades-documented quant strategy -- not
something improvised tonight. Time-Series Momentum (Moskowitz, Ooi &
Pedersen, "Time Series Momentum", Journal of Financial Economics 2012)
is one of the most replicated results in quant finance: if an
instrument's trailing 12-month return is positive, go long; if
negative, go short. Works (with real, published out-of-sample
evidence) across equity indices, commodities, bonds, and FX -- exactly
our asset mix. Monthly rebalancing across all 27 instruments gives
~27 signals once a month, which amortizes to roughly a trade a day
across the universe.

MECHANISM (faithful to the original paper's methodology, not a
simplification):
  1. On each monthly rebalance date, for every instrument: direction
     = sign of the trailing LOOKBACK_DAYS (~12 months) return.
  2. Position size is VOLATILITY-SCALED (inverse-vol weighting, exactly
     as in the original paper) -- normalize the realized monthly
     return by the instrument's own recent daily volatility scaled to
     the holding period, so a quiet FX pair and a volatile index
     contribute comparably-sized R units rather than the raw return
     dominating for whichever happens to be more volatile.
  3. Hold until the next rebalance date (~1 month later), then
     re-evaluate.

Real spread costs (1.5x stress multiplier), confirmed UTC+3 broker
offset, walk-forward discipline, and (given every other promising-
looking result tonight died under this test) the same genuine blind
selection/holdout split before any of this gets trusted.

Run in Codespace: python -u time_series_momentum_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
LOOKBACK_DAYS = 252     # ~12 months of trading days, the paper's headline horizon
VOL_LOOKBACK_DAYS = 20
COST_MULT = 1.5
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


def load_daily(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','close':'last'}).dropna()
    del df
    daily = daily[daily['open'] > 0]
    daily['ret1'] = np.log(daily['close'] / daily['close'].shift(1))
    # LOOKAHEAD FIX (audit, 2026-08-12): trail_ret/vol20 must reflect only
    # information available BEFORE the day they're acted on. find_trades()
    # enters at THIS row's open -- using this row's own close (via
    # .shift(LOOKBACK_DAYS) with no further shift) to size that same day's
    # entry is using data that doesn't exist yet at the open. Shifted by 1
    # extra day so the signal used for day i's open reflects only data
    # through day i-1's close.
    daily['trail_ret'] = np.log(daily['close'] / daily['close'].shift(LOOKBACK_DAYS)).shift(1)
    daily['vol20'] = daily['ret1'].rolling(VOL_LOOKBACK_DAYS).std().shift(1)
    return daily.dropna()


def find_trades(symbol, daily):
    idx = daily.index
    n = len(daily)
    trades = []
    # Monthly rebalance dates: first trading day on/after each calendar month start
    month_starts = pd.date_range(idx.min(), idx.max(), freq='MS', tz='UTC')
    rebalance_positions = sorted(set(idx.searchsorted(d) for d in month_starts if idx.searchsorted(d) < n))

    for k in range(len(rebalance_positions) - 1):
        i = rebalance_positions[k]
        exit_i = rebalance_positions[k + 1]
        if i >= n or exit_i >= n:
            continue
        row = daily.iloc[i]
        trail_ret = row['trail_ret']
        vol = row['vol20']
        if pd.isna(trail_ret) or pd.isna(vol) or vol <= 0:
            continue
        direction = 1 if trail_ret > 0 else (-1 if trail_ret < 0 else 0)
        if direction == 0:
            continue

        entry_price = float(daily['open'].iloc[i])
        exit_price = float(daily['open'].iloc[exit_i])
        holding_days = exit_i - i
        period_vol = vol * np.sqrt(max(holding_days, 1))   # scale daily vol to the holding period
        if period_vol <= 0:
            continue

        realized_ret = direction * np.log(exit_price / entry_price)
        r_gross = np.clip(realized_ret / period_vol, -3.0, 3.0)   # bounded, same defensive pattern as tonight's other scripts
        cost_return = COST_POINTS[symbol] / entry_price
        cost_r = cost_return / period_vol * COST_MULT

        trades.append({'symbol': symbol, 'entry_time': idx[i], 'r_net': r_gross - cost_r})

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
    daily = load_daily(symbol)
    if daily is None:
        continue
    loaded.append(symbol)
    trades = find_trades(symbol, daily)
    print(f'  {symbol}: {len(daily)} daily bars, {len(trades)} monthly rebalance trades')
    all_trades.extend(trades)
    del daily
    gc.collect()

print(f'\nLoaded {len(loaded)} instruments: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')

if len(df) > 0:
    report('FULL HISTORY', df, loaded)

    # Same genuine out-of-sample discipline as everything else tonight --
    # news_breakout_indices_ftmo.py and ml_triple_barrier_ftmo.py both
    # looked real in aggregate and came back near-breakeven under this
    # exact test.
    HOLDOUT_START = pd.Timestamp('2025-01-01', tz='UTC')
    MIN_SELECTION_TRADES = 30
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
