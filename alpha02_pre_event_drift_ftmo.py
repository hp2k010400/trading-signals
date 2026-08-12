"""
alpha02_pre_event_drift_ftmo.py

Phenomenon #2 from ALPHA_CANDIDATES.md. Descriptive measurement, not a
strategy: does price drift in a consistent direction in the hours
BEFORE a scheduled high-impact economic event, before the event
itself has even happened? This is mechanistically distinct from
news_breakout_ftmo.py (already tested/rejected), which measured the
INSTANT reaction to the release. This measures pre-positioning drift
in the window leading up to it.

BACKGROUND: Lucca & Moench (2015) found pre-FOMC drift (the 24h window
before FOMC announcements) accounted for ~80% of annual US equity
excess returns 1994-2011. More recent research ("The Disappearing
Pre-FOMC Announcement Drift") finds this has weakened, especially for
announcements without press conferences -- an honest headwind stated
up front.

METHOD: for every high-impact calendar event (reusing the same
HighImpactCalendar.csv already collected), for each instrument mapped
to that event's currency (same currency-mapping logic as
news_breakout_ftmo.py, reused because it's a legitimate, independent-
of-profitability way to decide which instruments plausibly react to
which currency, not itself a strategy claim):
  drift_return = log(price at event_time / price at event_time - PRE_WINDOW_HOURS)
This measures whether there's a systematic directional pull in the
PRE_WINDOW_HOURS before the release -- no trade, no direction call, no
stop/target. If a real, stable drift exists (positive or negative,
doesn't matter which), that's the signal worth building a strategy
around. If it's centered on zero, that's reported honestly.

Splits into discovery/validation/final-OOS by calendar time.

Run in Codespace: python -u alpha02_pre_event_drift_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
CALENDAR_UTC_OFFSET_HOURS = 3   # confirmed same convention as price bars, see earlier research
PRE_WINDOW_HOURS = 24
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
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'USDCHF':'USDCHF_M1_ftmo.csv',
    'USDCAD':'USDCAD_M1_ftmo.csv',
    'AUDCAD':'AUDCAD_M1_ftmo.csv',
    'AUDNZD':'AUDNZD_M1_ftmo.csv',
}
CURRENCY_MAP = {
    'USD': ['NAS100','SP500','US30','US2000','DAX','UK100','FRA40','EU50','JP225','AUS200','HK50'],
    'EUR': ['DAX','FRA40','EU50'],
    'GBP': ['UK100'],
    'JPY': ['JP225'],
    'AUD': ['AUS200','AUDCAD','AUDNZD'],
}


def load_m1(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    return df.dropna()


def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        return None
    df = pd.read_csv(CALENDAR_FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=CALENDAR_UTC_OFFSET_HOURS)
    df = df.drop_duplicates(subset=['currency', 'event_name', 'time'])
    return df.sort_values('time').reset_index(drop=True)


cal = load_calendar()
if cal is None:
    raise SystemExit(f'{CALENDAR_FILE} not found -- upload it first (same file used by news_breakout_ftmo.py).')
print(f'Loaded {len(cal)} calendar events.\n')

events_for_symbol = {s: [] for s in FILES}
for currency, symbols in CURRENCY_MAP.items():
    times = list(cal[cal['currency'] == currency]['time'])
    for s in symbols:
        events_for_symbol[s].extend(times)

all_drifts = []
loaded = []
for symbol in FILES:
    ev_times = events_for_symbol.get(symbol, [])
    if not ev_times or not os.path.exists(FILES[symbol]):
        continue
    m1 = load_m1(symbol)
    if m1 is None:
        continue
    loaded.append(symbol)
    idx = m1.index
    for t in ev_times:
        pre_time = t - pd.Timedelta(hours=PRE_WINDOW_HOURS)
        pre_pos = idx.searchsorted(pre_time)
        event_pos = idx.searchsorted(t)
        if pre_pos <= 0 or event_pos >= len(m1) or pre_pos >= event_pos:
            continue
        price_before = float(m1['close'].iloc[pre_pos])
        price_at_event = float(m1['close'].iloc[event_pos - 1])   # last known price BEFORE the event itself
        if price_before <= 0:
            continue
        drift = np.log(price_at_event / price_before)
        all_drifts.append({'symbol': symbol, 'event_time': t, 'drift': drift})
    del m1
    gc.collect()

drifts = pd.DataFrame(all_drifts)
if len(drifts) == 0:
    raise SystemExit('No pre-event drift observations generated -- check calendar/price CSVs are present.')
drifts = drifts.sort_values('event_time').reset_index(drop=True)
print(f'Loaded {len(loaded)} instruments: {loaded}')
print(f'Total pre-event drift observations: {len(drifts)}\n')


def measure(sub):
    if len(sub) == 0:
        return dict(N=0, mean=0.0, total=0.0, sharpe=0.0, wr=0.0)
    mean = sub.mean(); total = sub.sum()
    sharpe = mean / sub.std() if sub.std() > 0 else 0.0
    wr = (sub > 0).mean() * 100
    return dict(N=len(sub), mean=mean, total=total, sharpe=sharpe, wr=wr)


def print_measure(label, m):
    print(f'  {label:<20}  N={m["N"]:>6}  mean={m["mean"]*10000:>+8.2f}bp  '
          f'total={m["total"]:>+8.4f}  sharpe={m["sharpe"]:>+7.4f}  %positive={m["wr"]:>5.1f}%')


dates = drifts['event_time'].sort_values()
n = len(dates)
disc_end = dates.iloc[int(n * 0.50)]
val_end = dates.iloc[int(n * 0.75)]
print(f'Discovery period:  {dates.iloc[0].date()} -> {disc_end.date()}')
print(f'Validation period: {disc_end.date()} -> {val_end.date()}')
print(f'Final OOS period:  {val_end.date()} -> {dates.iloc[-1].date()}\n')

periods = {
    'DISCOVERY': drifts[drifts['event_time'] < disc_end],
    'VALIDATION': drifts[(drifts['event_time'] >= disc_end) & (drifts['event_time'] < val_end)],
    'FINAL OOS': drifts[drifts['event_time'] >= val_end],
}
for period_name, pdf in periods.items():
    print(f'\n{"="*90}\n  {period_name}  (N={len(pdf)})\n{"="*90}')
    print_measure(f'Pre-event drift ({PRE_WINDOW_HOURS}h)', measure(pdf['drift']))

print(f'\n{"="*90}\n  BY INSTRUMENT (full history)\n{"="*90}')
for symbol in loaded:
    m = measure(drifts[drifts['symbol'] == symbol]['drift'])
    print_measure(symbol, m)

print('\nDone. No trading rule applied yet -- this is a measurement of the raw phenomenon only.')
