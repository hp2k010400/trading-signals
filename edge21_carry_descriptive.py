"""
edge21_carry_descriptive.py

Gate 1 descriptive test for Edge #3 (E21): does the AU-CA / AU-NZ
short-rate differential predict forward AUDCAD / AUDNZD returns?
Pre-registered in EDGE21_HYPOTHESIS.md BEFORE this script was run.

Predicted direction (locked in advance): POSITIVE correlation (higher
AU rate relative to CA/NZ predicts AUD appreciation against that
currency), per the forward-premium-puzzle/carry-trade literature.

DESCRIPTIVE ONLY. Real data (FRED CSV export + Yahoo Finance), both
reachable directly from this environment.
"""
import urllib.request
import json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_MONTHS = 36
PUBLISH_LAG_DAYS = 45
HORIZONS_MONTHS = [1, 2, 3]

PAIRS = {
    'AUDCAD': {'base': 'IR3TIB01AUM156N', 'quote': 'IR3TIB01CAM156N', 'yahoo': 'AUDCAD%3DX'},
    'AUDNZD': {'base': 'IR3TIB01AUM156N', 'quote': 'IR3TIB01NZM156N', 'yahoo': 'AUDNZD%3DX'},
}


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


def fetch_fx(ticker):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
           '?period1=1000000000&period2=1893456000&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    result = data['chart']['result'][0]
    ts = result['timestamp']
    closes = result['indicators']['quote'][0]['close']
    df = pd.DataFrame({'time': pd.to_datetime(ts, unit='s', utc=True), 'close': closes})
    df = df.dropna().sort_values('time').reset_index(drop=True)
    return df


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


for pair_name, cfg in PAIRS.items():
    print(f'\n{"#"*100}\n  {pair_name}\n{"#"*100}')
    print('Fetching rate data...')
    base_rate = fetch_fred(cfg['base']).rename(columns={cfg['base']: 'base_rate'})
    quote_rate = fetch_fred(cfg['quote']).rename(columns={cfg['quote']: 'quote_rate'})
    rates = pd.merge(base_rate, quote_rate, on='date', how='inner').sort_values('date').reset_index(drop=True)
    rates['diff'] = rates['base_rate'] - rates['quote_rate']
    print(f'  {len(rates)} monthly observations, {rates["date"].iloc[0].date()} -> {rates["date"].iloc[-1].date()}')

    print('Fetching FX price data...')
    px = fetch_fx(cfg['yahoo'])
    print(f'  {len(px)} daily bars, {px["time"].iloc[0].date()} -> {px["time"].iloc[-1].date()}')

    rates['z'] = (rates['diff'] - rates['diff'].rolling(ZSCORE_WINDOW_MONTHS).mean()) / \
                 rates['diff'].rolling(ZSCORE_WINDOW_MONTHS).std()
    rates = rates.dropna(subset=['z']).reset_index(drop=True)
    print(f'  After {ZSCORE_WINDOW_MONTHS}-month z-score warmup: {len(rates)} usable signals, '
          f'{rates["date"].iloc[0].date()} -> {rates["date"].iloc[-1].date()}')

    rates['signal_available_date'] = rates['date'] + pd.Timedelta(days=PUBLISH_LAG_DAYS)

    px_idx = px['time'].values
    px_close = px['close'].values

    def pos_on_or_after(target_ts):
        pos = np.searchsorted(px_idx, np.datetime64(target_ts))
        return pos if pos < len(px_idx) else -1

    rows = []
    for _, r in rates.iterrows():
        entry_pos = pos_on_or_after(r['signal_available_date'])
        if entry_pos < 0:
            continue
        entry_price = px_close[entry_pos]
        rec = {'date': r['date'], 'z': r['z']}
        ok = True
        for h in HORIZONS_MONTHS:
            target = r['signal_available_date'] + pd.DateOffset(months=h)
            exit_pos = pos_on_or_after(target)
            if exit_pos < 0 or exit_pos <= entry_pos:
                ok = False
                break
            rec[f'fwd_ret_{h}m'] = np.log(px_close[exit_pos] / entry_price)
        if ok:
            rows.append(rec)

    df = pd.DataFrame(rows)
    print(f'\n  Usable paired observations: {len(df)}')
    print(f'  (predicted: POSITIVE correlation -- higher AU rate diff -> AUD appreciation)')
    for h in HORIZONS_MONTHS:
        report_case(f'{h}-month fwd', df['z'].values, df[f'fwd_ret_{h}m'].values)

    n = len(df)
    if n >= 40:
        df_sorted = df.sort_values('date').reset_index(drop=True)
        disc_end = df_sorted['date'].iloc[int(n * 0.50)]
        val_end = df_sorted['date'].iloc[int(n * 0.75)]
        print(f'\n  BY PERIOD (3-month horizon):')
        print(f'  Discovery:  {df_sorted["date"].iloc[0].date()} -> {disc_end.date()}')
        print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
        print(f'  Final OOS:  {val_end.date()} -> {df_sorted["date"].iloc[-1].date()}')
        for label, mask in [('DISCOVERY', df_sorted['date'] < disc_end),
                             ('VALIDATION', (df_sorted['date'] >= disc_end) & (df_sorted['date'] < val_end)),
                             ('FINAL OOS', df_sorted['date'] >= val_end)]:
            sub = df_sorted[mask]
            report_case(label, sub['z'].values, sub['fwd_ret_3m'].values)

print('\nDone.')
