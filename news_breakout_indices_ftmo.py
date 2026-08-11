"""
news_breakout_indices_ftmo.py

Isolation test of news_breakout_ftmo.py's real finding: every equity
index was profitable (DAX PF 1.99, UK100 PF 2.19, US30 PF 1.25, NAS100
PF 1.14, SP500 PF 1.05) while every FX pair and Gold was losing (PF
0.40-0.92) in the blended run. That's not noise -- indices show
sustained post-news momentum (institutional repositioning takes hours),
while FX is efficient/fast enough that our ATR-based straddle often
chases a move that's already priced in.

This restricts the exact same mechanism to ONLY the instruments that
showed a real signal (DAX, NAS100, SP500, US30, UK100, NATGAS), so the
walk-forward windows reflect the isolated edge instead of being dragged
by the FX/Gold losers. The blended full-period per-instrument numbers
don't tell us whether the index edge was consistent over time or
front/back-loaded -- this does.

Same mechanism, same currency mapping, same confirmed UTC+3 (price)
and UTC+3 (calendar) offsets as news_breakout_ftmo.py.

Run in Codespace: python -u news_breakout_indices_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
CALENDAR_UTC_OFFSET_HOURS = 3

BREAKOUT_ATR_MULT = 0.5
ATR_STOP_MULT = 1.0
RR = 1.5
COST_MULT = 1.5
WATCH_MINUTES = 30
MAX_HOLD_HOURS = 4
ATR_PERIOD = 14
WALK_FORWARD_MONTHS = 6

CALENDAR_FILE = 'HighImpactCalendar.csv'

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'NATGAS':'NATGAS_cash_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0, 'UK100':1.8, 'NATGAS':0.008,
}
CURRENCY_MAP = {
    'USD': ['NAS100','SP500','US30'],
    'EUR': ['DAX'],
    'GBP': ['UK100'],
}

def load_price(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None, None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    prev_close = h1['close'].shift(1)
    tr = pd.concat([h1['high']-h1['low'], (h1['high']-prev_close).abs(), (h1['low']-prev_close).abs()], axis=1).max(axis=1)
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    h1 = h1.dropna()
    return df, h1


def is_gas_storage(name):
    n = str(name).upper()
    return ('NATURAL GAS' in n) or ('GAS STORAGE' in n)


def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        return None
    df = pd.read_csv(CALENDAR_FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=CALENDAR_UTC_OFFSET_HOURS)
    return df.sort_values('time').reset_index(drop=True)


def find_trade_for_event(symbol, m1, h1, event_time):
    m1_index = m1.index
    h1_index = h1.index

    h1_pos = h1_index.searchsorted(event_time) - 1
    if h1_pos < 0 or h1_pos >= len(h1):
        return None
    atr = h1.iloc[h1_pos]['atr']
    if pd.isna(atr) or atr <= 0:
        return None

    m1_pos = m1_index.searchsorted(event_time)
    if m1_pos <= 0 or m1_pos >= len(m1):
        return None
    ref_price = float(m1['close'].iloc[m1_pos - 1])

    trigger_up = ref_price + BREAKOUT_ATR_MULT * atr
    trigger_down = ref_price - BREAKOUT_ATR_MULT * atr

    watch_end = min(m1_pos + WATCH_MINUTES, len(m1))
    watch = m1.iloc[m1_pos:watch_end]
    if len(watch) == 0:
        return None

    direction = 0
    entry_price = None
    entry_pos = None
    highs = watch['high'].values; lows = watch['low'].values
    for k in range(len(watch)):
        hit_up = highs[k] >= trigger_up
        hit_down = lows[k] <= trigger_down
        if hit_up and hit_down:
            return None
        if hit_up:
            direction = 1; entry_price = trigger_up; entry_pos = m1_pos + k; break
        if hit_down:
            direction = -1; entry_price = trigger_down; entry_pos = m1_pos + k; break

    if direction == 0:
        return None

    stop_dist = ATR_STOP_MULT * atr
    stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
    tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

    window_end = min(entry_pos + 1 + MAX_HOLD_HOURS * 60, len(m1))
    future = m1.iloc[entry_pos + 1: window_end]
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
    else:
        r_gross = -1.0

    cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
    return {'symbol': symbol, 'entry_time': m1_index[entry_pos], 'r_net': r_gross - cost_r}


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


RISK_PCT = 0.30
START_BAL = 70000.0

cal = load_calendar()
if cal is None:
    raise SystemExit(f'{CALENDAR_FILE} not found -- upload it first.')
print(f'Loaded {len(cal)} calendar events.\n')

cal_gas = cal[cal['event_name'].apply(is_gas_storage)]
cal_macro = cal[~cal['event_name'].apply(is_gas_storage)]

events_for_symbol = {s: [] for s in FILES}
events_for_symbol['NATGAS'] = list(cal_gas['time'])
for currency, symbols in CURRENCY_MAP.items():
    times = list(cal_macro[cal_macro['currency'] == currency]['time'])
    for s in symbols:
        events_for_symbol[s].extend(times)

all_trades = []
loaded = []
for symbol in FILES:
    ev_times = events_for_symbol.get(symbol, [])
    if not ev_times or not os.path.exists(FILES[symbol]):
        continue
    print(f'Processing {symbol}: {len(ev_times)} candidate events...')
    m1, h1 = load_price(symbol)
    if m1 is None:
        continue
    loaded.append(symbol)
    for t in ev_times:
        trade = find_trade_for_event(symbol, m1, h1, t)
        if trade is not None:
            all_trades.append(trade)
    del m1, h1
    gc.collect()

print(f'\nLoaded {len(loaded)} instruments: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print_row('OVERALL', n, wr, pf, tot)

if len(df) > 0:
    print(f'\n{"#"*90}')
    print(f'  WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    print(f'{"#"*90}')
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        window_rv = df[df['period'].isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    print(f'\n  Per-instrument:')
    for symbol in loaded:
        rv = df[df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {symbol}', n2, wr2, pf2, tot2)

    # Real monthly P&L, each month fresh from £70,000 at 0.30% risk
    print(f'\n{"#"*90}')
    print(f'  MONTHLY P&L (each month simulated fresh from £70,000 at {RISK_PCT}% risk)')
    print(f'{"#"*90}')
    rpt = RISK_PCT / 100.0
    rows = []
    for period, g in df.groupby('period'):
        equity = START_BAL
        for r in g.sort_values('entry_time')['r_net']:
            equity += equity * rpt * r
        pnl = equity - START_BAL
        rows.append({'month': str(period), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl / START_BAL * 100})
    monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
    print(f'  Months with activity: {len(monthly)}')
    print(f'  Best month:   {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  £{monthly["pnl_gbp"].max():>+9,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
    print(f'  Worst month:  {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  £{monthly["pnl_gbp"].min():>+9,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
    print(f'  Median month: £{monthly["pnl_gbp"].median():>+9,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
    print(f'  Mean month:   £{monthly["pnl_gbp"].mean():>+9,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
    pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
    print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

print('\nDone.')
