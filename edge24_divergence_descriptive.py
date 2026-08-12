"""
edge24_divergence_descriptive.py

Gate 1 descriptive test for Edge #6 (E24): does commercial positioning
DIVERGENCE between NAS100 and SP500 predict their subsequent RELATIVE
return? Pre-registered in EDGE24_HYPOTHESIS.md.

Predicted direction: POSITIVE (NAS100 commercial positioning turning
relatively more bullish than SP500's predicts NAS100 outperformance).
"""
import urllib.request
import urllib.parse
import json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_WEEKS = 156
PUBLISH_LAG_DAYS = 3
HORIZONS_WEEKS = [1, 2, 4]


def fetch_cot(market):
    base = 'https://publicreporting.cftc.gov/resource/jun7-fc8e.json'
    params = {
        '$where': f"market_and_exchange_names = '{market}'",
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
    df['net_comm_frac'] = (df['comm_positions_long_all'] - df['comm_positions_short_all']) / df['open_interest_all']
    return df[['report_date', 'net_comm_frac']].sort_values('report_date').reset_index(drop=True)


def fetch_price(ticker):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
           '?period1=1136073600&period2=1893456000&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    result = data['chart']['result'][0]
    ts = result['timestamp']
    closes = result['indicators']['quote'][0]['close']
    df = pd.DataFrame({'time': pd.to_datetime(ts, unit='s', utc=True), 'close': closes})
    return df.dropna().sort_values('time').reset_index(drop=True)


print('Fetching COT data for NAS100 and SP500...')
cot_nas = fetch_cot('NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE').rename(columns={'net_comm_frac': 'nas_frac'})
cot_sp = fetch_cot('S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE').rename(columns={'net_comm_frac': 'sp_frac'})
cot = pd.merge(cot_nas, cot_sp, on='report_date', how='inner').sort_values('report_date').reset_index(drop=True)
cot['divergence'] = cot['nas_frac'] - cot['sp_frac']
print(f'  {len(cot)} merged weekly reports, {cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}')

print('Fetching NAS100 and SP500 price data...')
px_nas = fetch_price('%5ENDX')
px_sp = fetch_price('%5EGSPC')

cot['z'] = (cot['divergence'] - cot['divergence'].rolling(ZSCORE_WINDOW_WEEKS).mean()) / \
           cot['divergence'].rolling(ZSCORE_WINDOW_WEEKS).std()
cot = cot.dropna(subset=['z']).reset_index(drop=True)
print(f'\nAfter {ZSCORE_WINDOW_WEEKS}-week z-score warmup: {len(cot)} usable signals, '
      f'{cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}')

cot['signal_available_date'] = cot['report_date'] + pd.Timedelta(days=PUBLISH_LAG_DAYS)


def pos_on_or_after(px, t):
    p = np.searchsorted(px['time'].values, np.datetime64(t))
    return p if p < len(px) else -1


rows = []
for _, r in cot.iterrows():
    ep_nas = pos_on_or_after(px_nas, r['signal_available_date'])
    ep_sp = pos_on_or_after(px_sp, r['signal_available_date'])
    if ep_nas < 0 or ep_sp < 0:
        continue
    entry_nas = px_nas['close'].iloc[ep_nas]
    entry_sp = px_sp['close'].iloc[ep_sp]
    rec = {'report_date': r['report_date'], 'z': r['z']}
    ok = True
    for h in HORIZONS_WEEKS:
        target = r['signal_available_date'] + pd.Timedelta(weeks=h)
        xp_nas = pos_on_or_after(px_nas, target)
        xp_sp = pos_on_or_after(px_sp, target)
        if xp_nas < 0 or xp_sp < 0 or xp_nas <= ep_nas or xp_sp <= ep_sp:
            ok = False
            break
        nas_ret = np.log(px_nas['close'].iloc[xp_nas] / entry_nas)
        sp_ret = np.log(px_sp['close'].iloc[xp_sp] / entry_sp)
        rec[f'rel_ret_{h}w'] = nas_ret - sp_ret
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
    print(f'  {label:<12} N={n:>4}  corr={corr:>+7.4f}  bottom20%={bottom:>+8.2f}bp  '
          f'top20%={top:>+8.2f}bp  spread={top-bottom:>+8.2f}bp')


print(f'\n{"="*90}\n  FULL HISTORY: commercial-positioning divergence z-score -> NAS100-SP500 relative return\n{"="*90}')
print('  (predicted: POSITIVE correlation)')
for h in HORIZONS_WEEKS:
    report_case(f'{h}-week fwd', df['z'].values, df[f'rel_ret_{h}w'].values)

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
    report_case(label, sub['z'].values, sub['rel_ret_4w'].values)

print('\nDone.')
