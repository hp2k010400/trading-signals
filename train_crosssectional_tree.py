"""
train_crosssectional_tree.py

Same cross-sectional long-short setup as train_crosssectional.py (which
failed the permutation test — 72% vs the 90% bar needed) — ONE change:
a shallow random forest instead of logistic regression.

Why this might behave differently: logistic regression can only find
LINEAR relationships between each feature and the outcome. A tree-based
model can capture interactions a linear model structurally cannot
represent — e.g. "momentum only predicts when volatility is low AND
positioning agrees," rather than each feature contributing independently.

Deliberately kept SHALLOW (max_depth=3) and conservatively sized
(min_samples_leaf=20) — a deep, unconstrained forest on a dataset this
size is exactly how you manufacture a convincing false positive. If a
shallow, constrained tree model can't find anything either, that's a
real, informative answer, not a failure to try hard enough.

Same discipline as everything else: expanding-window walk-forward,
genuinely untouched final holdout, permutation test against random
shuffles on the actual holdout (not just a vs-baseline comparison).

Run in Codespace: python -u train_crosssectional_tree.py
(needs features_weekly.csv from build_features.py, and scikit-learn)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from sklearn.ensemble import RandomForestClassifier

FEATURES = ['mom_1m','mom_3m','mom_6m','mom_12m','atr_pct','rsi_14','cot_z','rate_diff']
FINAL_HOLDOUT_START = pd.Timestamp('2025-02-01', tz='UTC')
WEEKLY_COST = 0.0005
MIN_INSTRUMENTS_PER_WEEK = 8

RF_PARAMS = dict(n_estimators=200, max_depth=3, min_samples_leaf=20,
                  random_state=42, n_jobs=-1)

df = pd.read_csv('features_weekly.csv', parse_dates=['date'])
df['date'] = pd.to_datetime(df['date'], utc=True)

for f in ['cot_z', 'rate_diff']:
    df[f + '_missing'] = df[f].isna().astype(int)
    df[f] = df[f].fillna(0)

FEATURES_FULL = FEATURES + ['cot_z_missing', 'rate_diff_missing']
df = df.dropna(subset=FEATURES_FULL + ['fwd_ret_1w'])

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
print(f'Cross-sectional target base rate: {df["y"].mean():.3f}')
print(f'Model: RandomForest({RF_PARAMS})')


def long_short_pnl(sub, proba):
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
        weekly_pnl.append((long_ret + short_ret) / 2)
    return np.array(weekly_pnl)


def pf_of(pnl):
    w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
    return w / l if l > 0 else np.nan


print(f'\n{"="*74}')
print('  WALK-FORWARD — cross-sectional long-short, random forest')
print(f'{"="*74}')

years = sorted(dev['date'].dt.year.unique())
fold_results = []
for test_year in years[2:]:
    train = dev[dev['date'].dt.year < test_year]
    test = dev[dev['date'].dt.year == test_year]
    if len(train) < 100 or len(test) < 10:
        continue

    model = RandomForestClassifier(**RF_PARAMS)
    model.fit(train[FEATURES_FULL], train['y'])
    proba = model.predict_proba(test[FEATURES_FULL])[:, 1]

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
model_full = RandomForestClassifier(**RF_PARAMS)
model_full.fit(dev[FEATURES_FULL], dev['y'])
for feat, imp in sorted(zip(FEATURES_FULL, model_full.feature_importances_), key=lambda x: -x[1]):
    print(f'  {feat:<16} {imp:.4f}')

print(f'\n{"="*74}')
print('  FINAL HOLDOUT — touched ONCE, this is the real answer')
print(f'{"="*74}')
if len(holdout) < 50:
    print(f'  Only {len(holdout)} holdout rows — too thin to mean anything, skipping.')
else:
    proba_h = model_full.predict_proba(holdout[FEATURES_FULL])[:, 1]
    weekly_pnl_h = long_short_pnl(holdout, proba_h)
    pf_h = pf_of(weekly_pnl_h)
    print(f'  weeks={len(weekly_pnl_h)}  PF={pf_h:.2f}  '
          f'mean_weekly_ret={weekly_pnl_h.mean():+.4f} (std={weekly_pnl_h.std():.4f})  '
          f'total_ret={weekly_pnl_h.sum():+.3f}')

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
