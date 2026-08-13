"""
edge31_volume_confirmation_descriptive.py

Gate 1 descriptive test for EDGE31: on large-move days, does volume
confirmation (volume_pctile) predict continuation in the original
move's direction? Pre-registered in EDGE31_HYPOTHESIS.md.

Predicted direction: POSITIVE.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

MOVE_LOOKBACK_DAYS = 252
LARGE_MOVE_PCTILE = 80
HORIZONS_DAYS = [5, 10, 20]
PRIMARY_SYMBOL = 'ES.n.0'
SYMBOLS = ['ES.n.0', 'NQ.n.0', 'GC.n.0', 'CL.n.0']
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
    corr = np.corrcoef(sig, fwd)[0, 1]
    from scipy import stats as sstats
    r, p = sstats.pearsonr(sig, fwd)
    order = np.argsort(sig)
    q = max(1, n // 5)
    bottom = fwd[order[:q]].mean() * 10000
    top = fwd[order[-q:]].mean() * 10000
    print(f'  {label:<14} N={n:>5}  corr={corr:>+7.4f}  p={p:.4f}  low-vol={bottom:>+8.2f}bp  '
          f'high-vol={top:>+8.2f}bp  spread={top-bottom:>+8.2f}bp')


print('Loading daily price+volume...')
daily = load_daily()

results = {}
for symbol in SYMBOLS:
    d = daily[daily['symbol'] == symbol].sort_values('date').reset_index(drop=True)
    if len(d) < 400:
        continue
    d['ret'] = np.log(d['close'] / d['close'].shift(1))
    d['abs_ret'] = d['ret'].abs()
    d['move_pctile'] = d['abs_ret'].rolling(MOVE_LOOKBACK_DAYS).rank(pct=True) * 100
    d['volume_pctile'] = d['volume'].rolling(MOVE_LOOKBACK_DAYS).rank(pct=True) * 100
    d = d.dropna(subset=['move_pctile', 'volume_pctile']).reset_index(drop=True)

    large_move = d[d['move_pctile'] >= LARGE_MOVE_PCTILE].copy()
    large_move['signal_available_date'] = large_move['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)

    d_dates = d['date'].values
    d_close = d['close'].values

    def pos_on_or_after(t, dates=d_dates):
        pos = np.searchsorted(dates, np.datetime64(t))
        return pos if pos < len(dates) else -1

    rows = []
    for _, r in large_move.iterrows():
        ep = pos_on_or_after(r['signal_available_date'])
        if ep < 0:
            continue
        entry_price = d_close[ep]
        rec = {'date': r['date'], 'volume_pctile': r['volume_pctile'], 'orig_dir': np.sign(r['ret'])}
        ok = True
        for h in HORIZONS_DAYS:
            xp = ep + h
            if xp >= len(d_close):
                ok = False
                break
            rec[f'fwd_signed_{h}d'] = rec['orig_dir'] * np.log(d_close[xp] / entry_price)
        if ok:
            rows.append(rec)

    df = pd.DataFrame(rows)
    results[symbol] = df
    print(f'\n{"="*90}\n  {symbol}: volume_pctile (on large-move days) -> signed forward return (N={len(df)})\n{"="*90}')
    print(f'  Large-move days: {len(large_move)} / {len(d)} total ({len(large_move)/len(d)*100:.1f}%, target ~{100-LARGE_MOVE_PCTILE}%)')
    if symbol == PRIMARY_SYMBOL:
        print('  (predicted: POSITIVE correlation -- high volume confirms continuation)')
    for h in HORIZONS_DAYS:
        report_case(f'{h}-day fwd', df['volume_pctile'].values, df[f'fwd_signed_{h}d'].values)

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
            report_case(label, sub['volume_pctile'].values, sub['fwd_signed_10d'].values)

print('\nDone.')
