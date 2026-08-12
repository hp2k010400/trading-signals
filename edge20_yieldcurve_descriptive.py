"""
edge20_yieldcurve_descriptive.py

Gate 1 descriptive test for Edge #2 (E20): does the T10Y3M yield curve
slope predict forward S&P 500 returns? Pre-registered in
EDGE20_HYPOTHESIS.md BEFORE this script was run.

Predicted direction (locked in advance): NEGATIVE correlation is wrong;
correctly stated: POSITIVE correlation between T10Y3M z-score and
forward return (steep curve = bullish, flat/inverted = bearish).

DESCRIPTIVE ONLY. Real data (FRED CSV export + Yahoo Finance), both
reachable directly from this environment.
"""
import urllib.request
import json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_DAYS = 756
PUBLISH_LAG_BDAYS = 1
HORIZONS_WEEKS = [1, 2, 4]


def fetch_fred(series_id):
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    text = resp.read().decode()
    lines = text.strip().split('\n')
    rows = [l.split(',') for l in lines[1:]]
    df = pd.DataFrame(rows, columns=['date', series_id])
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize('UTC')
    df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
    df = df.dropna().sort_values('date').reset_index(drop=True)
    return df


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


print('Fetching T10Y3M from FRED...')
yc = fetch_fred('T10Y3M')
print(f'  {len(yc)} daily observations, {yc["date"].iloc[0].date()} -> {yc["date"].iloc[-1].date()}')

print('Fetching S&P 500 daily price data (Yahoo Finance)...')
px = fetch_sp500()
print(f'  {len(px)} daily bars, {px["time"].iloc[0].date()} -> {px["time"].iloc[-1].date()}')

yc['z'] = (yc['T10Y3M'] - yc['T10Y3M'].rolling(ZSCORE_WINDOW_DAYS).mean()) / \
          yc['T10Y3M'].rolling(ZSCORE_WINDOW_DAYS).std()
yc = yc.dropna(subset=['z']).reset_index(drop=True)
print(f'\nAfter {ZSCORE_WINDOW_DAYS}-day z-score warmup: {len(yc)} usable signal observations, '
      f'{yc["date"].iloc[0].date()} -> {yc["date"].iloc[-1].date()}')

yc['signal_available_date'] = yc['date'] + pd.Timedelta(days=PUBLISH_LAG_BDAYS)

px_idx = px['time'].values
px_close = px['close'].values


def pos_on_or_after(target_ts):
    pos = np.searchsorted(px_idx, np.datetime64(target_ts))
    return pos if pos < len(px_idx) else -1


rows = []
for _, r in yc.iterrows():
    entry_pos = pos_on_or_after(r['signal_available_date'])
    if entry_pos < 0:
        continue
    entry_price = px_close[entry_pos]
    rec = {'date': r['date'], 'signal_available_date': r['signal_available_date'], 'z': r['z']}
    ok = True
    for h in HORIZONS_WEEKS:
        target = r['signal_available_date'] + pd.Timedelta(weeks=h)
        exit_pos = pos_on_or_after(target)
        if exit_pos < 0 or exit_pos <= entry_pos:
            ok = False
            break
        rec[f'fwd_ret_{h}w'] = np.log(px_close[exit_pos] / entry_price)
    if ok:
        rows.append(rec)

df = pd.DataFrame(rows)
print(f'\nUsable paired observations: {len(df)}')


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
    print(f'  {label:<12} N={n:>5}  corr={corr:>+7.4f}  bottom20%={bottom:>+8.2f}bp  '
          f'top20%={top:>+8.2f}bp  spread={top-bottom:>+8.2f}bp')


print(f'\n{"="*90}\n  FULL HISTORY: T10Y3M z-score -> forward S&P 500 return\n{"="*90}')
print('  (predicted: POSITIVE correlation -- steep curve bullish)')
for h in HORIZONS_WEEKS:
    report_case(f'{h}-week fwd', df['z'].values, df[f'fwd_ret_{h}w'].values)

print(f'\n{"="*90}\n  BY PERIOD (Discovery / Validation / Final-OOS), 4-week horizon\n{"="*90}')
n = len(df)
df_sorted = df.sort_values('date').reset_index(drop=True)
disc_end = df_sorted['date'].iloc[int(n * 0.50)]
val_end = df_sorted['date'].iloc[int(n * 0.75)]
print(f'  Discovery:  {df_sorted["date"].iloc[0].date()} -> {disc_end.date()}')
print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
print(f'  Final OOS:  {val_end.date()} -> {df_sorted["date"].iloc[-1].date()}\n')

for label, mask in [('DISCOVERY', df_sorted['date'] < disc_end),
                     ('VALIDATION', (df_sorted['date'] >= disc_end) & (df_sorted['date'] < val_end)),
                     ('FINAL OOS', df_sorted['date'] >= val_end)]:
    sub = df_sorted[mask]
    report_case(label, sub['z'].values, sub['fwd_ret_4w'].values)

print('\nDone.')
