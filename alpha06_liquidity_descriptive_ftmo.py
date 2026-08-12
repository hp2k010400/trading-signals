"""
alpha06_liquidity_descriptive_ftmo.py

Phase 3 of the alpha06 protocol (market microstructure / liquidity
proxies). DESCRIPTIVE ONLY -- no strategy, no stop/target, no filters.

Primary tool: Corwin-Schultz (2012) range-based bid-ask spread
estimator, computed from daily High/Low only (no volume needed).
CS_spread[t] is estimated from the (t-1, t) day pair -- i.e. it is
fully known at the close of day t -- and tested against fwd_ret[t] =
log(close[t+1]/close[t]), the day t->t+1 return that is NOT yet known
when CS_spread[t] becomes available. This pairing is deliberately
lookahead-free.

Two tests, per ALPHA06_LITERATURE.md's Amihud-illiquidity-premium
hypothesis:
  1. TIME-SERIES: within each instrument, does today's estimated
     spread (illiquidity) predict tomorrow's return? (correlation +
     top/bottom quintile spread, by period)
  2. CROSS-SECTIONAL: on a given day, ranking all instruments by
     estimated spread, do the more-illiquid instruments earn a
     different subsequent return than the more-liquid ones? (the
     classic Amihud cross-sectional test, applied to our universe)

Roll's (1984) implied spread is computed as a secondary cross-check
only (per the literature's caution that it's more fragile/biased) --
used to confirm the two liquidity proxies broadly agree on relative
ranking, not as an independent trading signal.

Run in Codespace: python -u alpha06_liquidity_descriptive_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

FILES = {
    'DAX':    'GER40_M1_ftmo.csv',
    'NAS100': 'US100_M1_ftmo.csv',
    'SP500':  'US500_M1_ftmo.csv',
    'US30':   'US30_M1_ftmo.csv',
    'UK100':  'UK100_cash_M1_ftmo.csv',
    'FRA40':  'FRA40_M1_ftmo.csv',
    'JP225':  'JP225_M1_ftmo.csv',
    'AUS200': 'AUS200_M1_ftmo.csv',
    'EU50':   'EU50_M1_ftmo.csv',
    'US2000': 'US2000_M1_ftmo.csv',
    'HK50':   'HK50_M1_ftmo.csv',
    'AUDCAD': 'AUDCAD_M1_ftmo.csv',
    'AUDNZD': 'AUDNZD_M1_ftmo.csv',
}

K_CONST = 3 - 2 * np.sqrt(2)


def load_daily_ohlc(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'high': 'float32', 'low': 'float32', 'close': 'float32'},
                      usecols=['time', 'high', 'low', 'close'])
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    daily = df.resample('1D').agg({'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    return daily


def corwin_schultz_spread(high, low):
    """Vectorized 2-day CS spread. Result index i uses days (i-1, i),
    so it's known at the close of day i. First element is NaN."""
    h = high.values.astype(float)
    l = low.values.astype(float)
    n = len(h)
    log_hl2 = np.log(h / l) ** 2
    beta = np.full(n, np.nan)
    gamma = np.full(n, np.nan)
    beta[1:] = log_hl2[:-1] + log_hl2[1:]
    hh = np.maximum(h[:-1], h[1:])
    ll = np.minimum(l[:-1], l[1:])
    gamma[1:] = np.log(hh / ll) ** 2
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / K_CONST - np.sqrt(gamma / K_CONST)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    spread = np.where(np.isnan(spread), np.nan, np.maximum(spread, 0))
    return spread


def roll_spread(close, window=20):
    dp = close.diff()
    dp_lag = dp.shift(1)
    cov = dp.rolling(window).cov(dp_lag)
    return 2 * np.sqrt(np.maximum(0, -cov))


print('Loading and computing liquidity proxies...')
data = {}
for sym in FILES:
    d = load_daily_ohlc(sym)
    if d is None:
        print(f'  {sym}: FILE NOT FOUND, skipped')
        continue
    d['cs_spread'] = corwin_schultz_spread(d['high'], d['low'])
    d['roll_spread'] = roll_spread(d['close'])
    d['fwd_ret'] = np.log(d['close'].shift(-1) / d['close'])
    d = d.dropna(subset=['cs_spread', 'fwd_ret'])
    data[sym] = d
    print(f'  {sym}: {len(d)} daily obs, {d.index[0].date()} -> {d.index[-1].date()}, '
          f'mean CS spread={d["cs_spread"].mean()*10000:.2f}bp')

# ============================================================
# CHECK: do CS-spread and Roll-spread broadly agree? (rank correlation)
# ============================================================
print(f'\n{"="*90}\n  CS-spread vs Roll-spread rank agreement (Spearman corr, per instrument)\n{"="*90}')
for sym, d in data.items():
    m = d[['cs_spread', 'roll_spread']].dropna()
    if len(m) < 30:
        continue
    rho = m['cs_spread'].rank().corr(m['roll_spread'].rank())
    print(f'  {sym:<8} N={len(m):>6}  rank_corr={rho:>+.4f}')

# ============================================================
# TEST 1: TIME-SERIES -- does today's CS spread predict tomorrow's return?
# ============================================================
print(f'\n{"="*90}\n  TIME-SERIES: CS spread[t] -> fwd_ret[t] (per instrument)\n{"="*90}')
for sym, d in data.items():
    n = len(d)
    corr = d['cs_spread'].corr(d['fwd_ret'])
    order = d['cs_spread'].values.argsort()
    q = max(1, n // 5)
    bottom = d['fwd_ret'].values[order[:q]].mean() * 10000
    top = d['fwd_ret'].values[order[-q:]].mean() * 10000
    print(f'  {sym:<8} N={n:>6}  corr={corr:>+7.4f}  low-illiq={bottom:>+7.2f}bp  '
          f'high-illiq={top:>+7.2f}bp  spread={top-bottom:>+7.2f}bp')

    # by period
    dates = d.index.to_series()
    disc_end = dates.iloc[int(n * 0.50)]
    val_end = dates.iloc[int(n * 0.75)]
    for label, mask in [('  Discovery', d.index < disc_end),
                         ('  Validation', (d.index >= disc_end) & (d.index < val_end)),
                         ('  Final OOS', d.index >= val_end)]:
        sub = d[mask]
        if len(sub) < 30:
            continue
        c = sub['cs_spread'].corr(sub['fwd_ret'])
        print(f'    {label:<14} N={len(sub):>6}  corr={c:>+7.4f}')

# ============================================================
# TEST 2: CROSS-SECTIONAL -- on a given day, do high-illiquidity
# instruments earn a different subsequent return than low-illiquidity ones?
# ============================================================
print(f'\n{"="*90}\n  CROSS-SECTIONAL: rank instruments by CS spread each day, high vs low illiquidity group\n{"="*90}')

panel = []
for sym, d in data.items():
    tmp = d[['cs_spread', 'fwd_ret']].copy()
    tmp['symbol'] = sym
    panel.append(tmp.reset_index().rename(columns={'time': 'date'}))
panel = pd.concat(panel, ignore_index=True)

daily_results = []
for date, g in panel.groupby('date'):
    if len(g) < 6:  # need a reasonable cross-section that day
        continue
    g = g.sort_values('cs_spread')
    n = len(g)
    tercile = max(1, n // 3)
    low_illiq = g['fwd_ret'].iloc[:tercile].mean()
    high_illiq = g['fwd_ret'].iloc[-tercile:].mean()
    daily_results.append({'date': date, 'n': n, 'low_illiq_ret': low_illiq, 'high_illiq_ret': high_illiq})

xs = pd.DataFrame(daily_results)
xs['spread_bp'] = (xs['high_illiq_ret'] - xs['low_illiq_ret']) * 10000
print(f'  Days with >=6 instruments: {len(xs)}')
print(f'  Mean daily cross-sectional spread (high-illiq minus low-illiq): {xs["spread_bp"].mean():>+7.3f}bp')
print(f'  Std: {xs["spread_bp"].std():.3f}bp   t-stat (approx): '
      f'{xs["spread_bp"].mean() / (xs["spread_bp"].std() / np.sqrt(len(xs))):>+.3f}')

n_xs = len(xs)
if n_xs > 60:
    xs_sorted = xs.sort_values('date')
    disc_end = xs_sorted['date'].iloc[int(n_xs * 0.50)]
    val_end = xs_sorted['date'].iloc[int(n_xs * 0.75)]
    for label, mask in [('Discovery', xs_sorted['date'] < disc_end),
                         ('Validation', (xs_sorted['date'] >= disc_end) & (xs_sorted['date'] < val_end)),
                         ('Final OOS', xs_sorted['date'] >= val_end)]:
        sub = xs_sorted[mask]
        if len(sub) < 20:
            continue
        print(f'  {label:<12} N={len(sub):>5}  mean spread={sub["spread_bp"].mean():>+7.3f}bp')

print('\nDone.')
