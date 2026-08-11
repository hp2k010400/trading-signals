"""
lesser_traded_pairs_ftmo.py

Same relative-return z-score mean-reversion mechanism as
pairs_walkforward_monthly.py (the one strategy tonight that showed a
real, if modest, edge on FTMO data), now applied to natural pairs
within the lesser-traded instrument set instead of the original
index/major-FX pairs.

Pair selection is not arbitrary -- each pair shares a common leg,
which is what makes a genuine mean-reverting spread plausible in the
first place (same logic as EURUSD/GBPUSD/USDJPY all sharing USD):
  AUDNZD / AUDCAD / AUDCHF   -- all AUD crosses
  USDCHF / USDCAD            -- both USD crosses

COST ESTIMATES ARE UNCALIBRATED -- see lesser_traded_donchian_ftmo.py
for the same caveat.

MECHANISM (unchanged from pairs_walkforward_monthly.py):
  1. Daily relative return over LOOKBACK_DAYS, z-scored against a
     rolling ZSCORE_WINDOW-day history.
  2. Enter when |z| > ENTRY_Z (short the outperformer / long the
     underperformer). Exit when |z| < EXIT_Z or MAX_HOLD_DAYS reached.
  3. R normalized by the same rolling spread_std that defines the
     entry z-score (period-matched, not daily_std).

Same locked walk-forward discipline, confirmed UTC+3 broker offset
correction from the start.

Run in Codespace: python -u lesser_traded_pairs_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

LOOKBACK_DAYS = 20
ZSCORE_WINDOW = 100
ENTRY_Z = 2.0
EXIT_Z = 0.5
MAX_HOLD_DAYS = 20
WALK_FORWARD_MONTHS = 6
RISK_PCT = 0.30
START_BAL = 70000.0

BROKER_UTC_OFFSET_HOURS = 3   # confirmed directly against MT5 (TimeCurrent()-TimeGMT())

FILES = {
    'AUDNZD': 'AUDNZD_M1_ftmo.csv',
    'AUDCAD': 'AUDCAD_M1_ftmo.csv',
    'AUDCHF': 'AUDCHF_M1_ftmo.csv',
    'USDCHF': 'USDCHF_M1_ftmo.csv',
    'USDCAD': 'USDCAD_M1_ftmo.csv',
}
# UNCALIBRATED ESTIMATES -- see lesser_traded_donchian_ftmo.py
COST_POINTS = {
    'AUDNZD': 0.0004, 'AUDCAD': 0.0004, 'AUDCHF': 0.0004,
    'USDCHF': 0.00015, 'USDCAD': 0.00015,
}
PAIRS = [
    ('AUDNZD', 'AUDCAD'), ('AUDNZD', 'AUDCHF'), ('AUDCAD', 'AUDCHF'),
    ('USDCHF', 'USDCAD'),
]

_daily = {}

def load_daily(k, fn):
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    _daily[k] = daily
    return True


def simulate_pair(sym_a, sym_b):
    da = _daily[sym_a]; db = _daily[sym_b]
    common_idx = da.index.intersection(db.index)
    da = da.loc[common_idx]; db = db.loc[common_idx]
    n = len(da)
    if n < ZSCORE_WINDOW + LOOKBACK_DAYS + 10:
        return []

    ret_a = np.log(da['close'] / da['close'].shift(1)).values
    ret_b = np.log(db['close'] / db['close'].shift(1)).values
    rel_ret = ret_a - ret_b
    rolling_spread = pd.Series(rel_ret).rolling(LOOKBACK_DAYS).sum()
    spread_mean = rolling_spread.rolling(ZSCORE_WINDOW).mean()
    spread_std = rolling_spread.rolling(ZSCORE_WINDOW).std()
    zscore = (rolling_spread - spread_mean) / spread_std

    trades = []
    state = None
    for i in range(ZSCORE_WINDOW + LOOKBACK_DAYS, n - 1):
        z = zscore.iloc[i]
        if pd.isna(z):
            continue

        if state is None:
            if abs(z) < ENTRY_Z:
                continue
            direction = -1 if z > 0 else 1   # -1: short A/long B ; +1: long A/short B
            norm = spread_std.iloc[i]
            if pd.isna(norm) or norm <= 0:
                continue
            entry_idx = i + 1   # enter next day's open, no lookahead
            if entry_idx >= n:
                continue
            state = {'direction': direction, 'entry_idx': entry_idx, 'entry_day': entry_idx,
                     'norm': norm, 'a_entry': da['open'].iloc[entry_idx], 'b_entry': db['open'].iloc[entry_idx]}
            continue

        held = i - state['entry_day']
        exited = False
        if abs(z) < EXIT_Z:
            exited = True
        elif held >= MAX_HOLD_DAYS:
            exited = True

        if exited:
            a_exit = da['close'].iloc[i]
            b_exit = db['close'].iloc[i]
            ret_a_trade = np.log(a_exit / state['a_entry'])
            ret_b_trade = np.log(b_exit / state['b_entry'])
            spread_ret = state['direction'] * (ret_a_trade - ret_b_trade)
            cost_r = (COST_POINTS[sym_a] / state['a_entry'] + COST_POINTS[sym_b] / state['b_entry']) / state['norm']
            r_net = spread_ret / state['norm'] - cost_r
            trades.append({'entry_time': da.index[state['entry_day']], 'r_net': r_net})
            state = None

    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 2) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 1)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=28):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


print('Loading FTMO M1 data, building daily bars...')
loaded = [s for s in FILES if load_daily(s, FILES[s])]
print(f'Loaded: {loaded}\n')

all_trades = []
for sym_a, sym_b in PAIRS:
    if sym_a not in loaded or sym_b not in loaded:
        print(f'  {sym_a}/{sym_b}: missing data, skipped')
        continue
    trades = simulate_pair(sym_a, sym_b)
    for t in trades:
        t['pair'] = f'{sym_a}/{sym_b}'
    print(f'  {sym_a}/{sym_b}: {len(trades)} trades')
    all_trades.extend(trades)

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'\nTotal trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print_row('OVERALL', n, wr, pf, tot)

if len(df) > 0:
    print(f'\n  Per-pair:')
    for sym_a, sym_b in PAIRS:
        rv = df[df['pair'] == f'{sym_a}/{sym_b}']['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {sym_a}/{sym_b}', n2, wr2, pf2, tot2)

    # ============================================================
    #  PART 1: WALK-FORWARD (non-overlapping windows)
    # ============================================================
    print(f'\n{"#"*90}')
    print(f'  PART 1: WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    print(f'{"#"*90}')
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        label_suffix = ' (partial window)' if len(window_periods) < WALK_FORWARD_MONTHS else ''
        window_rv = df[df['period'].isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}{label_suffix}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    # ============================================================
    #  PART 2: REAL MONTHLY P&L (each month fresh from £70,000, 0.30% risk)
    # ============================================================
    print(f'\n{"#"*90}')
    print(f'  PART 2: MONTHLY P&L (each month simulated fresh from £70,000 at {RISK_PCT}% risk)')
    print(f'{"#"*90}')
    rpt = RISK_PCT / 100.0
    rows = []
    for period, g in df.groupby('period'):
        equity = START_BAL
        for r in g.sort_values('entry_time')['r_net']:
            equity += equity * rpt * r
        pnl = equity - START_BAL
        pnl_pct = pnl / START_BAL * 100
        rows.append({'month': str(period), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl_pct})

    monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
    print(f'  Months with activity: {len(monthly)}')
    print(f'  Best month:   {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  £{monthly["pnl_gbp"].max():>+9,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
    print(f'  Worst month:  {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  £{monthly["pnl_gbp"].min():>+9,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
    print(f'  Median month: £{monthly["pnl_gbp"].median():>+9,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
    print(f'  Mean month:   £{monthly["pnl_gbp"].mean():>+9,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
    pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
    print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

    print(f'\n  Full month-by-month:')
    for _, r in monthly.iterrows():
        print(f'    {r["month"]}  £{r["pnl_gbp"]:>+9,.0f}  {r["pnl_pct"]:>+6.2f}%  N={r["trades"]:.0f}')

print('\nDone.')
