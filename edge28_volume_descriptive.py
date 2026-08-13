"""
edge28_volume_descriptive.py

Gate 1 descriptive test for E28: volume-conditioned continuation
(short horizon) vs. reversal (longer horizon). Pre-registered in
EDGE28_HYPOTHESIS.md, follows DATABENTO_VALIDATION_PROTOCOL.md.

Signal = abnormal_volume(60-day rolling median) x sign(daily return),
already downloaded real Databento data (databento_ohlcv_1h_v2.csv).

Predicted (locked in advance):
  Stage A (continuation): POSITIVE correlation at short horizons (3, 5d)
  Stage B (reversal): NEGATIVE correlation (or decaying) at longer
  horizons (15, 20d)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

VOL_MEDIAN_WINDOW = 60
PUBLISH_LAG_DAYS = 1
HORIZONS_DAYS = [3, 5, 10, 15, 20]
PRIMARY_SYMBOL = 'ES.n.0'
SYMBOLS = ['ES.n.0', 'NQ.n.0', 'GC.n.0', 'CL.n.0']


def load_daily():
    df = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'volume', 'symbol'])
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    daily = df.groupby(['symbol', 'date']).agg(close=('close', 'last'), volume=('volume', 'sum')).reset_index()
    return daily


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


print('Loading daily price+volume...')
daily = load_daily()
print(f'  {len(daily)} symbol-days total')

results = {}
for symbol in SYMBOLS:
    d = daily[daily['symbol'] == symbol].sort_values('date').reset_index(drop=True)
    if len(d) < 200:
        continue
    d['ret'] = np.log(d['close'] / d['close'].shift(1))
    d['vol_median60'] = d['volume'].rolling(VOL_MEDIAN_WINDOW).median()
    d['abnormal_vol'] = d['volume'] / d['vol_median60']
    d['signal'] = d['abnormal_vol'] * np.sign(d['ret'])
    d = d.dropna(subset=['signal']).reset_index(drop=True)

    d['signal_available_date'] = d['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)
    d_dates = d['date'].values
    d_close = d['close'].values

    def pos_on_or_after(t, dates=d_dates):
        pos = np.searchsorted(dates, np.datetime64(t))
        return pos if pos < len(dates) else -1

    rows = []
    for _, r in d.iterrows():
        ep = pos_on_or_after(r['signal_available_date'])
        if ep < 0:
            continue
        entry_price = d_close[ep]
        rec = {'date': r['date'], 'signal': r['signal']}
        ok = True
        for h in HORIZONS_DAYS:
            xp = ep + h
            if xp >= len(d_close):
                ok = False
                break
            rec[f'fwd_ret_{h}d'] = np.log(d_close[xp] / entry_price)
        if ok:
            rows.append(rec)

    df = pd.DataFrame(rows)
    results[symbol] = df
    print(f'\n{"="*90}\n  {symbol}: abnormal-volume-weighted signal -> forward return (N={len(df)})\n{"="*90}')
    if symbol == PRIMARY_SYMBOL:
        print('  (predicted: Stage A [3,5d] POSITIVE continuation; Stage B [15,20d] NEGATIVE/decaying reversal)')
    for h in HORIZONS_DAYS:
        report_case(f'{h}-day fwd', df['signal'].values, df[f'fwd_ret_{h}d'].values)

# Period breakdown for primary instrument, Stage A (5d) and Stage B (20d)
if PRIMARY_SYMBOL in results:
    df = results[PRIMARY_SYMBOL]
    n = len(df)
    df_sorted = df.sort_values('date').reset_index(drop=True)
    disc_end = df_sorted['date'].iloc[int(n * 0.50)]
    val_end = df_sorted['date'].iloc[int(n * 0.75)]
    print(f'\n{"="*90}\n  {PRIMARY_SYMBOL} BY PERIOD\n{"="*90}')
    print(f'  Discovery:  {df_sorted["date"].iloc[0].date()} -> {disc_end.date()}')
    print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
    print(f'  Final OOS:  {val_end.date()} -> {df_sorted["date"].iloc[-1].date()}\n')
    for h, tag in [(5, 'Stage A (5d)'), (20, 'Stage B (20d)')]:
        print(f'  --- {tag} ---')
        for label, mask in [('DISCOVERY', df_sorted['date'] < disc_end),
                             ('VALIDATION', (df_sorted['date'] >= disc_end) & (df_sorted['date'] < val_end)),
                             ('FINAL OOS', df_sorted['date'] >= val_end)]:
            sub = df_sorted[mask]
            report_case(label, sub['signal'].values, sub[f'fwd_ret_{h}d'].values)

print('\nDone.')
