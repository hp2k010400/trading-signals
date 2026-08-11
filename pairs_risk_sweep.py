"""
pairs_risk_sweep.py

Pairs mean-reversion trades rarely (~2/month, held up to 20 days each)
compared to the high-frequency M1 strategies tested earlier -- each
trade carries much more weight in a month's result, so risk can't
just be cranked up blindly. This sweeps RISK_PCT across several
levels and reports real monthly £ P&L plus a simplified Monte Carlo
safety check against FTMO's actual account rules at each level, same
methodology as fair_price_risk_scaling.py used for the other strategy.

HONEST LIMITATION: pairs trades can be held up to 20 days, but only
entry_time and final r_net are tracked (no day-by-day floating P&L
path). The Monte Carlo here approximates each trade's full R as
materializing on its entry day -- the same simplification already
built into the monthly P&L calc. This slightly understates true
intra-trade drawdown risk (a trade that's floating badly for days
before eventually recovering wouldn't show that interim dip here) --
flagging clearly rather than hiding it.

Run in Codespace: python -u pairs_risk_sweep.py
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
START_BAL = 70000.0
FTMO_TARGET = 0.10
FTMO_DAILY  = 0.05
FTMO_TOTAL  = 0.10
MC_RUNS = 5000
MAX_SIM_TRADES = 300
BLOCK_TRADES = 5   # bootstrap in blocks of 5 sequential trades, not calendar days

BROKER_UTC_OFFSET_HOURS = 3
RISK_SWEEP = [0.30, 0.50, 1.00, 1.50, 2.00, 3.00]

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011,
}
PAIRS = [
    ('DAX', 'NAS100'), ('DAX', 'SP500'), ('DAX', 'US30'),
    ('SP500', 'US30'),
    ('EURUSD', 'GBPUSD'), ('EURUSD', 'USDJPY'), ('GBPUSD', 'USDJPY'),
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
            direction = -1 if z > 0 else 1
            norm = spread_std.iloc[i]
            if pd.isna(norm) or norm <= 0:
                continue
            entry_idx = i + 1
            if entry_idx >= n:
                continue
            state = {'direction': direction, 'entry_idx': entry_idx, 'entry_day': entry_idx,
                     'norm': norm, 'a_entry': da['open'].iloc[entry_idx], 'b_entry': db['open'].iloc[entry_idx]}
            continue
        held = i - state['entry_day']
        exited = abs(z) < EXIT_Z or held >= MAX_HOLD_DAYS
        if exited:
            a_exit = da['close'].iloc[i]; b_exit = db['close'].iloc[i]
            ret_a_trade = np.log(a_exit / state['a_entry'])
            ret_b_trade = np.log(b_exit / state['b_entry'])
            spread_ret = state['direction'] * (ret_a_trade - ret_b_trade)
            cost_r = (COST_POINTS[sym_a] / state['a_entry'] + COST_POINTS[sym_b] / state['b_entry']) / state['norm']
            r_net = spread_ret / state['norm'] - cost_r
            trades.append({'entry_time': da.index[state['entry_day']], 'r_net': r_net})
            state = None
    return trades


print('Loading FTMO M1 data, building daily bars...')
loaded = [s for s in FILES if load_daily(s, FILES[s])]
print(f'Loaded: {loaded}\n')

all_trades = []
for sym_a, sym_b in PAIRS:
    if sym_a not in loaded or sym_b not in loaded:
        continue
    trades = simulate_pair(sym_a, sym_b)
    all_trades.extend(trades)

df = pd.DataFrame(all_trades).sort_values('entry_time').reset_index(drop=True)
print(f'Total trades (7 pairs): {len(df)}\n')
r_values = df['r_net'].values
n_trades = len(r_values)

for risk_pct in RISK_SWEEP:
    rpt = risk_pct / 100.0

    # Real monthly P&L at this risk level
    df['month'] = df['entry_time'].dt.to_period('M')
    rows = []
    for month, g in df.groupby('month'):
        equity = START_BAL
        for r in g.sort_values('entry_time')['r_net']:
            equity += equity * rpt * r
        rows.append({'pnl_gbp': equity - START_BAL})
    monthly = pd.DataFrame(rows)
    median_month = monthly['pnl_gbp'].median()
    worst_month = monthly['pnl_gbp'].min()
    pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100

    # Simplified Monte Carlo -- trade-block bootstrap, each trade's R
    # materializes fully on its entry "day" (see docstring limitation)
    def simulate_one(rng):
        equity = START_BAL
        trades_done = 0
        while trades_done < MAX_SIM_TRADES:
            start = rng.integers(0, max(1, n_trades - BLOCK_TRADES))
            for b in range(BLOCK_TRADES):
                idx = start + b
                if idx >= n_trades:
                    break
                day_start_equity = equity
                equity += equity * rpt * r_values[idx]
                daily_loss = (day_start_equity - equity) / START_BAL
                if daily_loss > FTMO_DAILY:
                    return 'FAILED_DAILY'
                if (START_BAL - equity) / START_BAL > FTMO_TOTAL:
                    return 'FAILED_TOTAL'
                if (equity - START_BAL) / START_BAL >= FTMO_TARGET:
                    return 'PASSED'
                trades_done += 1
                if trades_done >= MAX_SIM_TRADES:
                    break
        return 'TIMEOUT'

    rng = np.random.default_rng(21)
    results = [simulate_one(rng) for _ in range(MC_RUNS)]
    n_pass = sum(1 for r in results if r == 'PASSED')
    n_daily_fail = sum(1 for r in results if r == 'FAILED_DAILY')
    n_total_fail = sum(1 for r in results if r == 'FAILED_TOTAL')

    print(f'{"="*80}')
    print(f'  RISK = {risk_pct}%')
    print(f'{"="*80}')
    print(f'  Median month: £{median_month:>+8,.0f}   Worst month: £{worst_month:>+8,.0f}   '
          f'Profitable months: {pct_profitable:.1f}%')
    print(f'  MC pass rate: {n_pass}/{MC_RUNS} ({n_pass/MC_RUNS*100:.2f}%)   '
          f'Failed daily: {n_daily_fail} ({n_daily_fail/MC_RUNS*100:.2f}%)   '
          f'Failed total: {n_total_fail} ({n_total_fail/MC_RUNS*100:.2f}%)\n')

print('Done.')
