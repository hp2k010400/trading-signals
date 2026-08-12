"""
train_walkforward.py

Step 2: train a SIMPLE model (logistic regression first — deliberately
not gradient boosting or a neural net) on features_weekly.csv, with
proper expanding-window walk-forward validation, and a genuinely
untouched final holdout.

Why logistic regression first: it's the model least likely to manufacture
a false positive from noise on a dataset this size. If it can't find
anything, that's real information before reaching for something more
flexible (and more overfitting-prone).

Validation design:
  - FOLDS: expanding window. Train on all data up to year Y, test ONLY
    on year Y+1, roll forward. Every fold's test set is data the model
    has never seen during that fold's training. This is what a single
    train/test split can't give you — performance across MULTIPLE
    distinct out-of-sample periods, not one lucky/unlucky split.
  - FINAL HOLDOUT: the last 12-18 months are never touched during
    walk-forward fold selection or feature iteration — reported once,
    at the end, same rule as every strategy tested tonight.

Target: binary direction of fwd_ret_1w (up/down). Missing cot_z/
rate_diff are imputed to 0 (neutral) with an explicit "was missing"
flag added — informative missingness (e.g. "this is an index, not FX")
shouldn't be silently dropped or treated as a real zero.

Metrics reported: accuracy, and — more importantly for trading — the
PF-equivalent if you sized every predicted-up week long and every
predicted-down week short, using the actual fwd_ret_1w magnitude. A
model can be "accurate" and still not tradeable if its edge is too
small to survive costs; this makes that visible directly instead of
hiding behind an accuracy number.

Run in Codespace: python -u train_walkforward.py
(requires: pip install scikit-learn, if not already available)
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

FEATURES = ['mom_1m','mom_3m','mom_6m','mom_12m','atr_pct','rsi_14','cot_z','rate_diff']
FINAL_HOLDOUT_START = pd.Timestamp('2025-02-01', tz='UTC')   # same date used all night, for consistency
WEEKLY_COST = 0.0005   # rough round-trip cost estimate as a fraction of price, per weekly rebalance —
                       # approximate, not instrument-specific, but zero would be dishonest

df = pd.read_csv('features_weekly.csv', parse_dates=['date'])
df['date'] = pd.to_datetime(df['date'], utc=True)

# missingness flags BEFORE imputing — informative (e.g. "this is an index, no COT/carry")
for f in ['cot_z', 'rate_diff']:
    df[f + '_missing'] = df[f].isna().astype(int)
    df[f] = df[f].fillna(0)

FEATURES_FULL = FEATURES + ['cot_z_missing', 'rate_diff_missing']
df = df.dropna(subset=FEATURES_FULL + ['fwd_ret_1w'])
df['y'] = (df['fwd_ret_1w'] > 0).astype(int)

df = df.sort_values('date').reset_index(drop=True)

dev = df[df['date'] < FINAL_HOLDOUT_START].copy()
holdout = df[df['date'] >= FINAL_HOLDOUT_START].copy()

print(f'Development set: {len(dev)} rows, {dev["date"].min().date()} to {dev["date"].max().date()}')
print(f'Final holdout:   {len(holdout)} rows, {holdout["date"].min().date() if len(holdout) else "N/A"} '
      f'to {holdout["date"].max().date() if len(holdout) else "N/A"} — NOT touched until the end')

years = sorted(dev['date'].dt.year.unique())
if len(years) < 4:
    print(f'\nWARNING: only {len(years)} years in dev set — walk-forward folds will be thin. '
          f'Treat results as low-confidence regardless of what they show.')

print(f'\n{"="*74}')
print('  WALK-FORWARD (expanding window, one fold per year)')
print(f'{"="*74}')

fold_results = []
for test_year in years[2:]:   # need at least ~2 years of training history before the first test fold
    train = dev[dev['date'].dt.year < test_year]
    test = dev[dev['date'].dt.year == test_year]
    if len(train) < 100 or len(test) < 10:
        continue

    scaler = StandardScaler()
    Xtr = scaler.fit_transform(train[FEATURES_FULL])
    Xte = scaler.transform(test[FEATURES_FULL])

    model = LogisticRegression(max_iter=1000, C=1.0)
    model.fit(Xtr, train['y'])

    pred = model.predict(Xte)
    acc = (pred == test['y'].values).mean()

    # PF-equivalent: go long predicted-up, short predicted-down, size = actual fwd return magnitude
    direction = np.where(pred == 1, 1, -1)
    pnl = direction * test['fwd_ret_1w'].values - WEEKLY_COST
    wins = pnl[pnl > 0].sum(); losses = abs(pnl[pnl < 0].sum())
    pf = wins / losses if losses > 0 else np.nan

    fold_results.append({'year': test_year, 'n': len(test), 'acc': acc, 'pf': pf, 'total_ret': pnl.sum()})
    print(f'  {test_year}: train_n={len(train):>5}  test_n={len(test):>4}  '
          f'accuracy={acc:.3f}  PF-equiv={pf:.2f}  total_ret={pnl.sum():+.3f}')

if fold_results:
    fr = pd.DataFrame(fold_results)
    print(f'\n  Mean accuracy across folds: {fr["acc"].mean():.3f}  (0.500 = coin flip)')
    print(f'  Mean PF-equiv across folds: {fr["pf"].mean():.2f}')
    print(f'  Folds with PF > 1.0: {(fr["pf"] > 1.0).sum()} / {len(fr)}')

print(f'\n{"="*74}')
print('  FEATURE IMPORTANCE (from a model trained on ALL dev data — for inspection only,')
print('  NOT the model used in the walk-forward folds above)')
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
if len(holdout) < 20:
    print(f'  Only {len(holdout)} holdout rows — too thin to mean anything, skipping.')
else:
    Xh = scaler_full.transform(holdout[FEATURES_FULL])
    pred_h = model_full.predict(Xh)
    acc_h = (pred_h == holdout['y'].values).mean()
    direction_h = np.where(pred_h == 1, 1, -1)
    pnl_h = direction_h * holdout['fwd_ret_1w'].values - WEEKLY_COST
    wins_h = pnl_h[pnl_h > 0].sum(); losses_h = abs(pnl_h[pnl_h < 0].sum())
    pf_h = wins_h / losses_h if losses_h > 0 else np.nan
    print(f'  N={len(holdout)}  accuracy={acc_h:.3f}  PF-equiv={pf_h:.2f}  total_ret={pnl_h.sum():+.3f}')

print('\nDone.')
