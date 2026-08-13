"""
edge27_oi_descriptive.py

Gate 1 (descriptive phenomenon) for E27: does open interest change
predict forward returns? Pre-registered in EDGE27_HYPOTHESIS.md,
follows DATABENTO_VALIDATION_PROTOCOL.md.

Loads real Databento data already downloaded to:
  databento_ohlcv_1h_v2.csv   (schema=ohlcv-1h, ES/NQ/GC/CL, 2010-2026)
  databento_statistics_v2.csv (schema=statistics, same universe/range;
                                stat_type=9 rows are Open Interest,
                                confirmed against Databento's own dbn
                                enums.rs source -- quantity field is OI,
                                ts_ref is not populated on these rows so
                                ts_event is used as the reference time)

Predicted direction (locked in EDGE27_HYPOTHESIS.md): POSITIVE.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_DAYS = 756  # ~36 months
OI_CHANGE_WINDOW_DAYS = 21  # ~1 month
PUBLISH_LAG_DAYS = 1  # business days
HORIZONS_WEEKS = [2, 4, 8]
PRIMARY_SYMBOL = 'ES.n.0'
SYMBOLS = ['ES.n.0', 'NQ.n.0', 'GC.n.0', 'CL.n.0']


def load_price():
    df = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'symbol'])
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    daily = df.groupby(['symbol', 'date'])['close'].last().reset_index()
    return daily


def load_oi():
    df = pd.read_csv('databento_statistics_v2.csv',
                      usecols=['ts_event', 'quantity', 'stat_type', 'symbol'])
    df = df[df['stat_type'] == 9].copy()
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    daily = df.groupby(['symbol', 'date'])['quantity'].last().reset_index()
    daily = daily.rename(columns={'quantity': 'oi'})
    return daily


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


print('Loading price and open-interest data...')
price = load_price()
oi = load_oi()
print(f'  Price: {len(price)} symbol-days, {price["date"].min().date()} -> {price["date"].max().date()}')
print(f'  OI: {len(oi)} symbol-days, {oi["date"].min().date()} -> {oi["date"].max().date()}')
for s in SYMBOLS:
    print(f'    {s}: price {len(price[price.symbol==s])} days, OI {len(oi[oi.symbol==s])} days')

results_by_symbol = {}
for symbol in SYMBOLS:
    p = price[price['symbol'] == symbol].sort_values('date').reset_index(drop=True)
    o = oi[oi['symbol'] == symbol].sort_values('date').reset_index(drop=True)
    if len(p) < 100 or len(o) < 100:
        print(f'\n{symbol}: insufficient data, skipping')
        continue

    o['oi_change'] = o['oi'] / o['oi'].shift(OI_CHANGE_WINDOW_DAYS) - 1
    o['z'] = (o['oi_change'] - o['oi_change'].rolling(ZSCORE_WINDOW_DAYS).mean()) / \
             o['oi_change'].rolling(ZSCORE_WINDOW_DAYS).std()
    o = o.dropna(subset=['z']).reset_index(drop=True)
    if len(o) < 100:
        print(f'\n{symbol}: insufficient data after z-score warmup, skipping')
        continue

    o['signal_available_date'] = o['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)

    p_dates = p['date'].values
    p_close = p['close'].values

    def pos_on_or_after(t):
        pos = np.searchsorted(p_dates, np.datetime64(t))
        return pos if pos < len(p_dates) else -1

    rows = []
    for _, r in o.iterrows():
        ep = pos_on_or_after(r['signal_available_date'])
        if ep < 0:
            continue
        entry_price = p_close[ep]
        rec = {'date': r['date'], 'z': r['z']}
        ok = True
        for h in HORIZONS_WEEKS:
            target = r['signal_available_date'] + pd.Timedelta(weeks=h)
            xp = pos_on_or_after(target)
            if xp < 0 or xp <= ep:
                ok = False
                break
            rec[f'fwd_ret_{h}w'] = np.log(p_close[xp] / entry_price)
        if ok:
            rows.append(rec)

    df = pd.DataFrame(rows)
    results_by_symbol[symbol] = df
    print(f'\n{"="*90}\n  {symbol}: OI-change z-score -> forward return (N={len(df)})\n{"="*90}')
    if symbol == PRIMARY_SYMBOL:
        print('  (predicted: POSITIVE correlation)')
    for h in HORIZONS_WEEKS:
        report_case(f'{h}-week fwd', df['z'].values, df[f'fwd_ret_{h}w'].values)

# Period breakdown for primary instrument only (Gate 1 focus)
if PRIMARY_SYMBOL in results_by_symbol:
    df = results_by_symbol[PRIMARY_SYMBOL]
    n = len(df)
    if n >= 60:
        df_sorted = df.sort_values('date').reset_index(drop=True)
        disc_end = df_sorted['date'].iloc[int(n * 0.50)]
        val_end = df_sorted['date'].iloc[int(n * 0.75)]
        print(f'\n{"="*90}\n  {PRIMARY_SYMBOL} BY PERIOD (4-week horizon)\n{"="*90}')
        print(f'  Discovery:  {df_sorted["date"].iloc[0].date()} -> {disc_end.date()}')
        print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
        print(f'  Final OOS:  {val_end.date()} -> {df_sorted["date"].iloc[-1].date()}\n')
        for label, mask in [('DISCOVERY', df_sorted['date'] < disc_end),
                             ('VALIDATION', (df_sorted['date'] >= disc_end) & (df_sorted['date'] < val_end)),
                             ('FINAL OOS', df_sorted['date'] >= val_end)]:
            sub = df_sorted[mask]
            report_case(label, sub['z'].values, sub['fwd_ret_4w'].values)

        print(f'\n{"="*90}\n  {PRIMARY_SYMBOL} BY YEAR (4-week horizon)\n{"="*90}')
        df_sorted['year'] = df_sorted['date'].dt.year
        for year in sorted(df_sorted['year'].unique()):
            sub = df_sorted[df_sorted['year'] == year]
            report_case(str(year), sub['z'].values, sub['fwd_ret_4w'].values)

print('\nDone.')
