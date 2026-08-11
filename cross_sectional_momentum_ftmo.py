"""
cross_sectional_momentum_ftmo.py

The direct companion to time_series_momentum_ftmo.py (the one strategy
tonight with a genuinely credible blind holdout, PF 1.47) -- and NOT
another reversal variant, since both reversal ideas tried tonight
(absolute Bollinger+RSI and cross-sectional short-term reversal) failed
decisively. That's a real pattern, not coincidence: the two things that
actually worked were trend/carry-style, not fast-reversal-style, which
lines up with market efficiency (faster, more obvious effects get
arbitraged away faster).

Cross-sectional momentum (Jegadeesh & Titman 1993) is TSM's sister
strategy in the academic literature: instead of "is this instrument's
own trailing return positive" (time-series momentum, absolute), it's
"is this instrument outperforming the REST of the universe" (relative
ranking). Same trend-following logic, applied as a ranking instead of
a sign.

MECHANISM:
  1. Monthly rebalance. For each instrument, trailing LOOKBACK_DAYS
     (~3 months) return, vol-normalized (dividing by 20-day realized
     vol) so the ranking isn't dominated by whichever instrument is
     inherently most volatile.
  2. Rank all instruments. LONG the N_LEGS strongest (highest
     normalized momentum), SHORT the N_LEGS weakest.
  3. Hold 1 month, rebalance.
  4. R = direction x forward monthly return / vol-at-entry (scaled to
     the holding period) -- same convention as time_series_momentum
     _ftmo.py and cross_sectional_reversal_ftmo.py.

Real spread costs (1.5x stress multiplier), confirmed UTC+3 offset,
walk-forward discipline, and the same genuine blind selection/holdout
split used on every other strategy tonight before trusting any
full-history number.

Run in Codespace: python -u cross_sectional_momentum_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
LOOKBACK_DAYS = 63       # ~3 trading months
VOL_LOOKBACK_DAYS = 20
N_LEGS = 5
COST_MULT = 1.5
MIN_INSTRUMENTS_FOR_RANK = 10
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
    daily['trail_ret'] = np.log(daily['close'] / daily['close'].shift(LOOKBACK_DAYS))
    daily['vol20'] = daily['ret1'].rolling(VOL_LOOKBACK_DAYS).std()
    daily['mom_z'] = daily['trail_ret'] / (daily['vol20'] * np.sqrt(LOOKBACK_DAYS))
    return daily.dropna(subset=['mom_z'])


print('Loading daily bars for all instruments...')
daily_data = {}
for symbol in FILES:
    d = load_daily(symbol)
    if d is None:
        continue
    daily_data[symbol] = d
    print(f'  {symbol}: {len(d)} daily bars')
    gc.collect()

loaded = sorted(daily_data.keys())
print(f'\nLoaded {len(loaded)} instruments: {loaded}')

mom_wide = pd.DataFrame({s: d['mom_z'] for s, d in daily_data.items()})

# Monthly rebalance dates: first trading day on/after each calendar month start
all_dates = mom_wide.index
month_starts = pd.date_range(all_dates.min(), all_dates.max(), freq='MS', tz='UTC')
rebalance_dates = sorted(set(d for d in month_starts if d >= all_dates.min() and d <= all_dates.max()))

all_trades = []
for k in range(len(rebalance_dates) - 1):
    date = rebalance_dates[k]
    next_date = rebalance_dates[k + 1]
    pos_in_wide = mom_wide.index.searchsorted(date)
    if pos_in_wide >= len(mom_wide):
        continue
    row = mom_wide.iloc[pos_in_wide].dropna()
    if len(row) < MIN_INSTRUMENTS_FOR_RANK:
        continue
    ranked = row.sort_values()
    losers = ranked.index[:N_LEGS]     # weakest momentum -- SHORT
    winners = ranked.index[-N_LEGS:]   # strongest momentum -- LONG

    legs = [(s, 1) for s in winners] + [(s, -1) for s in losers]
    for symbol, direction in legs:
        d = daily_data[symbol]
        d_idx = d.index
        entry_pos = d_idx.searchsorted(date) + 1
        exit_pos = d_idx.searchsorted(next_date) + 1
        if entry_pos >= len(d) or exit_pos >= len(d) or exit_pos <= entry_pos:
            continue
        entry_price = float(d['open'].iloc[entry_pos])
        exit_price = float(d['open'].iloc[exit_pos])
        vol_at_signal = float(d['vol20'].iloc[d_idx.searchsorted(date)])
        if pd.isna(vol_at_signal) or vol_at_signal <= 0:
            continue
        holding_days = exit_pos - entry_pos
        period_vol = vol_at_signal * np.sqrt(max(holding_days, 1))

        realized_ret = direction * np.log(exit_price / entry_price)
        r_gross = np.clip(realized_ret / period_vol, -3.0, 3.0)
        cost_return = COST_POINTS[symbol] / entry_price
        cost_r = cost_return / period_vol * COST_MULT

        all_trades.append({'symbol': symbol, 'entry_time': d_idx[entry_pos], 'r_net': r_gross - cost_r})

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'\nTotal trades: {len(df)}')


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


if len(df) > 0:
    report('FULL HISTORY', df, loaded)

    HOLDOUT_START = pd.Timestamp('2025-01-01', tz='UTC')
    MIN_SELECTION_TRADES = 20
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
