"""
tsm_regime_temporal_ablation_ftmo.py

Continuation of the post-mortem after TSM was classified B (promising
but insufficient evidence): 2 of 4 independent OOS windows lost, and
the permutation test only reached the 85.6th percentile (short of the
95th-percentile significance bar). The objective now is NOT to make
TSM profitable -- it is to understand WHY it worked in 2019-2021 and
2025+ but not 2021-2023 or 2023-2025, and whether that's explained by
identifiable market regimes or is just noise.

This script does NOT construct filters, does NOT optimize anything,
and does NOT modify the strategy's rules. It produces descriptive
tables only. Per the research directive: if no convincing regime
explanation emerges, that must be reported honestly, not manufactured.

PART A -- TEMPORAL DECOMPOSITION: by year, instrument, asset class,
long vs short, to see exactly where the edge and the losses came from.

PART B -- REGIME DECOMPOSITION: each monthly rebalance date is
classified into regime terciles (top/mid/bottom third) on four
descriptive market-environment variables computed from data available
BEFORE that date:
  - mkt_vol: cross-sectional average of instruments' own 20-day vol
  - mkt_corr: average pairwise 60-day correlation across the universe
  - dispersion: cross-sectional std of 21-day returns across instruments
  - breadth: fraction of the universe with a positive 252-day trailing
    return (extreme = strong one-directional regime, ~50% = mixed)
Trade outcomes for that date are then reported by regime tercile.

PART C -- WINNING VS LOSING PERIOD COMPARISON: the same four regime
variables, averaged over the two winning OOS windows (2019-2021,
2025+) vs the two losing OOS windows (2021-2023, 2023-2025) --
looking for variables that were genuinely different BEFORE the
strategy traded, not explanations invented after the fact.

PART D -- SIMPLE ABLATION: (1) vol-scaling removed (raw capped return
instead of vol-normalized R) vs the real vol-scaled version: does
vol-scaling itself add value independent of direction accuracy? (2)
diversification: does the combined multi-instrument portfolio have a
better risk-adjusted profile than the average of trading each selected
instrument alone?

Run in Codespace: python -u tsm_regime_temporal_ablation_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
LOOKBACK_DAYS = 252
VOL_LOOKBACK_DAYS = 20
CORR_LOOKBACK_DAYS = 60
DISPERSION_LOOKBACK_DAYS = 21
COST_MULT = 1.5

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
ASSET_CLASS = {
    'DAX':'Index','NAS100':'Index','SP500':'Index','US30':'Index','UK100':'Index',
    'FRA40':'Index','JP225':'Index','AUS200':'Index','EU50':'Index','US2000':'Index','HK50':'Index',
    'EURUSD':'FX','GBPUSD':'FX','USDJPY':'FX','AUDNZD':'FX','AUDCAD':'FX','AUDCHF':'FX','USDCHF':'FX','USDCAD':'FX','USDINDEX':'FX',
    'GOLD':'Metal','SILVER':'Metal','PLATINUM':'Metal','PALLADIUM':'Metal',
    'NATGAS':'Energy','WTIOIL':'Energy','BRENTOIL':'Energy','COPPER':'Metal',
}

WINNING_WINDOWS = [(pd.Timestamp('2019-01-01', tz='UTC'), pd.Timestamp('2021-01-01', tz='UTC')),
                    (pd.Timestamp('2025-01-01', tz='UTC'), pd.Timestamp('2027-01-01', tz='UTC'))]
LOSING_WINDOWS = [(pd.Timestamp('2021-01-01', tz='UTC'), pd.Timestamp('2023-01-01', tz='UTC')),
                   (pd.Timestamp('2023-01-01', tz='UTC'), pd.Timestamp('2025-01-01', tz='UTC'))]


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
    daily['trail_ret'] = np.log(daily['close'] / daily['close'].shift(LOOKBACK_DAYS)).shift(1)
    daily['vol20'] = daily['ret1'].rolling(VOL_LOOKBACK_DAYS).std().shift(1)
    daily['ret21'] = np.log(daily['close'] / daily['close'].shift(DISPERSION_LOOKBACK_DAYS)).shift(1)
    return daily.dropna(subset=['trail_ret', 'vol20'])


print('Loading daily bars for all instruments...')
daily_data = {}
for symbol in FILES:
    d = load_daily(symbol)
    if d is None:
        continue
    daily_data[symbol] = d
    gc.collect()
loaded = sorted(daily_data.keys())
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

# ---- Build wide tables for cross-sectional regime variables ----
vol_wide = pd.DataFrame({s: d['vol20'] for s, d in daily_data.items()})
ret1_wide = pd.DataFrame({s: d['ret1'] for s, d in daily_data.items()})
ret21_wide = pd.DataFrame({s: d['ret21'] for s, d in daily_data.items()})
trail_wide = pd.DataFrame({s: d['trail_ret'] for s, d in daily_data.items()})

mkt_vol = vol_wide.mean(axis=1)
dispersion = ret21_wide.std(axis=1)
breadth = (trail_wide > 0).mean(axis=1)

# rolling average pairwise correlation (60-day) -- computed once per day is
# expensive for 28 instruments x thousands of days; approximate via the
# average correlation of each instrument's returns with the equal-weight
# universe return, which is a standard, much cheaper proxy for average
# pairwise correlation and moves the same direction.
universe_ret = ret1_wide.mean(axis=1)
mkt_corr_components = {}
for s in loaded:
    mkt_corr_components[s] = ret1_wide[s].rolling(CORR_LOOKBACK_DAYS).corr(universe_ret)
mkt_corr = pd.DataFrame(mkt_corr_components).mean(axis=1)

regime_df = pd.DataFrame({'mkt_vol': mkt_vol, 'dispersion': dispersion,
                           'breadth': breadth, 'mkt_corr': mkt_corr}).dropna()
print(f'Regime variable table: {len(regime_df)} days.\n')


# ---- Generate TSM trade opportunities (identical mechanism, no changes) ----
def find_trade_opportunities(symbol, daily):
    idx = daily.index
    n = len(daily)
    opps = []
    month_starts = pd.date_range(idx.min(), idx.max(), freq='MS', tz='UTC')
    rebalance_positions = sorted(set(idx.searchsorted(d) for d in month_starts if idx.searchsorted(d) < n))
    for k in range(len(rebalance_positions) - 1):
        i = rebalance_positions[k]
        exit_i = rebalance_positions[k + 1]
        if i >= n or exit_i >= n:
            continue
        row = daily.iloc[i]
        trail_ret = row['trail_ret']; vol = row['vol20']
        if pd.isna(trail_ret) or pd.isna(vol) or vol <= 0:
            continue
        direction = 1 if trail_ret > 0 else (-1 if trail_ret < 0 else 0)
        if direction == 0:
            continue
        entry_price = float(daily['open'].iloc[i]); exit_price = float(daily['open'].iloc[exit_i])
        holding_days = exit_i - i
        period_vol = vol * np.sqrt(max(holding_days, 1))
        if period_vol <= 0:
            continue
        unsigned_log_ret = np.log(exit_price / entry_price)
        cost_return = COST_POINTS[symbol] / entry_price
        cost_r = cost_return / period_vol * COST_MULT
        r_gross = np.clip(direction * unsigned_log_ret / period_vol, -3.0, 3.0)
        r_net = r_gross - cost_r
        r_gross_unscaled = np.clip(direction * unsigned_log_ret, -0.5, 0.5)  # for the no-vol-scaling ablation
        opps.append({'symbol': symbol, 'entry_time': idx[i], 'direction': direction,
                     'r_net': r_net, 'r_gross_unscaled': r_gross_unscaled - cost_return,
                     'holding_days': holding_days})
    return opps


all_opps = []
for symbol in loaded:
    all_opps.extend(find_trade_opportunities(symbol, daily_data[symbol]))
trades = pd.DataFrame(all_opps).sort_values('entry_time').reset_index(drop=True)
trades['asset_class'] = trades['symbol'].map(ASSET_CLASS)
trades['side'] = np.where(trades['direction'] > 0, 'LONG', 'SHORT')
trades['year'] = trades['entry_time'].dt.year
print(f'Total trade opportunities: {len(trades)}\n')


def stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(N=0, WR=0.0, PF=0.0, R=0.0, Sharpe=0.0)
    wins = r[r > 0]; losses = r[r <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r) * 100, 1)
    sharpe = round(r.mean() / r.std(), 3) if r.std() > 0 else 0.0
    return dict(N=len(r), WR=wr, PF=pf, R=round(r.sum(), 2), Sharpe=sharpe)


def print_table(title, groups):
    print(f'\n{"="*90}\n  {title}\n{"="*90}')
    for label, r in groups:
        s = stats(r)
        flag = ' <- LOSING' if s['R'] < 0 else ''
        print(f'  {label+flag:<30}  N={s["N"]:>5}  WR={s["WR"]:>5.1f}%  PF={s["PF"]:>5.2f}  '
              f'R={s["R"]:>+8.2f}  Sharpe={s["Sharpe"]:>+6.3f}')


# ============================================================
# PART A -- TEMPORAL DECOMPOSITION
# ============================================================
print_table('PART A1: BY YEAR', [(str(y), trades[trades['year'] == y]['r_net'].values)
                                   for y in sorted(trades['year'].unique())])
print_table('PART A2: BY INSTRUMENT', [(s, trades[trades['symbol'] == s]['r_net'].values)
                                         for s in loaded])
print_table('PART A3: BY ASSET CLASS', [(ac, trades[trades['asset_class'] == ac]['r_net'].values)
                                          for ac in sorted(trades['asset_class'].unique())])
print_table('PART A4: LONG vs SHORT', [(side, trades[trades['side'] == side]['r_net'].values)
                                         for side in ['LONG', 'SHORT']])

# ============================================================
# PART B -- REGIME DECOMPOSITION (descriptive terciles, no filtering)
# ============================================================
trades_regime = trades.merge(regime_df, left_on='entry_time', right_index=True, how='left')
print(f'\nTrades with matched regime data: {trades_regime["mkt_vol"].notna().sum()} / {len(trades_regime)}')

for var in ['mkt_vol', 'dispersion', 'breadth', 'mkt_corr']:
    valid = trades_regime.dropna(subset=[var])
    if len(valid) < 30:
        print(f'\n  Skipping {var} tercile breakdown -- insufficient matched data.')
        continue
    terciles = pd.qcut(valid[var], 3, labels=['LOW', 'MID', 'HIGH'], duplicates='drop')
    groups = [(f'{var}={t}', valid[terciles == t]['r_net'].values) for t in ['LOW', 'MID', 'HIGH'] if t in terciles.cat.categories]
    print_table(f'PART B: REGIME TERCILES -- {var}', groups)

# ============================================================
# PART C -- WINNING vs LOSING PERIOD REGIME COMPARISON
# ============================================================
print(f'\n{"="*90}\n  PART C: REGIME VARIABLES IN WINNING vs LOSING OOS WINDOWS\n{"="*90}')
print('  (average level of each regime variable during each window -- NOT trade outcomes,')
print('   this is the market environment itself, checked for genuine pre-existing differences)')

win_mask = pd.Series(False, index=regime_df.index)
for s, e in WINNING_WINDOWS:
    win_mask |= (regime_df.index >= s) & (regime_df.index < e)
lose_mask = pd.Series(False, index=regime_df.index)
for s, e in LOSING_WINDOWS:
    lose_mask |= (regime_df.index >= s) & (regime_df.index < e)

for var in ['mkt_vol', 'dispersion', 'breadth', 'mkt_corr']:
    win_avg = regime_df.loc[win_mask, var].mean()
    lose_avg = regime_df.loc[lose_mask, var].mean()
    diff_pct = (win_avg - lose_avg) / lose_avg * 100 if lose_avg != 0 else float('nan')
    print(f'  {var:<12}  winning windows avg={win_avg:.5f}   losing windows avg={lose_avg:.5f}   '
          f'diff={diff_pct:+.1f}%')

# ============================================================
# PART D -- SIMPLE ABLATION
# ============================================================
print(f'\n{"="*90}\n  PART D1: VOLATILITY SCALING ABLATION\n{"="*90}')
print_table('With vol-scaling (real strategy)', [('real', trades['r_net'].values)])
print_table('Without vol-scaling (raw capped return, cost still applied)', [('no_vol_scaling', trades['r_gross_unscaled'].values)])

print(f'\n{"="*90}\n  PART D2: DIVERSIFICATION -- combined portfolio vs average of isolated instruments\n{"="*90}')
combined = stats(trades['r_net'].values)
per_instrument_sharpes = []
for s in loaded:
    rv = trades[trades['symbol'] == s]['r_net'].values
    if len(rv) >= 10:
        per_instrument_sharpes.append(stats(rv)['Sharpe'])
avg_individual_sharpe = np.mean(per_instrument_sharpes) if per_instrument_sharpes else float('nan')
print(f'  Combined portfolio Sharpe (all instruments, all trades pooled): {combined["Sharpe"]:+.3f}')
print(f'  Average of each instrument\'s OWN Sharpe in isolation:          {avg_individual_sharpe:+.3f}')
print(f'  (if combined > average individual, that\'s a real diversification effect,')
print(f'   not just "the same edge repeated on more instruments")')

print('\nDone.')
