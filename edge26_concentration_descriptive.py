"""
edge26_concentration_descriptive.py

Gate 1 descriptive test for Edge #8 (E26): does top-4 trader gross
concentration in S&P 500 futures predict forward REALIZED VOLATILITY
(not direction)? Pre-registered in EDGE26_HYPOTHESIS.md.

Predicted direction: POSITIVE (higher concentration -> higher subsequent
realized vol).
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
        '$select': 'report_date_as_yyyy_mm_dd,conc_gross_le_4_tdr_long,conc_gross_le_4_tdr_short',
    }
    url = base + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'edge-research'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    df = pd.DataFrame(data)
    df['report_date'] = pd.to_datetime(df['report_date_as_yyyy_mm_dd']).dt.tz_localize('UTC')
    for c in ['conc_gross_le_4_tdr_long', 'conc_gross_le_4_tdr_short']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.dropna().sort_values('report_date').reset_index(drop=True)


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
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    return df


print('Fetching CFTC COT (concentration) + S&P 500 prices...')
cot = fetch_cot()
px = fetch_sp500()
print(f'  COT: {len(cot)} weekly reports, {cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}')
print(f'  Price: {len(px)} daily bars')

cot['concentration'] = cot['conc_gross_le_4_tdr_long'] + cot['conc_gross_le_4_tdr_short']
cot['z'] = (cot['concentration'] - cot['concentration'].rolling(ZSCORE_WINDOW_WEEKS).mean()) / \
           cot['concentration'].rolling(ZSCORE_WINDOW_WEEKS).std()
cot = cot.dropna(subset=['z']).reset_index(drop=True)
print(f'\nAfter {ZSCORE_WINDOW_WEEKS}-week z-score warmup: {len(cot)} usable signals, '
      f'{cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}')

cot['signal_available_date'] = cot['report_date'] + pd.Timedelta(days=PUBLISH_LAG_DAYS)
px_idx = px['time'].values


def pos_on_or_after(t):
    p = np.searchsorted(px_idx, np.datetime64(t))
    return p if p < len(px_idx) else -1


rows = []
for _, r in cot.iterrows():
    ep = pos_on_or_after(r['signal_available_date'])
    if ep < 0:
        continue
    rec = {'report_date': r['report_date'], 'z': r['z']}
    ok = True
    for h in HORIZONS_WEEKS:
        target = r['signal_available_date'] + pd.Timedelta(weeks=h)
        xp = pos_on_or_after(target)
        if xp < 0 or xp <= ep:
            ok = False
            break
        window_rets = px['ret'].iloc[ep + 1:xp + 1]
        if len(window_rets) < 3:
            ok = False
            break
        rec[f'fwd_vol_{h}w'] = window_rets.std()
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
    print(f'  {label:<12} N={n:>4}  corr={corr:>+7.4f}  bottom20%_vol={bottom:>8.2f}bp  '
          f'top20%_vol={top:>8.2f}bp  spread={top-bottom:>+8.2f}bp')


print(f'\n{"="*90}\n  FULL HISTORY: concentration z-score -> forward S&P 500 REALIZED VOLATILITY\n{"="*90}')
print('  (predicted: POSITIVE correlation -- higher concentration -> higher vol)')
for h in HORIZONS_WEEKS:
    report_case(f'{h}-week fwd', df['z'].values, df[f'fwd_vol_{h}w'].values)

n = len(df)
df_sorted = df.sort_values('report_date').reset_index(drop=True)
disc_end = df_sorted['report_date'].iloc[int(n * 0.50)]
val_end = df_sorted['report_date'].iloc[int(n * 0.75)]
print(f'\n{"="*90}\n  BY PERIOD (4-week horizon)\n{"="*90}')
print(f'  Discovery:  {df_sorted["report_date"].iloc[0].date()} -> {disc_end.date()}')
print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
print(f'  Final OOS:  {val_end.date()} -> {df_sorted["report_date"].iloc[-1].date()}\n')
for label, mask in [('DISCOVERY', df_sorted['report_date'] < disc_end),
                     ('VALIDATION', (df_sorted['report_date'] >= disc_end) & (df_sorted['report_date'] < val_end)),
                     ('FINAL OOS', df_sorted['report_date'] >= val_end)]:
    sub = df_sorted[mask]
    report_case(label, sub['z'].values, sub['fwd_vol_4w'].values)

print('\nDone.')
