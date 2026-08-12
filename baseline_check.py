"""
baseline_check.py

Decisive check before trusting train_walkforward.py's result: does the
logistic regression model actually beat a dumb "always predict up"
baseline on the exact same folds and holdout? If not, the model isn't
adding real value — it's just riding this dataset's strong positive
average drift (12-month momentum averaged +14.3%/year across the
2019-2026 sample), the same way an "always long" strategy looks great
in any bull-biased backtest for reasons that have nothing to do with
skill.

Also reports: (1) the model's prediction distribution — if it's calling
"up" on 90%+ of weeks, it's not really discriminating, it's just
mimicking the base rate. (2) per-instrument PF breakdown on the final
holdout — if the result is concentrated in one or two high-drift
instruments (BTCUSD is the obvious suspect) rather than broadly spread,
that's not a generalizable signal, it's exposure to one asset's
structural rally.

Run in Codespace: python -u baseline_check.py
(uses the SAME features_weekly.csv and FINAL_HOLDOUT_START as
train_walkforward.py — run that first)
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

df = pd.read_csv('features_weekly.csv', parse_dates=['date'])
df['date'] = pd.to_datetime(df['date'], utc=True)

for f in ['cot_z', 'rate_diff']:
    df[f + '_missing'] = df[f].isna().astype(int)
    df[f] = df[f].fillna(0)

FEATURES_FULL = FEATURES + ['cot_z_missing', 'rate_diff_missing']
df = df.dropna(subset=FEATURES_FULL + ['fwd_ret_1w'])
df['y'] = (df['fwd_ret_1w'] > 0).astype(int)
df = df.sort_values('date').reset_index(drop=True)

dev = df[df['date'] < FINAL_HOLDOUT_START].copy()
holdout = df[df['date'] >= FINAL_HOLDOUT_START].copy()

def pf_of(pnl):
    w = pnl[pnl > 0].sum(); l = abs(pnl[pnl < 0].sum())
    return w / l if l > 0 else np.nan

print(f'Base rate: {df["y"].mean():.3f} of all weeks are up (this is what "always predict up" exploits)')

print(f'\n{"="*74}')
print('  MODEL vs "ALWAYS UP" BASELINE — same folds as train_walkforward.py')
print(f'{"="*74}')
years = sorted(dev['date'].dt.year.unique())
for test_year in years[2:]:
    train = dev[dev['date'].dt.year < test_year]
    test = dev[dev['date'].dt.year == test_year]
    if len(train) < 100 or len(test) < 10: continue

    scaler = StandardScaler()
    Xtr = scaler.fit_transform(train[FEATURES_FULL])
    Xte = scaler.transform(test[FEATURES_FULL])
    model = LogisticRegression(max_iter=1000, C=1.0)
    model.fit(Xtr, train['y'])
    pred = model.predict(Xte)

    pct_up = (pred == 1).mean()
    model_acc = (pred == test['y'].values).mean()
    model_pnl = np.where(pred == 1, 1, -1) * test['fwd_ret_1w'].values - WEEKLY_COST
    model_pf = pf_of(model_pnl)

    baseline_acc = (test['y'].values == 1).mean()   # "always up" is correct whenever y==1
    baseline_pnl = test['fwd_ret_1w'].values - WEEKLY_COST   # always long
    baseline_pf = pf_of(baseline_pnl)

    print(f'  {test_year}: model_acc={model_acc:.3f} model_PF={model_pf:.2f} '
          f'(predicts UP {pct_up*100:.0f}% of weeks)  |  '
          f'baseline_acc={baseline_acc:.3f} baseline_PF={baseline_pf:.2f}')

print(f'\n{"="*74}')
print('  MODEL vs "ALWAYS UP" BASELINE — final holdout')
print(f'{"="*74}')
scaler_full = StandardScaler()
X_full = scaler_full.fit_transform(dev[FEATURES_FULL])
model_full = LogisticRegression(max_iter=1000, C=1.0)
model_full.fit(X_full, dev['y'])

Xh = scaler_full.transform(holdout[FEATURES_FULL])
pred_h = model_full.predict(Xh)
pct_up_h = (pred_h == 1).mean()
model_acc_h = (pred_h == holdout['y'].values).mean()
model_pnl_h = np.where(pred_h == 1, 1, -1) * holdout['fwd_ret_1w'].values - WEEKLY_COST
model_pf_h = pf_of(model_pnl_h)

baseline_acc_h = (holdout['y'].values == 1).mean()
baseline_pnl_h = holdout['fwd_ret_1w'].values - WEEKLY_COST
baseline_pf_h = pf_of(baseline_pnl_h)

print(f'  Model:    acc={model_acc_h:.3f}  PF={model_pf_h:.2f}  (predicts UP {pct_up_h*100:.0f}% of weeks)')
print(f'  Baseline: acc={baseline_acc_h:.3f}  PF={baseline_pf_h:.2f}  (always predicts up)')
if model_pf_h <= baseline_pf_h + 0.05:
    print('  -> Model does NOT meaningfully beat "always long". This is drift, not a learned signal.')
else:
    print('  -> Model beats the baseline. Worth checking per-instrument concentration next.')

print(f'\n{"="*74}')
print('  PER-INSTRUMENT holdout PF (model predictions) — checking concentration')
print(f'{"="*74}')
holdout = holdout.copy()
holdout['pred'] = pred_h
holdout['pnl'] = model_pnl_h
for inst, grp in holdout.groupby('instrument'):
    n = len(grp); pf = pf_of(grp['pnl'].values)
    print(f'  {inst:<8} N={n:>4}  PF={pf:.2f}  total_ret={grp["pnl"].sum():+.3f}')

print('\nDone.')
