"""
london_monthly_contribution.py

How much does the London session specifically contribute, month by
month? Follow-up to ny_only_check.py, which showed London adds real
net profit overall (not dead weight) but didn't break it down by
month. This isolates London-only trades and walks through the real
calendar month by month, same approach as fair_price_monthly_pnl.py,
so the actual monthly contribution (not just an 8.5yr aggregate) is
visible.

Same locked live parameters: 0.10% displacement, RR=1.2, 0.30% risk,
real-spread costs at 1.5x. Each month simulated fresh from £70,000.

Run in Codespace: python -u london_monthly_contribution.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

MIN_DISPLACEMENT_PCT = 0.0010
RISK_PCT = 0.30
COST_MULT = 1.5
START_BAL = 70000.0
RR = 1.2
REVERSION_WINDOW_MIN = 90
MAX_HOLD_MIN = 240
LONDON_HOUR = 8

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


print('Loading OANDA M1 data...')
loaded = [s for s in FILES if load(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

all_trades = []
for symbol in loaded:
    all_trades.extend(find_reversion_trades(symbol, LONDON_HOUR))

df = pd.DataFrame(all_trades)
print(f'Total LONDON-only trades: {len(df)}\n')

df['month'] = df['entry_time'].dt.to_period('M')
rpt = RISK_PCT / 100.0

rows = []
for month, g in df.groupby('month'):
    equity = START_BAL
    for r in g.sort_values('entry_time')['r_net']:
        equity += equity * rpt * r
    pnl = equity - START_BAL
    pnl_pct = pnl / START_BAL * 100
    rows.append({'month': str(month), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl_pct})

monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
print(f'Months with London trading activity: {len(monthly)}\n')

print(f'{"="*70}')
print(f'  LONDON-ONLY MONTHLY CONTRIBUTION (each month simulated fresh from £70,000)')
print(f'{"="*70}')
print(f'  Best month:    {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  '
      f'£{monthly["pnl_gbp"].max():>+10,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
print(f'  Worst month:   {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  '
      f'£{monthly["pnl_gbp"].min():>+10,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
print(f'  Median month:  £{monthly["pnl_gbp"].median():>+10,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
print(f'  Mean month:    £{monthly["pnl_gbp"].mean():>+10,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

print(f'\n  Full month-by-month (London-only, year-month, £pnl, %, trades):')
for _, r in monthly.iterrows():
    print(f'    {r["month"]}  £{r["pnl_gbp"]:>+9,.0f}  {r["pnl_pct"]:>+6.2f}%  N={r["trades"]:.0f}')

print('\nDone.')
