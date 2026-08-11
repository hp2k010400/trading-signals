"""
pairs_challenge_montecarlo_ftmo.py

Answers the real question on the table: could higher risk get this
pairs strategy (AUDCAD/AUDCHF, AUDNZD/AUDCHF, USDCHF/USDCAD -- the only
thing tonight that survived a genuine blind holdout) through an FTMO
challenge faster, and at what cost? Two things are tested together,
not separately, because both matter:

  1. RISK vs PASS RATE: does raising risk-per-trade actually get you
     through a challenge more often, or does it just get you disqualified
     faster via the daily/max loss limits?
  2. TRADE FREQUENCY vs TIME LIMIT: this strategy only fires ~4-5 times a
     year PER PAIR (real, not assumed) -- even with a real edge, there's
     a genuine question of whether enough trades even OCCUR within a
     30/60-day challenge window to reach the profit target before time
     runs out, independent of the risk/drawdown tradeoff.

METHOD: bootstrap the REAL historical trade sequence (entry times and
r_net outcomes, not an assumed distribution or assumed trade count).
For each simulation: pick a random start date, take whatever trades
ACTUALLY occurred in the following CHALLENGE_DAYS window (preserving
real clustering/frequency, not a smoothed assumption), simulate the
account day by day, and check FTMO-style rules:
  - Daily loss limit: 5% of that day's starting balance
  - Max total loss: 10% of initial balance (static, not trailing --
    adjust MAX_TOTAL_LOSS_PCT/convention if your specific account uses
    a different rule)
  - Profit target: 10% for a 30-day window (approximating Phase 1),
    5% for a 60-day window (approximating Phase 2) -- adjust to match
    your actual challenge's real rules, these are typical FTMO figures
    not a guarantee they match your specific account.

Each simulated window ends in exactly one of three outcomes: PASS
(hit target), FAIL-DAILY / FAIL-MAXLOSS (breached a risk limit), or
TIMEOUT (window ended with neither -- not enough edge/trades in time).
Reports all three separately, not just a single pass rate, because
"failed" and "ran out of time" are different problems.

Run in Codespace: python -u pairs_challenge_montecarlo_ftmo.py
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
BROKER_UTC_OFFSET_HOURS = 3

FILES = {
    'AUDNZD': 'AUDNZD_M1_ftmo.csv',
    'AUDCAD': 'AUDCAD_M1_ftmo.csv',
    'AUDCHF': 'AUDCHF_M1_ftmo.csv',
    'USDCHF': 'USDCHF_M1_ftmo.csv',
    'USDCAD': 'USDCAD_M1_ftmo.csv',
}
COST_POINTS = {
    'AUDNZD': 0.0004, 'AUDCAD': 0.0004, 'AUDCHF': 0.0004,
    'USDCHF': 0.00015, 'USDCAD': 0.00015,
}
# Only the 3 pairs that survived the blind holdout test
SURVIVOR_PAIRS = [('AUDCAD', 'AUDCHF'), ('AUDNZD', 'AUDCHF'), ('USDCHF', 'USDCAD')]

START_BAL = 70000.0
MAX_DAILY_LOSS_PCT = 0.05
MAX_TOTAL_LOSS_PCT = 0.10
CHALLENGE_CONFIGS = [
    (30, 0.10),   # (window_days, profit_target_pct) -- approximates FTMO Phase 1
    (60, 0.05),   # approximates FTMO Phase 2 -- ADJUST to match your real account's actual rules
]
RISK_LEVELS_PCT = [0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
N_SIMULATIONS = 3000

_daily = {}

def load_daily(symbol):
    fn = FILES[symbol]
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
    _daily[symbol] = daily
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
            state = {'direction': direction, 'entry_day': entry_idx, 'norm': norm,
                     'a_entry': da['open'].iloc[entry_idx], 'b_entry': db['open'].iloc[entry_idx]}
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


print('Loading FTMO daily data for the 3 surviving pairs...')
loaded = [s for s in FILES if load_daily(s)]
all_trades = []
for sym_a, sym_b in SURVIVOR_PAIRS:
    if sym_a not in loaded or sym_b not in loaded:
        print(f'  {sym_a}/{sym_b}: missing data, skipped')
        continue
    trades = simulate_pair(sym_a, sym_b)
    print(f'  {sym_a}/{sym_b}: {len(trades)} trades')
    all_trades.extend(trades)

trades_df = pd.DataFrame(all_trades)
if len(trades_df) == 0:
    raise SystemExit('No trades found -- check the 5 CSVs are present.')
trades_df = trades_df.sort_values('entry_time').reset_index(drop=True)
trades_df['date'] = trades_df['entry_time'].dt.normalize()
print(f'\nTotal real trades across the 3 survivor pairs: {len(trades_df)}')
print(f'Date range: {trades_df["entry_time"].min().date()} -> {trades_df["entry_time"].max().date()}')

data_start = trades_df['entry_time'].min()
data_end = trades_df['entry_time'].max()

rng = np.random.default_rng(42)


def simulate_window(window_days, profit_target_pct, risk_pct):
    max_start = data_end - pd.Timedelta(days=window_days)
    if max_start <= data_start:
        return None
    total_span_days = (max_start - data_start).days
    start_offset = rng.integers(0, total_span_days + 1)
    start_date = data_start + pd.Timedelta(days=int(start_offset))
    end_date = start_date + pd.Timedelta(days=window_days)

    window_trades = trades_df[(trades_df['entry_time'] >= start_date) & (trades_df['entry_time'] < end_date)]
    n_trades = len(window_trades)

    equity = START_BAL
    daily_start_balance = START_BAL
    current_day = None
    rpt = risk_pct / 100.0

    for _, row in window_trades.iterrows():
        if row['date'] != current_day:
            daily_start_balance = equity
            current_day = row['date']

        equity += equity * rpt * row['r_net']

        if (daily_start_balance - equity) / daily_start_balance >= MAX_DAILY_LOSS_PCT:
            return 'FAIL_DAILY', n_trades
        if (START_BAL - equity) / START_BAL >= MAX_TOTAL_LOSS_PCT:
            return 'FAIL_MAXLOSS', n_trades
        if (equity - START_BAL) / START_BAL >= profit_target_pct:
            return 'PASS', n_trades

    return 'TIMEOUT', n_trades


print(f'\n{"#"*100}')
print(f'  MONTE CARLO: {N_SIMULATIONS} simulated challenge windows per (window length, risk level)')
print(f'  Rules: {MAX_DAILY_LOSS_PCT*100:.0f}% max daily loss, {MAX_TOTAL_LOSS_PCT*100:.0f}% max total loss (static)')
print(f'{"#"*100}')

for window_days, profit_target_pct in CHALLENGE_CONFIGS:
    print(f'\n--- {window_days}-day window, {profit_target_pct*100:.0f}% profit target '
          f'(approximates FTMO {"Phase 1" if window_days == 30 else "Phase 2"} -- verify against your real account rules) ---')
    print(f'  {"Risk%":>6}  {"PASS":>7}  {"FAIL_DAILY":>10}  {"FAIL_MAXLOSS":>12}  {"TIMEOUT":>8}  {"AvgTrades":>9}')
    for risk_pct in RISK_LEVELS_PCT:
        outcomes = {'PASS': 0, 'FAIL_DAILY': 0, 'FAIL_MAXLOSS': 0, 'TIMEOUT': 0}
        trade_counts = []
        for _ in range(N_SIMULATIONS):
            result = simulate_window(window_days, profit_target_pct, risk_pct)
            if result is None:
                continue
            outcome, n_trades = result
            outcomes[outcome] += 1
            trade_counts.append(n_trades)
        total = sum(outcomes.values())
        if total == 0:
            print(f'  {risk_pct:>6.2f}  (no valid simulations -- window longer than available data span)')
            continue
        avg_trades = np.mean(trade_counts) if trade_counts else 0.0
        print(f'  {risk_pct:>6.2f}  {outcomes["PASS"]/total*100:>6.1f}%  {outcomes["FAIL_DAILY"]/total*100:>9.1f}%  '
              f'{outcomes["FAIL_MAXLOSS"]/total*100:>11.1f}%  {outcomes["TIMEOUT"]/total*100:>7.1f}%  {avg_trades:>9.2f}')

print('\nDone.')
