"""
alpha03_strategy_gold_metals_leadlag_ftmo.py

Second leg of alpha03, tested separately because it rests on much
deeper data than the USDINDEX leg that just failed decisively (PF
0.65, all 11 instruments losing) -- that rejection was plausibly
driven by USDINDEX only having ~17 months of real history, not a
structural finding. GOLD has full multi-year depth like the majors,
and the descriptive test showed a consistent, economically sensible
pattern into the other precious metals:
  GOLD -> SILVER:    N=1719, top-quintile +29.18bp vs bottom -20.80bp
  GOLD -> PALLADIUM: N=2656, top-quintile +24.11bp vs bottom -24.25bp
  GOLD -> PLATINUM:  N=2659, top-quintile +15.76bp vs bottom -10.61bp
Precious metals co-moving with a one-day lag from gold (the most
liquid, most-watched member of the complex) is a real, plausible
commodity-complex mechanism, not a coincidence found by mining many
leader/follower combinations -- gold leading silver/platinum/palladium
specifically (not leading FX or indices with the same strength) is
exactly the kind of narrow, mechanistically-coherent pattern that's
more trustworthy than a scattergun finding.

MECHANISM (same no-lookahead structure as the USDINDEX version):
  1. Each day, compute GOLD's daily return.
  2. Rolling (trailing 60-day, causal) 80th/20th percentile of GOLD's
     own daily returns.
  3. GOLD >= rolling 80th pct -> LONG each metal tomorrow (follow the
     gold move, not fade it -- the descriptive test showed metals move
     the SAME direction as gold's prior-day move, not the opposite).
  4. GOLD <= rolling 20th pct -> SHORT each metal tomorrow.
  5. Entry at tomorrow's open, ATR-based stop/target, exit at ~24h.

Real spread costs (1.5x stress multiplier), confirmed UTC+3 offset,
walk-forward discipline, and the same blind selection/holdout split.

Run in Codespace: python -u alpha03_strategy_gold_metals_leadlag_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
ROLLING_QUANTILE_DAYS = 60
ATR_PERIOD = 14
ATR_STOP_MULT = 1.5
RR = 1.5
COST_MULT = 1.5
MIN_STOP_DIST_PCT = 0.0003
WALK_FORWARD_MONTHS = 6
RISK_PCT = 0.30
START_BAL = 70000.0

LEADER_FILE = 'XAUUSD_M1_ftmo.csv'
METAL_FILES = {
    'SILVER':  'SILVER_M1_ftmo.csv',
    'PALLADIUM':'PALLADIUM_M1_ftmo.csv',
    'PLATINUM':'PLATINUM_M1_ftmo.csv',
}
COST_POINTS = {
    'SILVER':0.025, 'PALLADIUM':2.0, 'PLATINUM':0.5,
}


def load_leader_signal():
    if not os.path.exists(LEADER_FILE):
        return None
    df = pd.read_csv(LEADER_FILE, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    daily = df.resample('1D').agg({'close':'last'}).dropna()
    del df
    daily = daily[daily['close'] > 0]
    daily['ret1'] = np.log(daily['close'] / daily['close'].shift(1))
    daily['q80'] = daily['ret1'].rolling(ROLLING_QUANTILE_DAYS).quantile(0.8).shift(1)
    daily['q20'] = daily['ret1'].rolling(ROLLING_QUANTILE_DAYS).quantile(0.2).shift(1)
    return daily.dropna(subset=['q80', 'q20'])


def load_follower_h1(symbol):
    fn = METAL_FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    del df
    prev_close = h1['close'].shift(1)
    tr = pd.concat([h1['high']-h1['low'], (h1['high']-prev_close).abs(), (h1['low']-prev_close).abs()], axis=1).max(axis=1)
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    return h1.dropna()


print('Loading GOLD leader signal...')
leader = load_leader_signal()
if leader is None:
    raise SystemExit(f'{LEADER_FILE} not found.')
print(f'Leader signal days: {len(leader)}\n')

all_trades = []
loaded = []
for symbol in METAL_FILES:
    h1 = load_follower_h1(symbol)
    if h1 is None:
        continue
    loaded.append(symbol)
    h1_idx = h1.index

    for signal_date, row in leader.iterrows():
        r = row['ret1']
        if r >= row['q80']:
            direction = 1     # follow gold UP
        elif r <= row['q20']:
            direction = -1    # follow gold DOWN
        else:
            continue

        entry_time = signal_date + pd.Timedelta(days=1)
        entry_pos = h1_idx.searchsorted(entry_time)
        if entry_pos >= len(h1):
            continue
        atr = h1['atr'].iloc[entry_pos]
        if pd.isna(atr) or atr <= 0:
            continue
        entry_price = float(h1['open'].iloc[entry_pos])
        stop_dist = ATR_STOP_MULT * atr
        if stop_dist < entry_price * MIN_STOP_DIST_PCT:
            continue
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        exit_time = entry_time + pd.Timedelta(hours=23)
        exit_pos = h1_idx.searchsorted(exit_time)
        window_end = min(exit_pos, len(h1))
        future = h1.iloc[entry_pos + 1: window_end]
        r_gross = None
        if len(future) > 0:
            fh = future['high'].values; fl = future['low'].values; fc = future['close'].values
            for k in range(len(future)):
                if direction == 1:
                    if fh[k] >= tp_price: r_gross = RR; break
                    if fl[k] <= stop_price: r_gross = -1.0; break
                else:
                    if fl[k] <= tp_price: r_gross = RR; break
                    if fh[k] >= stop_price: r_gross = -1.0; break
            if r_gross is None:
                final_close = fc[-1]
                r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                           else (entry_price - final_close) / stop_dist)
                r_gross = max(-2.0, min(RR + 0.5, r_gross))
        else:
            r_gross = -1.0

        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        all_trades.append({'symbol': symbol, 'entry_time': h1_idx[entry_pos], 'r_net': r_gross - cost_r})

    del h1
    gc.collect()

print(f'Loaded {len(loaded)} follower metals: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')


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
    print(f'\n{"="*90}\n  {label}  (N={len(sub_df)})\n{"="*90}')
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
    n_losing = 0; n_total = 0
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
