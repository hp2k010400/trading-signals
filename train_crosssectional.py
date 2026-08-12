"""
train_crosssectional.py

The fix for what train_walkforward.py exposed: that model just learned
to predict "up" 91-96% of the time and barely beat a dumb "always long"
baseline — it was riding this dataset's shared 2019-2026 drift, not
finding real structure.

This version predicts something genuinely different: does this
instrument OUTPERFORM the cross-sectional median that week, not whether
it goes up in absolute terms. And it trades that as an actual
market-neutral portfolio — long the top third of instruments by
predicted probability, short the bottom third, equal weight — rather
than per-instrument directional calls. Being long AND short every week
in roughly equal size cancels the shared market factor at the PORTFOLIO
level too, not just in how the label was defined. Double protection
against the same failure mode.

Same discipline as everything else: expanding-window walk-forward,
genuinely untouched final holdout, feature importance inspected, costs
applied per leg.

Run in Codespace: python -u train_crosssectional.py
(needs features_weekly.csv from build_features.py, and scikit-learn)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

FEATURES = ['mom_1m','mom_3m','mom_6m','mom_12m','atr_pct','rsi_14','cot_z','rate_diff']
FINAL_HOLDOUT_START = pd.Timestamp('2025-02-01', tz='UTC')
WEEKLY_COST = 0.0005
MIN_INSTRUMENTS_PER_WEEK = 8   # need a reasonable cross-section to rank against

df = pd.read_csv('features_weekly.csv', parse_dates=['date'])
df['date'] = pd.to_datetime(df['date'], utc=True)

for f in ['cot_z', 'rate_diff']:
    df[f + '_missing'] = df[f].isna().astype(int)
    df[f] = df[f].fillna(0)

FEATURES_FULL = FEATURES + ['cot_z_missing', 'rate_diff_missing']
df = df.dropna(subset=FEATURES_FULL + ['fwd_ret_1w'])

# cross-sectional target: does this instrument beat the median return THAT WEEK,
# across whatever instruments have data that week — no lookahead, purely contemporaneous
weekly_median = df.groupby('date')['fwd_ret_1w'].transform('median')
weekly_count = df.groupby('date')['date'].transform('count')
df = df[weekly_count >= MIN_INSTRUMENTS_PER_WEEK].copy()
df['excess_ret'] = df['fwd_ret_1w'] - weekly_median
df['y'] = (df['excess_ret'] > 0).astype(int)

df = df.sort_values('date').reset_index(drop=True)
dev = df[df['date'] < FINAL_HOLDOUT_START].copy()
holdout = df[df['date'] >= FINAL_HOLDOUT_START].copy()

print(f'Development set: {len(dev)} rows, {dev["date"].min().date()} to {dev["date"].max().date()}')
print(f'Final holdout:   {len(holdout)} rows — NOT touched until the end')
print(f'Cross-sectional target base rate: {df["y"].mean():.3f} (should be close to 0.5 by construction)')


def long_short_pnl(sub, proba):
    """Rank instruments by predicted probability each week, long top third,
    short bottom third, equal weight, RAW returns (long-short cancels the
    shared drift automatically since both legs are held simultaneously)."""
    sub = sub.copy()
    sub['proba'] = proba
    weekly_pnl = []
    for date, wk in sub.groupby('date'):
        wk = wk.sort_values('proba', ascending=False)
        n = len(wk)
        tercile = max(1, n // 3)
        longs = wk.iloc[:tercile]
        shorts = wk.iloc[-tercile:]
        long_ret = longs['fwd_ret_1w'].mean() - WEEKLY_COST
        short_ret = -shorts['fwd_ret_1w'].mean() - WEEKLY_COST
        weekly_pnl.append((long_ret + short_ret) / 2)   # equal-weighted long+short book
    return np.array(weekly_pnl)


def pf_of(pnl):
    w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
    return w / l if l > 0 else np.nan


print(f'\n{"="*74}')
print('  WALK-FORWARD — cross-sectional long-short portfolio')
print(f'{"="*74}')

years = sorted(dev['date'].dt.year.unique())
fold_results = []
for test_year in years[2:]:
    train = dev[dev['date'].dt.year < test_year]
    test = dev[dev['date'].dt.year == test_year]
    if len(train) < 100 or len(test) < 10:
        continue

    scaler = StandardScaler()
    Xtr = scaler.fit_transform(train[FEATURES_FULL])
    Xte = scaler.transform(test[FEATURES_FULL])
    model = LogisticRegression(max_iter=1000, C=1.0)
    model.fit(Xtr, train['y'])
    proba = model.predict_proba(Xte)[:, 1]

    weekly_pnl = long_short_pnl(test, proba)
    pf = pf_of(weekly_pnl)
    n_weeks = len(weekly_pnl)
    mean_wk = weekly_pnl.mean(); std_wk = weekly_pnl.std()

    fold_results.append({'year': test_year, 'n_weeks': n_weeks, 'pf': pf,
                          'mean_wk_ret': mean_wk, 'total_ret': weekly_pnl.sum()})
    print(f'  {test_year}: weeks={n_weeks:>3}  PF={pf:.2f}  '
          f'mean_weekly_ret={mean_wk:+.4f} (std={std_wk:.4f})  total_ret={weekly_pnl.sum():+.3f}')

if fold_results:
    fr = pd.DataFrame(fold_results)
    print(f'\n  Mean PF across folds: {fr["pf"].mean():.2f}')
    print(f'  Folds with PF > 1.0: {(fr["pf"] > 1.0).sum()} / {len(fr)}')

print(f'\n{"="*74}')
print('  FEATURE IMPORTANCE (trained on ALL dev data, inspection only)')
print(f'{"="*74}')
scaler_full = StandardScaler()
X_full = scaler_full.fit_transform(dev[FEATURES_FULL])
model_full = LogisticRegression(max_iter=1000, C=1.0)
model_full.fit(X_full, dev['y'])
for feat, coef in sorted(zip(FEATURES_FULL, model_full.coef_[0]), key=lambda x: -abs(x[1])):
    print(f'  {feat:<16} {coef:+.4f}')

print(f'\n{"="*74}')
print('  FINAL HOLDOUT — touched ONCE, this is the real answer')
print(f'{"="*74}')
if len(holdout) < 50:
    print(f'  Only {len(holdout)} holdout rows — too thin to mean anything, skipping.')
else:
    Xh = scaler_full.transform(holdout[FEATURES_FULL])
    proba_h = model_full.predict_proba(Xh)[:, 1]
    weekly_pnl_h = long_short_pnl(holdout, proba_h)
    pf_h = pf_of(weekly_pnl_h)
    print(f'  weeks={len(weekly_pnl_h)}  PF={pf_h:.2f}  '
          f'mean_weekly_ret={weekly_pnl_h.mean():+.4f} (std={weekly_pnl_h.std():.4f})  '
          f'total_ret={weekly_pnl_h.sum():+.3f}')

    # random-ranking reference: shuffle predictions, see what "no skill" looks like on THIS holdout
    rng = np.random.default_rng(42)
    random_pfs = []
    for _ in range(200):
        shuffled = rng.permutation(proba_h)
        rnd_pnl = long_short_pnl(holdout, shuffled)
        random_pfs.append(pf_of(rnd_pnl))
    random_pfs = np.array(random_pfs)
    print(f'\n  Random-ranking reference (200 shuffles): mean PF={np.nanmean(random_pfs):.2f}, '
          f'std={np.nanstd(random_pfs):.2f}')
    pctile = (random_pfs < pf_h).mean() * 100
    print(f'  Actual model PF beats {pctile:.0f}% of random shuffles on this exact holdout.')
    if pctile < 90:
        print('  -> Not distinguishable from random ranking. No real signal.')
    else:
        print('  -> Beats random ranking convincingly. Worth a closer look, not yet worth trusting blindly.')

print('\nDone.')
