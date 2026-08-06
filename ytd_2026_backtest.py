"""
ytd_2026_backtest.py

2026 year-to-date backtest (2026-01-01 -> 2026-08-06), using the exact
same locked, validated logic as the live EA (0.10% displacement,
NY+London, RR=1.2, real-spread costs at 1.5x). Reports overall stats,
month-by-month breakdown within the period, and £ P&L at the live
0.30% risk setting -- same approach as every other validated script
tonight, just sliced to this specific window.

Run in Codespace: python -u ytd_2026_backtest.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RR = 1.2
COST_MULT = 1.5
RISK_PCT = 0.30
START_BAL = 70000.0
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
YTD_START = pd.Timestamp('2026-01-01', tz='UTC')
YTD_END   = pd.Timestamp('2026-08-06', tz='UTC') + pd.Timedelta(days=1)

SESSIONS = {'LONDON': 8, 'NY': 13}

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
}

_m1 = {}

def load(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[symbol] = df.dropna()
    return True


def simulate_forward(m1, m1_index, entry_index, direction, entry_price, stop_price, tp_price, max_minutes):
    window_end = min(entry_index + 1 + max_minutes, len(m1))
    future = m1.iloc[entry_index + 1: window_end]
    if len(future) == 0:
        return -1.0
    highs = future['high'].values
    lows  = future['low'].values
    closes = future['close'].values
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return 0.0
    for k in range(len(future)):
        if direction == 1:
            if highs[k] >= tp_price: return RR
            if lows[k] <= stop_price: return -1.0
        else:
            if lows[k] <= tp_price: return RR
            if highs[k] >= stop_price: return -1.0
    final_close = closes[-1]
    return ((final_close - entry_price) / stop_distance if direction == 1
            else (entry_price - final_close) / stop_distance)


def find_reversion_trades(symbol, session_hour):
    m1 = _m1[symbol]
    m1_index = m1.index
    days = pd.date_range(m1_index.min().normalize(), m1_index.max().normalize(), freq='D')
    trades = []
    for day in days:
        if day.dayofweek >= 5:
            continue
        session_start = day + pd.Timedelta(hours=session_hour)
        rev_start = session_start + pd.Timedelta(minutes=5)
        rev_end = session_start + pd.Timedelta(minutes=REVERSION_WINDOW_MIN)
        rev_window = m1[(m1_index >= rev_start - pd.Timedelta(minutes=1)) & (m1_index < rev_end)]
        if len(rev_window) < 3:
            continue
        bodies = (rev_window['close'] - rev_window['open']).values
        opens = rev_window['open'].values
        closes = rev_window['close'].values
        highs = rev_window['high'].values
        lows = rev_window['low'].values
        idx_labels = rev_window.index
        busy_until = None
        for i in range(1, len(rev_window)):
            ts = idx_labels[i]
            if busy_until is not None and ts < busy_until:
                continue
            if ts < rev_start:
                continue
            body_cur = abs(bodies[i]); body_prev = abs(bodies[i-1])
            if body_cur <= body_prev:
                continue
            px = float(closes[i])
            if px <= 0 or body_cur / px < MIN_DISPLACEMENT_PCT:
                continue
            direction = 1 if closes[i] > opens[i] else (-1 if closes[i] < opens[i] else 0)
            if direction == 0:
                continue
            entry_price = float(closes[i])
            stop_price = float(lows[i]) if direction == 1 else float(highs[i])
            stop_dist = abs(entry_price - stop_price)
            if stop_dist <= 0:
                continue
            entry_ts = idx_labels[i]
            entry_idx = m1_index.searchsorted(entry_ts)
            if entry_idx >= len(m1) - 1:
                continue
            entry_idx += 1
            entry_price = float(m1['open'].iloc[entry_idx])
            if abs(entry_price - stop_price) <= 0:
                continue
            tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR
            r_gross = simulate_forward(m1, m1_index, entry_idx, direction, entry_price,
                                        stop_price, tp_price, MAX_HOLD_MIN)
            cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
            trades.append({'symbol': symbol, 'entry_time': m1_index[entry_idx], 'r_net': r_gross - cost_r})
            busy_until = m1_index[entry_idx] + pd.Timedelta(minutes=1)
    return trades


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for session_name, session_hour in SESSIONS.items():
    for symbol in loaded:
        all_trades.extend(find_reversion_trades(symbol, session_hour))

df = pd.DataFrame(all_trades)
df_ytd = df[(df['entry_time'] >= YTD_START) & (df['entry_time'] < YTD_END)].sort_values('entry_time').reset_index(drop=True)

print(f'{"="*80}')
print(f'  2026 YEAR-TO-DATE (2026-01-01 -> 2026-08-06)')
print(f'{"="*80}')
n, wr, pf, tot = compute_stats(df_ytd['r_net'].values)
print(f'  Total trades: {n}   WR: {wr}%   PF: {pf}   Total R: {tot:+.1f}\n')

# ============================================================
#  Monthly breakdown within the YTD window (each month fresh from £70k)
# ============================================================
df_ytd['month'] = df_ytd['entry_time'].dt.to_period('M')
rpt = RISK_PCT / 100.0
rows = []
for month, g in df_ytd.groupby('month'):
    equity = START_BAL
    for r in g.sort_values('entry_time')['r_net']:
        equity += equity * rpt * r
    pnl = equity - START_BAL
    pnl_pct = pnl / START_BAL * 100
    rows.append({'month': str(month), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl_pct})

monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
print(f'{"#"*90}')
print(f'  MONTH-BY-MONTH (each month simulated fresh from £70,000 at live 0.30% risk)')
print(f'{"#"*90}')
for _, r in monthly.iterrows():
    print(f'  {r["month"]}  £{r["pnl_gbp"]:>+9,.0f}  {r["pnl_pct"]:>+6.2f}%  N={r["trades"]:.0f} trades')

print(f'\n  Total 2026 YTD £ (months summed independently): £{monthly["pnl_gbp"].sum():>+,.0f}')
print(f'  Average month: £{monthly["pnl_gbp"].mean():>+,.0f}   Median month: £{monthly["pnl_gbp"].median():>+,.0f}')

print('\nDone.')
