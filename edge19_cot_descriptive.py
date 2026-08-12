"""
edge19_cot_descriptive.py

Gate 1 descriptive test for Edge #1 (E19): does CFTC commercial net
positioning in S&P 500 futures predict forward S&P 500 index returns?
Pre-registered in EDGE19_HYPOTHESIS.md BEFORE this script was run.

DESCRIPTIVE ONLY. Pulls real data directly (both CFTC's public Socrata
API and Yahoo Finance's public chart API are reachable from this
environment) -- no synthetic smoke test needed, this runs on the real
thing from the start since both sources are free, public, and network-
reachable here.

No lookahead: signal_available_date = report_date + 3 calendar days
(CFTC's real publish lag), forward returns measured from the first
trading day at or after that date.
"""
import urllib.request
import urllib.parse
import json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

COT_MARKET = 'S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE'
ZSCORE_WINDOW_WEEKS = 156
PUBLISH_LAG_DAYS = 3
HORIZONS_WEEKS = [1, 2, 4]


def fetch_cot():
    base = 'https://publicreporting.cftc.gov/resource/jun7-fc8e.json'
    params = {
        '$where': f"market_and_exchange_names = '{COT_MARKET}'",
        '$order': 'report_date_as_yyyy_mm_dd ASC',
        '$limit': '5000',
        '$select': 'report_date_as_yyyy_mm_dd,comm_positions_long_all,comm_positions_short_all,open_interest_all',
    }
    url = base + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'edge-research'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    df = pd.DataFrame(data)
    df['report_date'] = pd.to_datetime(df['report_date_as_yyyy_mm_dd']).dt.tz_localize('UTC')
    for c in ['comm_positions_long_all', 'comm_positions_short_all', 'open_interest_all']:
        df[c] = df[c].astype(float)
    df = df.sort_values('report_date').reset_index(drop=True)
    return df[['report_date', 'comm_positions_long_all', 'comm_positions_short_all', 'open_interest_all']]


def fetch_sp500():
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC'
           '?period1=1136073600&period2=1893456000&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    result = data['chart']['result'][0]
    ts = result['timestamp']
    closes = result['indicators']['quote'][0]['close']
    df = pd.DataFrame({'time': pd.to_datetime(ts, unit='s', utc=True), 'close': closes})
    df = df.dropna().sort_values('time').reset_index(drop=True)
    return df


print('Fetching CFTC COT data (S&P 500 Consolidated)...')
cot = fetch_cot()
print(f'  {len(cot)} weekly reports, {cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}')

print('Fetching S&P 500 daily price data (Yahoo Finance)...')
px = fetch_sp500()
print(f'  {len(px)} daily bars, {px["time"].iloc[0].date()} -> {px["time"].iloc[-1].date()}')

# ---- signal construction ----
cot['net_comm_frac'] = (cot['comm_positions_long_all'] - cot['comm_positions_short_all']) / cot['open_interest_all']
cot['z'] = (cot['net_comm_frac'] - cot['net_comm_frac'].rolling(ZSCORE_WINDOW_WEEKS).mean()) / \
           cot['net_comm_frac'].rolling(ZSCORE_WINDOW_WEEKS).std()
cot = cot.dropna(subset=['z']).reset_index(drop=True)
print(f'\nAfter {ZSCORE_WINDOW_WEEKS}-week z-score warmup: {len(cot)} usable signal observations, '
      f'{cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}')

cot['signal_available_date'] = cot['report_date'] + pd.Timedelta(days=PUBLISH_LAG_DAYS)

px_idx = px['time'].values
px_close = px['close'].values


def price_on_or_after(target_ts):
    pos = np.searchsorted(px_idx, np.datetime64(target_ts))
    if pos >= len(px_idx):
        return np.nan
    return px_close[pos]


def price_pos_on_or_after(target_ts):
    pos = np.searchsorted(px_idx, np.datetime64(target_ts))
    if pos >= len(px_idx):
        return -1
    return pos


rows = []
for _, r in cot.iterrows():
    entry_pos = price_pos_on_or_after(r['signal_available_date'])
    if entry_pos < 0:
        continue
    entry_price = px_close[entry_pos]
    rec = {'report_date': r['report_date'], 'signal_available_date': r['signal_available_date'], 'z': r['z']}
    ok = True
    for h in HORIZONS_WEEKS:
        target = r['signal_available_date'] + pd.Timedelta(weeks=h)
        exit_pos = price_pos_on_or_after(target)
        if exit_pos < 0 or exit_pos <= entry_pos:
            ok = False
            break
        rec[f'fwd_ret_{h}w'] = np.log(px_close[exit_pos] / entry_price)
    if ok:
        rows.append(rec)

df = pd.DataFrame(rows)
print(f'\nUsable paired observations (signal + all 3 forward horizons available): {len(df)}')


def report_case(label, z, fwd):
    n = len(z)
    if n < 20:
        print(f'  {label}: N={n} too few')
        return
    corr = np.corrcoef(z, fwd)[0, 1]
    order = np.argsort(z)
    q = max(1, n // 5)
    bottom = fwd[order[:q]].mean() * 10000
    top = fwd[order[-q:]].mean() * 10000
    print(f'  {label:<12} N={n:>4}  corr={corr:>+7.4f}  bottom20%={bottom:>+8.2f}bp  '
          f'top20%={top:>+8.2f}bp  spread={top-bottom:>+8.2f}bp')


print(f'\n{"="*90}\n  FULL HISTORY: net_comm z-score -> forward S&P 500 return\n{"="*90}')
for h in HORIZONS_WEEKS:
    report_case(f'{h}-week fwd', df['z'].values, df[f'fwd_ret_{h}w'].values)

print(f'\n{"="*90}\n  BY PERIOD (Discovery / Validation / Final-OOS), 4-week horizon\n{"="*90}')
n = len(df)
df_sorted = df.sort_values('report_date').reset_index(drop=True)
disc_end = df_sorted['report_date'].iloc[int(n * 0.50)]
val_end = df_sorted['report_date'].iloc[int(n * 0.75)]
print(f'  Discovery:  {df_sorted["report_date"].iloc[0].date()} -> {disc_end.date()}')
print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
print(f'  Final OOS:  {val_end.date()} -> {df_sorted["report_date"].iloc[-1].date()}\n')

for label, mask in [('DISCOVERY', df_sorted['report_date'] < disc_end),
                     ('VALIDATION', (df_sorted['report_date'] >= disc_end) & (df_sorted['report_date'] < val_end)),
                     ('FINAL OOS', df_sorted['report_date'] >= val_end)]:
    sub = df_sorted[mask]
    report_case(label, sub['z'].values, sub['fwd_ret_4w'].values)

print('\nDone.')
