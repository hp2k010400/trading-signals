"""
news_breakout_ftmo.py

General news-volatility-breakout strategy: instead of one narrow
weekly NatGas report, trades EVERY high/moderate-impact economic
calendar event, mapped to whichever of our instruments shares that
event's currency (USD releases -> EURUSD/GBPUSD/USDJPY/USDCAD/
USDCHF/GOLD/indices, AUD releases -> AUDNZD/AUDCAD/AUDCHF, etc.).
Natural Gas Storage is special-cased to NATGAS only, regardless of
its currency tag, since it's a NATGAS-specific driver not a general
USD-macro one.

MECHANISM (pending-stop straddle, direction-agnostic):
  1. Just before each event, take the last known M1 close as the
     reference price and the most recent COMPLETE H1 ATR(14) (no
     lookahead) as the volatility unit.
  2. Set a breakout trigger BREAKOUT_ATR_MULT x ATR above and below
     the reference price -- like resting a buy-stop and a sell-stop
     on both sides before the release.
  3. Watch the WATCH_MINUTES after the event for either trigger to
     hit; first one wins (skip if genuinely ambiguous -- both hit in
     the same bar).
  4. From that fill: stop = ATR_STOP_MULT x ATR, target = stop x RR,
     time-stop at MAX_HOLD_HOURS.
  5. If neither trigger hits within the watch window, no trade.

CALENDAR TIMEZONE CONFIRMED (2026-08-11): Natural Gas Storage sample
timestamps from ExportHighImpactCalendar.mq5 (e.g. 2016.08.18 17:30
broker time) land on Thursdays, and minus the same 3h broker offset
used for M1 bars gives 14:30 UTC = 10:30am US Eastern (EDT) -- the
known real release time. Calendar events use the same broker-server
UTC+3 convention as price bars, so CALENDAR_UTC_OFFSET_HOURS matches
BROKER_UTC_OFFSET_HOURS.

Run in Codespace: python -u news_breakout_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3     # confirmed for M1 price bars (TimeCurrent()-TimeGMT())
CALENDAR_UTC_OFFSET_HOURS = 3   # confirmed 2026-08-11: Natural Gas Storage sample times
                                 # (e.g. 2016.08.18 17:30 broker time) minus 3h land on
                                 # 14:30 UTC = 10:30am US Eastern (EDT), the known real
                                 # release time -- same broker-server convention as M1 bars

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
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
    'NATGAS':0.008, 'UK100':1.8, 'AUDNZD':0.0004, 'AUDCAD':0.0004,
    'AUDCHF':0.0004, 'USDCHF':0.00015, 'USDCAD':0.00015,
}
# currency -> instruments that react to that currency's macro releases
CURRENCY_MAP = {
    'USD': ['EURUSD','GBPUSD','USDJPY','USDCAD','USDCHF','GOLD','NAS100','SP500','US30'],
    'EUR': ['EURUSD','DAX'],
    'GBP': ['GBPUSD','UK100'],
    'JPY': ['USDJPY'],
    'AUD': ['AUDNZD','AUDCAD','AUDCHF'],
    'NZD': ['AUDNZD'],
    'CAD': ['USDCAD','AUDCAD'],
    'CHF': ['USDCHF','AUDCHF'],
}

# Instruments now span up to ~4M M1 bars each (11 years for several of the
# lesser-traded FX crosses). Loading all 15 into memory at once was OOM-killed
# in the Codespace, so this processes ONE instrument's price data at a time --
# load, extract its trades, discard, move to the next -- instead of holding
# every instrument resident simultaneously. float32 (not the pandas default
# float64) roughly halves the per-file memory footprint too.

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
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)   # known BEFORE this bar, no lookahead
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
    n_before = len(df)
    # MT5's calendar stores multiple "revisions" of the same real-world event
    # (preliminary/revised/final figures) as separate rows, often with the
    # same or near-identical timestamp. Treating each as an independent trade
    # fires the "same" event multiple times and blows up compounded monthly
    # P&L (confirmed on the indices-only variant: one month showed +30,460%).
    df = df.drop_duplicates(subset=['currency', 'event_name', 'time'])
    n_after = len(df)
    if n_after < n_before:
        print(f'Dropped {n_before - n_after} duplicate calendar rows (same currency/event/time).')
    return df.sort_values('time').reset_index(drop=True)


def find_trade_for_event(symbol, m1, h1, event_time):
    m1_index = m1.index
    h1_index = h1.index

    # last complete H1 bar strictly before the event -> its ATR (no lookahead)
    h1_pos = h1_index.searchsorted(event_time) - 1
    if h1_pos < 0 or h1_pos >= len(h1):
        return None
    atr = h1.iloc[h1_pos]['atr']
    if pd.isna(atr) or atr <= 0:
        return None

    # reference price = last known M1 close before the event
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
            return None   # ambiguous same-bar hit, skip
        if hit_up:
            direction = 1; entry_price = trigger_up; entry_pos = m1_pos + k; break
        if hit_down:
            direction = -1; entry_price = trigger_down; entry_pos = m1_pos + k; break

    if direction == 0:
        return None   # no breakout within watch window

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


cal = load_calendar()
if cal is None:
    raise SystemExit(f'{CALENDAR_FILE} not found -- run ExportHighImpactCalendar.mq5 and upload it first.')
print(f'Loaded {len(cal)} calendar events (High/Moderate importance + Natural Gas Storage).\n')

# Pre-split the (small) calendar into a per-instrument event-time list so
# each instrument's price data can be loaded, used, and freed in turn.
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
n_events_used = 0
for symbol in FILES:
    ev_times = events_for_symbol.get(symbol, [])
    if not ev_times or not os.path.exists(FILES[symbol]):
        continue
    print(f'Processing {symbol}: {len(ev_times)} candidate events...')
    m1, h1 = load_price(symbol)
    if m1 is None:
        continue
    loaded.append(symbol)
    n_events_used += len(ev_times)
    for t in ev_times:
        trade = find_trade_for_event(symbol, m1, h1, t)
        if trade is not None:
            all_trades.append(trade)
    del m1, h1
    gc.collect()

print(f'\nLoaded {len(loaded)} instruments: {loaded}')
print(f'Candidate (event, instrument) pairs processed: {n_events_used}')

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

print('\nDone.')
