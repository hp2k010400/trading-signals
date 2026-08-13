"""
edge32_spillover_descriptive.py

Gate 1 descriptive test for EDGE32: does an NQ volume shock predict
elevated forward ES realized volatility? Pre-registered in
EDGE32_HYPOTHESIS.md.

Predicted direction: POSITIVE.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
from scipy import stats as sstats

VOL_MEDIAN_WINDOW = 60
HORIZONS_DAYS = [5, 10, 20]
PUBLISH_LAG_DAYS = 1


def load_daily():
    df = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'volume', 'symbol'])
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    return df.groupby(['symbol', 'date']).agg(close=('close', 'last'), volume=('volume', 'sum')).reset_index()


def report_case(label, sig, fwd):
    n = len(sig)
    if n < 20:
        print(f'  {label}: N={n} too few')
        return
    r, p = sstats.pearsonr(sig, fwd)
    order = np.argsort(sig)
    q = max(1, n // 5)
    bottom = fwd[order[:q]].mean() * 10000
    top = fwd[order[-q:]].mean() * 10000
    print(f'  {label:<14} N={n:>5}  corr={r:>+7.4f}  p={p:.4f}  low-vol-shock={bottom:>8.2f}bp  '
          f'high-vol-shock={top:>8.2f}bp  spread={top-bottom:>+8.2f}bp')


print('Loading daily data...')
daily = load_daily()
nq = daily[daily['symbol'] == 'NQ.n.0'].sort_values('date').reset_index(drop=True)
es = daily[daily['symbol'] == 'ES.n.0'].sort_values('date').reset_index(drop=True)

nq['vol_median60'] = nq['volume'].rolling(VOL_MEDIAN_WINDOW).median()
nq['volume_shock'] = nq['volume'] / nq['vol_median60']
nq = nq.dropna(subset=['volume_shock']).reset_index(drop=True)
nq['signal_available_date'] = nq['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)

es['ret'] = np.log(es['close'] / es['close'].shift(1))
es_dates = es['date'].values
es_close = es['close'].values
es_ret = es['ret'].values


def pos_on_or_after(t, dates=es_dates):
    pos = np.searchsorted(dates, np.datetime64(t))
    return pos if pos < len(dates) else -1


rows = []
merged = pd.merge(nq[['date', 'signal_available_date', 'volume_shock']], es[['date']], on='date', how='inner')
for _, r in merged.iterrows():
    ep = pos_on_or_after(r['signal_available_date'])
    if ep < 0:
        continue
    rec = {'date': r['date'], 'volume_shock': r['volume_shock']}
    ok = True
    for h in HORIZONS_DAYS:
        xp = ep + h
        if xp >= len(es_close):
            ok = False
            break
        fwd_vol = np.std(es_ret[ep + 1:xp + 1])
        rec[f'fwd_vol_{h}d'] = fwd_vol
    if ok:
        rows.append(rec)

df = pd.DataFrame(rows)
print(f'\nUsable paired observations: {len(df)}')

print(f'\n{"="*90}\n  FULL HISTORY: NQ volume shock -> ES forward realized volatility\n{"="*90}')
print('  (predicted: POSITIVE correlation)')
for h in HORIZONS_DAYS:
    report_case(f'{h}-day fwd', df['volume_shock'].values, df[f'fwd_vol_{h}d'].values)

n = len(df)
df_sorted = df.sort_values('date').reset_index(drop=True)
disc_end = df_sorted['date'].iloc[int(n * 0.50)]
val_end = df_sorted['date'].iloc[int(n * 0.75)]
print(f'\n{"="*90}\n  BY PERIOD (10-day horizon)\n{"="*90}')
print(f'  Discovery:  {df_sorted["date"].iloc[0].date()} -> {disc_end.date()}')
print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
print(f'  Final OOS:  {val_end.date()} -> {df_sorted["date"].iloc[-1].date()}\n')
for label, mask in [('DISCOVERY', df_sorted['date'] < disc_end),
                     ('VALIDATION', (df_sorted['date'] >= disc_end) & (df_sorted['date'] < val_end)),
                     ('FINAL OOS', df_sorted['date'] >= val_end)]:
    sub = df_sorted[mask]
    report_case(label, sub['volume_shock'].values, sub['fwd_vol_10d'].values)

print('\nDone.')
