"""
cross_sectional_reversal_ftmo.py

Structurally different from the Bollinger+RSI mean-reversion idea that
just failed decisively (23/23 losing windows) -- that bet an
instrument reverts to ITS OWN average. This bets on the SPREAD between
today's best and worst performers narrowing, the same underlying logic
as the pairs mean-reversion strategy that actually survived its blind
holdout, just broadened across the whole 27-instrument universe
instead of 2 legs at a time. Real, published anomaly (short-term
cross-sectional reversal -- Lehmann 1990, Jegadeesh 1990), not
improvised.

MECHANISM:
  1. Each trading day, for every instrument with valid data: compute
     a vol-normalized 1-day return z-score (ret1 / 20-day realized
     vol) -- normalizing by each instrument's OWN volatility before
     ranking is what makes the cross-section fair; without it, the
     ranking would just be "which instrument is most volatile today,"
     not "which move was actually extreme for that instrument."
  2. Rank all instruments by that z-score. LONG the N_LEGS biggest
     RELATIVE losers, SHORT the N_LEGS biggest RELATIVE winners.
  3. Enter at next day's open, exit HOLD_DAYS later's open, rebalance.
  4. R = direction x forward return / vol-at-entry (scaled to the
     holding period) -- same vol-normalized R-multiple convention as
     time_series_momentum_ftmo.py.

Real spread costs (1.5x stress multiplier), confirmed UTC+3 offset,
walk-forward discipline. Note on validation: unlike the per-instrument
strategies tonight, this is inherently a PORTFOLIO-level bet -- the
ranking and legs depend on ALL instruments simultaneously, so removing
"bad" instruments the way earlier scripts did doesn't cleanly apply
(it would change the entire cross-section for every remaining trade
too). Validated instead with a straight temporal holdout: FULL HISTORY
vs a RECENT-ONLY (2025 onward) run using the identical, unmodified
strategy -- no re-selection, no cherry-picking.

Run in Codespace: python -u cross_sectional_reversal_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
VOL_LOOKBACK_DAYS = 20
N_LEGS = 5              # long the 5 biggest relative losers, short the 5 biggest relative winners
HOLD_DAYS = 1           # classic short-term reversal horizon
MIN_INSTRUMENTS_FOR_RANK = 10
COST_MULT = 1.5
WALK_FORWARD_MONTHS = 6
RISK_PCT = 0.30
START_BAL = 70000.0
RECENT_CUTOFF = pd.Timestamp('2025-01-01', tz='UTC')

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
    daily['vol20'] = daily['ret1'].rolling(VOL_LOOKBACK_DAYS).std()
    daily['z'] = daily['ret1'] / daily['vol20']
    return daily.dropna(subset=['z'])


print('Loading daily bars for all instruments (small once resampled -- kept in memory together,')
print('required for cross-sectional ranking across the whole universe on each date)...')
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

# Build the wide z-score matrix (date x instrument) for ranking
z_wide = pd.DataFrame({s: d['z'] for s, d in daily_data.items()})
all_dates = z_wide.index

all_trades = []
for i, date in enumerate(all_dates):
    row = z_wide.loc[date].dropna()
    if len(row) < MIN_INSTRUMENTS_FOR_RANK:
        continue
    ranked = row.sort_values()
    losers = ranked.index[:N_LEGS]     # most negative z -- go LONG (expect bounce)
    winners = ranked.index[-N_LEGS:]   # most positive z -- go SHORT (expect fade)

    legs = [(s, 1) for s in losers] + [(s, -1) for s in winners]
    for symbol, direction in legs:
        d = daily_data[symbol]
        d_idx = d.index
        pos = d_idx.searchsorted(date)
        entry_pos = pos + 1
        exit_pos = entry_pos + HOLD_DAYS
        if entry_pos >= len(d) or exit_pos >= len(d):
            continue
        entry_price = float(d['open'].iloc[entry_pos])
        exit_price = float(d['open'].iloc[exit_pos])
        vol_at_signal = float(d['vol20'].iloc[pos])
        if pd.isna(vol_at_signal) or vol_at_signal <= 0:
            continue
        period_vol = vol_at_signal * np.sqrt(HOLD_DAYS)

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
    recent_df = df[df['entry_time'] >= RECENT_CUTOFF].reset_index(drop=True)
    report(f'RECENT ONLY ({RECENT_CUTOFF.date()} onward, SAME unmodified strategy -- '
           f'no re-selection/cherry-picking)', recent_df, loaded)

print('\nDone.')
