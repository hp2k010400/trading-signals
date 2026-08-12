"""
alpha05_pair_screening_ftmo.py

Phase 2/3 of the alpha05 protocol (statistical arbitrage / cointegrated
index spreads). DESCRIPTIVE / SCREENING ONLY -- no strategy, no
stop/target, no filters. For each candidate pair identified in
ALPHA05_LITERATURE.md (grounded in the real cited DAX-EuroStoxx50
correlation fact, not guessed), this:

  1. Computes daily-close correlation over the FULL history (context only).
  2. Runs a formal Engle-Granger cointegration test -- OLS hedge ratio
     regression + Augmented Dickey-Fuller test on the residual spread --
     estimated ONLY on the FORMATION period (first 50% of history by
     date, matching this research programme's Discovery convention).
     This directly implements the literature's warning: correlation is
     not cointegration, and re-fitting the hedge ratio on
     Validation/Final-OOS data would be both a lookahead violation and
     exactly the kind of in-sample-flattering bias the OLS mean-
     reversion-speed literature warns about.
  3. Estimates the spread's mean-reversion half-life via AR(1) fit,
     formation period only.
  4. Reports out-of-formation behaviour: applying the FIXED (formation-
     period) hedge ratio to Validation+Final-OOS data and checking
     whether the resulting spread still looks mean-reverting (same
     half-life ballpark, doesn't trend away) -- this is the real test
     of whether the relationship survives, not just whether it existed
     historically.

Uses statsmodels' adfuller if available (exact p-values); falls back to
a manual ADF regression + MacKinnon-table approximate critical values
if not (noted explicitly in the output either way, per the honesty
requirement -- do not silently present an approximation as an exact
p-value).

Run in Codespace: python -u alpha05_pair_screening_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

FILES = {
    'DAX':    'GER40_M1_ftmo.csv',
    'FRA40':  'FRA40_M1_ftmo.csv',
    'EU50':   'EU50_M1_ftmo.csv',
    'UK100':  'UK100_cash_M1_ftmo.csv',
    'NAS100': 'US100_M1_ftmo.csv',
    'SP500':  'US500_M1_ftmo.csv',
    'US30':   'US30_M1_ftmo.csv',
    'US2000': 'US2000_M1_ftmo.csv',
}

# Grounded in ALPHA05_LITERATURE.md: Eurozone cluster (high correlation
# expected), US mega-cap cluster (high correlation expected), UK100 and
# US2000 as weaker/uncertain candidates to actually test, not assume.
PAIRS = [
    ('DAX', 'EU50'), ('DAX', 'FRA40'), ('FRA40', 'EU50'),
    ('NAS100', 'SP500'), ('SP500', 'US30'), ('NAS100', 'US30'),
    ('UK100', 'DAX'), ('UK100', 'EU50'),
    ('US2000', 'SP500'), ('US2000', 'NAS100'),
]

# MacKinnon (Engle-Granger, 1 regressor, no trend) approximate asymptotic
# critical values -- used only if statsmodels is unavailable.
EG_CRIT = {'1%': -3.90, '5%': -3.34, '10%': -3.04}

try:
    from statsmodels.tsa.stattools import adfuller as _sm_adfuller
    HAVE_STATSMODELS = True
except ImportError:
    HAVE_STATSMODELS = False


def load_daily_close(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip', dtype={'close': 'float32'}, usecols=['time', 'close'])
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    daily = df['close'].resample('1D').last().dropna()
    return daily


def adf_tstat(series):
    """ADF test statistic, no trend, 1 lag of the differenced series
    (standard default for daily financial spreads)."""
    if HAVE_STATSMODELS:
        try:
            return _sm_adfuller(series.values, maxlag=1, autolag=None, regression='c')[0], True
        except Exception:
            pass
    y = series.values.astype(float)
    dy = np.diff(y)
    y_lag = y[:-1]
    if len(dy) < 3:
        return np.nan, False
    d_lag = np.diff(y_lag)  # one lag of the differenced series
    n = len(d_lag)
    X = np.column_stack([np.ones(n), y_lag[1:], d_lag])
    yv = dy[1:]
    try:
        beta, *_ = np.linalg.lstsq(X, yv, rcond=None)
        resid = yv - X @ beta
        dof = n - X.shape[1]
        sigma2 = np.sum(resid ** 2) / dof
        xtx_inv = np.linalg.inv(X.T @ X)
        se = np.sqrt(sigma2 * xtx_inv[1, 1])
        t_stat = beta[1] / se
        return t_stat, False
    except Exception:
        return np.nan, False


def engle_granger(y, x):
    """OLS hedge ratio (y ~ a + b*x), ADF test on residual spread."""
    X = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    intercept, hedge_ratio = beta
    spread = y - (intercept + hedge_ratio * x)
    t_stat, exact = adf_tstat(pd.Series(spread))
    return hedge_ratio, intercept, t_stat, exact, spread


def half_life(spread):
    s = np.asarray(spread)
    s = s[~np.isnan(s)]
    if len(s) < 30:
        return np.nan
    s_lag = s[:-1]
    s_t = s[1:]
    X = np.column_stack([np.ones(len(s_lag)), s_lag])
    try:
        beta, *_ = np.linalg.lstsq(X, s_t, rcond=None)
    except Exception:
        return np.nan
    b = beta[1]
    if b <= 0 or b >= 1:
        return np.nan
    return -np.log(2) / np.log(b)


print(f'statsmodels available: {HAVE_STATSMODELS} '
      f'({"exact ADF p-values" if HAVE_STATSMODELS else "using approximate MacKinnon critical values"})\n')

prices = {}
for sym in FILES:
    d = load_daily_close(sym)
    if d is not None:
        prices[sym] = np.log(d)
        print(f'  {sym}: {len(d)} daily bars, {d.index[0].date()} -> {d.index[-1].date()}')
    else:
        print(f'  {sym}: FILE NOT FOUND, skipped')

print(f'\n{"="*110}')
print(f'  {"Pair":<18} {"N(full)":>8} {"corr(full)":>11} {"N(form)":>8} {"ADF t-stat":>11} '
      f'{"vs 5% crit":>10} {"half-life(d)":>12} {"HL post-formation":>18}')
print(f'{"="*110}')

results = []
for a, b in PAIRS:
    if a not in prices or b not in prices:
        print(f'  {a}-{b:<12} SKIPPED (missing data)')
        continue
    df = pd.concat([prices[a], prices[b]], axis=1, join='inner')
    df.columns = [a, b]
    df = df.dropna()
    n = len(df)
    if n < 100:
        print(f'  {a}-{b:<12} SKIPPED (only {n} overlapping daily bars)')
        continue
    full_corr = df[a].corr(df[b])

    form_end = df.index[int(n * 0.50)]
    form = df[df.index < form_end]
    post = df[df.index >= form_end]

    hedge_ratio, intercept, t_stat, exact, form_spread = engle_granger(form[a].values, form[b].values)
    hl_form = half_life(form_spread)

    post_spread = post[a].values - (intercept + hedge_ratio * post[b].values)
    hl_post = half_life(post_spread)

    crit_label = 'exact' if exact else 'approx'
    sig = 'COINTEGRATED' if t_stat < EG_CRIT['5%'] else 'not sig.'
    print(f'  {a}-{b:<12} {n:>8} {full_corr:>+11.4f} {len(form):>8} {t_stat:>11.3f} '
          f'{EG_CRIT["5%"]:>10.2f} {hl_form:>12.1f} {hl_post:>18.1f}   [{crit_label}, {sig}]')

    results.append(dict(pair=f'{a}-{b}', n=n, corr=full_corr, n_form=len(form),
                         hedge_ratio=hedge_ratio, intercept=intercept, adf_t=t_stat,
                         cointegrated_5pct=t_stat < EG_CRIT['5%'], hl_formation=hl_form,
                         hl_post_formation=hl_post))

print(f'\n{"="*110}')
print('  Interpretation:')
print('  - ADF t-stat more negative than the 5% critical value => reject the null of a unit root')
print('    => spread is statistically stationary (mean-reverting) in the FORMATION period.')
print('  - half-life(d) = formation-period estimated half-life in trading days (AR(1)-based, itself')
print('    subject to the documented OLS speed-bias -- treat as approximate, not precise.')
print('  - "HL post-formation" applies the FIXED formation hedge ratio to Validation+Final-OOS data.')
print('    If this comes back NaN/negative/wildly different from the formation half-life, the')
print('    relationship likely broke down out-of-sample -- exactly what Phase 4-5 needs to know')
print('    before building any strategy on this pair.')

print('\nDone.')
