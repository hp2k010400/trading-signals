"""
tsm_multiperiod_permutation_ftmo.py

Phases 6-7 of the post-mortem research directive. TSM's single 2025+
holdout (PF 1.56 post-audit-fix) is NOT sufficient evidence on its
own -- this script answers the two questions that actually settle it:

PHASE 6 -- MULTIPLE INDEPENDENT OOS WINDOWS:
  Instead of one train/test split, walk forward through FOUR
  non-overlapping selection/test splits:
    OOS #1: select on 2016-2019, test on 2019-2021
    OOS #2: select on 2016-2021, test on 2021-2023
    OOS #3: select on 2016-2023, test on 2023-2025
    OOS #4: select on 2016-2025, test on 2025-2026 (the existing,
            now-familiar holdout -- included for continuity, NOT
            re-optimized)
  The strategy and selection RULE are identical in every window --
  nothing is tuned per-window. If PF 1.56-ish shows up consistently
  across independent windows, that's real evidence. If only the last
  window looks good, that's evidence of regime luck, not edge.

PHASE 7 -- PERMUTATION TEST:
  For the full trade set, replace each trade's REAL momentum-sign
  direction with a RANDOM direction (+1/-1, 50/50), keeping every
  other component identical (vol-scaling, cost, holding period,
  instrument, timing). Repeat 2000 times to build a null distribution
  of what PF looks like when the directional signal carries zero
  information but everything else about the strategy (diversification,
  vol-scaling, cost structure) is unchanged. Report what percentile the
  REAL strategy's PF falls into. This isolates whether the momentum
  SIGN itself is informative, separate from portfolio-construction
  effects (which the permutation preserves).

TSM's existing 2025+ holdout is NOT touched or re-optimized here --
this script only adds independent evidence around it.

Run in Codespace: python -u tsm_multiperiod_permutation_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
LOOKBACK_DAYS = 252
VOL_LOOKBACK_DAYS = 20
COST_MULT = 1.5
MIN_SELECTION_TRADES = 30
SELECTION_PF_THRESHOLD = 1.0
N_PERMUTATIONS = 2000

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
    # same lookahead fix as time_series_momentum_ftmo.py (audit, 2026-08-12)
    daily['trail_ret'] = np.log(daily['close'] / daily['close'].shift(LOOKBACK_DAYS)).shift(1)
    daily['vol20'] = daily['ret1'].rolling(VOL_LOOKBACK_DAYS).std().shift(1)
    return daily.dropna()


def find_trade_opportunities(symbol, daily):
    """Returns every monthly rebalance opportunity with the RAW (unsigned)
    forward log-return, vol, and cost -- direction kept separate so the
    permutation test can swap in a random direction without re-deriving
    anything else."""
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
        trail_ret = row['trail_ret']
        vol = row['vol20']
        if pd.isna(trail_ret) or pd.isna(vol) or vol <= 0:
            continue
        real_direction = 1 if trail_ret > 0 else (-1 if trail_ret < 0 else 0)
        if real_direction == 0:
            continue

        entry_price = float(daily['open'].iloc[i])
        exit_price = float(daily['open'].iloc[exit_i])
        holding_days = exit_i - i
        period_vol = vol * np.sqrt(max(holding_days, 1))
        if period_vol <= 0:
            continue

        unsigned_log_ret = np.log(exit_price / entry_price)   # direction NOT applied yet
        cost_return = COST_POINTS[symbol] / entry_price
        cost_r = cost_return / period_vol * COST_MULT

        opps.append({'symbol': symbol, 'entry_time': idx[i], 'real_direction': real_direction,
                     'unsigned_log_ret': unsigned_log_ret, 'period_vol': period_vol, 'cost_r': cost_r})
    return opps


def r_net_for_direction(opp, direction):
    r_gross = np.clip(direction * opp['unsigned_log_ret'] / opp['period_vol'], -3.0, 3.0)
    return r_gross - opp['cost_r']


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


print('Loading daily bars, generating trade opportunities (real direction preserved separately)...')
all_opps = []
loaded = []
for symbol in FILES:
    daily = load_daily(symbol)
    if daily is None:
        continue
    loaded.append(symbol)
    opps = find_trade_opportunities(symbol, daily)
    all_opps.extend(opps)
    del daily
    gc.collect()

opps_df = pd.DataFrame(all_opps)
if len(opps_df) == 0:
    raise SystemExit('No trade opportunities generated -- check CSVs are present.')
opps_df = opps_df.sort_values('entry_time').reset_index(drop=True)
opps_df['r_net_real'] = [r_net_for_direction(row, row['real_direction']) for _, row in opps_df.iterrows()]
print(f'\nLoaded {len(loaded)} instruments, {len(opps_df)} total trade opportunities.\n')


def select_and_test(sel_start, sel_end, test_start, test_end, label):
    sel = opps_df[(opps_df['entry_time'] >= sel_start) & (opps_df['entry_time'] < sel_end)]
    selected = []
    for symbol in loaded:
        rv = sel[sel['symbol'] == symbol]['r_net_real'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        if n2 >= MIN_SELECTION_TRADES and pf2 >= SELECTION_PF_THRESHOLD:
            selected.append(symbol)

    test = opps_df[(opps_df['entry_time'] >= test_start) & (opps_df['entry_time'] < test_end) &
                    (opps_df['symbol'].isin(selected))]
    n, wr, pf, tot = compute_stats(test['r_net_real'].values)
    print(f'\n{"="*90}')
    print(f'  {label}')
    print(f'  Selection window: {sel_start.date()} -> {sel_end.date()}  ({len(selected)} instruments selected: {selected})')
    print(f'  Test window:      {test_start.date()} -> {test_end.date()}')
    print(f'{"="*90}')
    print_row('TEST RESULT', n, wr, pf, tot)
    if n < 80:
        print('  WARNING: fewer than 80 trades -- treat as directionally indicative only.')
    return n, wr, pf, tot


print(f'\n{"#"*100}')
print(f'  PHASE 6: MULTIPLE INDEPENDENT OOS WINDOWS (same rule every time, nothing re-tuned per window)')
print(f'{"#"*100}')

utc = 'UTC'
windows = [
    (pd.Timestamp('2016-01-01', tz=utc), pd.Timestamp('2019-01-01', tz=utc),
     pd.Timestamp('2019-01-01', tz=utc), pd.Timestamp('2021-01-01', tz=utc), 'OOS #1 (select 2016-2019, test 2019-2021)'),
    (pd.Timestamp('2016-01-01', tz=utc), pd.Timestamp('2021-01-01', tz=utc),
     pd.Timestamp('2021-01-01', tz=utc), pd.Timestamp('2023-01-01', tz=utc), 'OOS #2 (select 2016-2021, test 2021-2023)'),
    (pd.Timestamp('2016-01-01', tz=utc), pd.Timestamp('2023-01-01', tz=utc),
     pd.Timestamp('2023-01-01', tz=utc), pd.Timestamp('2025-01-01', tz=utc), 'OOS #3 (select 2016-2023, test 2023-2025)'),
    (pd.Timestamp('2016-01-01', tz=utc), pd.Timestamp('2025-01-01', tz=utc),
     pd.Timestamp('2025-01-01', tz=utc), pd.Timestamp('2027-01-01', tz=utc), 'OOS #4 (select 2016-2025, test 2025+ -- the familiar holdout, included for continuity)'),
]

oos_results = []
for sel_start, sel_end, test_start, test_end, label in windows:
    result = select_and_test(sel_start, sel_end, test_start, test_end, label)
    oos_results.append((label, *result))

print(f'\n{"="*90}')
print('  PHASE 6 SUMMARY')
print(f'{"="*90}')
n_windows_losing = sum(1 for _, n, wr, pf, tot in oos_results if tot < 0)
for label, n, wr, pf, tot in oos_results:
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label}{flag}: N={n} PF={pf} R={tot:+.2f}')
print(f'\n  OOS windows losing: {n_windows_losing}/{len(oos_results)}')


print(f'\n{"#"*100}')
print(f'  PHASE 7: PERMUTATION TEST ({N_PERMUTATIONS} random-direction shuffles)')
print(f'{"#"*100}')

real_n, real_wr, real_pf, real_tot = compute_stats(opps_df['r_net_real'].values)
print(f'\n  REAL strategy (momentum-sign direction): N={real_n}  WR={real_wr}%  PF={real_pf}  R={real_tot:+.2f}')

rng = np.random.default_rng(42)
unsigned = opps_df['unsigned_log_ret'].values
period_vol = opps_df['period_vol'].values
cost_r = opps_df['cost_r'].values

null_pfs = np.empty(N_PERMUTATIONS)
null_totals = np.empty(N_PERMUTATIONS)
for p in range(N_PERMUTATIONS):
    random_dir = rng.choice([-1, 1], size=len(opps_df))
    r_gross = np.clip(random_dir * unsigned / period_vol, -3.0, 3.0)
    r_net = r_gross - cost_r
    wins = r_net[r_net > 0]; losses = r_net[r_net <= 0]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else 0.0
    null_pfs[p] = pf
    null_totals[p] = r_net.sum()

percentile_pf = (null_pfs < real_pf).mean() * 100
percentile_tot = (null_totals < real_tot).mean() * 100

print(f'\n  Null distribution (random direction, same vol-scaling/cost/instruments/timing):')
print(f'    Mean PF:   {null_pfs.mean():.3f}   (should be close to 1.0 if direction carries no info)')
print(f'    Std PF:    {null_pfs.std():.3f}')
print(f'    5th pct:   {np.percentile(null_pfs, 5):.3f}')
print(f'    95th pct:  {np.percentile(null_pfs, 95):.3f}')
print(f'\n  REAL PF ({real_pf}) beats {percentile_pf:.1f}% of random-direction permutations.')
print(f'  REAL total R ({real_tot:+.2f}) beats {percentile_tot:.1f}% of random-direction permutations.')
print(f'\n  Interpretation: >=95th percentile is conventionally "significant" (p<0.05, one-sided).')
print(f'  This tests ONLY whether the momentum SIGN carries information -- it does NOT test')
print(f'  whether diversification/vol-scaling alone (present in every permutation too) is real,')
print(f'  which is a separate, already-understood portfolio-construction effect.')

print('\nDone.')
