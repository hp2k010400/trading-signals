"""
edge29_turnover_descriptive.py

Gate 1 descriptive test for E29: does volume/open-interest turnover
predict forward returns? Pre-registered in EDGE29_HYPOTHESIS.md,
follows DATABENTO_VALIDATION_PROTOCOL.md.

Signal = z-score(volume[t] / OI[t]), 756-day causal rolling window.
Predicted direction (locked): POSITIVE.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_DAYS = 756
PUBLISH_LAG_DAYS = 1
HORIZONS_DAYS = [5, 10, 20]
PRIMARY_SYMBOL = 'ES.n.0'
SYMBOLS = ['ES.n.0', 'NQ.n.0', 'GC.n.0', 'CL.n.0']


def load_price_volume():
    df = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'volume', 'symbol'])
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    return df.groupby(['symbol', 'date']).agg(close=('close', 'last'), volume=('volume', 'sum')).reset_index()


def load_oi():
    df = pd.read_csv('databento_statistics_v2.csv', usecols=['ts_event', 'quantity', 'stat_type', 'symbol'])
    df = df[df['stat_type'] == 9].copy()
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    daily = df.groupby(['symbol', 'date'])['quantity'].last().reset_index()
    return daily.rename(columns={'quantity': 'oi'})


def report_case(label, sig, fwd):
    n = len(sig)
    if n < 20:
        print(f'  {label}: N={n} too few')
        return
    corr = np.corrcoef(sig, fwd)[0, 1]
    order = np.argsort(sig)
    q = max(1, n // 5)
    bottom = fwd[order[:q]].mean() * 10000
    top = fwd[order[-q:]].mean() * 10000
    print(f'  {label:<12} N={n:>5}  corr={corr:>+7.4f}  bottom20%={bottom:>+8.2f}bp  '
          f'top20%={top:>+8.2f}bp  spread={top-bottom:>+8.2f}bp')


print('Loading price/volume and open-interest data...')
pv_all = load_price_volume()
oi_all = load_oi()

results = {}
for symbol in SYMBOLS:
    pv = pv_all[pv_all['symbol'] == symbol].sort_values('date').reset_index(drop=True)
    oi = oi_all[oi_all['symbol'] == symbol].sort_values('date').reset_index(drop=True)
    m = pd.merge(pv, oi, on='date', how='inner').sort_values('date').reset_index(drop=True)
    if len(m) < 900:
        print(f'{symbol}: insufficient merged data, skipping')
        continue

    m['turnover'] = m['volume'] / m['oi']
    m['z'] = (m['turnover'] - m['turnover'].rolling(ZSCORE_WINDOW_DAYS).mean()) / \
             m['turnover'].rolling(ZSCORE_WINDOW_DAYS).std()
    m = m.dropna(subset=['z']).reset_index(drop=True)

    m['signal_available_date'] = m['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)
    m_dates = m['date'].values
    m_close = m['close'].values

    def pos_on_or_after(t, dates=m_dates):
        pos = np.searchsorted(dates, np.datetime64(t))
        return pos if pos < len(dates) else -1

    rows = []
    for _, r in m.iterrows():
        ep = pos_on_or_after(r['signal_available_date'])
        if ep < 0:
            continue
        entry_price = m_close[ep]
        rec = {'date': r['date'], 'z': r['z']}
        ok = True
        for h in HORIZONS_DAYS:
            xp = ep + h
            if xp >= len(m_close):
                ok = False
                break
            rec[f'fwd_ret_{h}d'] = np.log(m_close[xp] / entry_price)
        if ok:
            rows.append(rec)

    df = pd.DataFrame(rows)
    results[symbol] = df
    print(f'\n{"="*90}\n  {symbol}: turnover z-score -> forward return (N={len(df)})\n{"="*90}')
    if symbol == PRIMARY_SYMBOL:
        print('  (predicted: POSITIVE correlation)')
    for h in HORIZONS_DAYS:
        report_case(f'{h}-day fwd', df['z'].values, df[f'fwd_ret_{h}d'].values)

if PRIMARY_SYMBOL in results:
    df = results[PRIMARY_SYMBOL]
    n = len(df)
    if n >= 60:
        df_sorted = df.sort_values('date').reset_index(drop=True)
        disc_end = df_sorted['date'].iloc[int(n * 0.50)]
        val_end = df_sorted['date'].iloc[int(n * 0.75)]
        print(f'\n{"="*90}\n  {PRIMARY_SYMBOL} BY PERIOD (10-day horizon)\n{"="*90}')
        print(f'  Discovery:  {df_sorted["date"].iloc[0].date()} -> {disc_end.date()}')
        print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
        print(f'  Final OOS:  {val_end.date()} -> {df_sorted["date"].iloc[-1].date()}\n')
        for label, mask in [('DISCOVERY', df_sorted['date'] < disc_end),
                             ('VALIDATION', (df_sorted['date'] >= disc_end) & (df_sorted['date'] < val_end)),
                             ('FINAL OOS', df_sorted['date'] >= val_end)]:
            sub = df_sorted[mask]
            report_case(label, sub['z'].values, sub['fwd_ret_10d'].values)

print('\nDone.')
