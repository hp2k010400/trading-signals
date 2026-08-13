"""
edge32_risk_overlay_test.py

Full frozen test of EDGE32 as a volatility-managed-portfolio risk
overlay, per EDGE32_RISK_OVERLAY_PREREGISTRATION.md. Compares four
variants (A constant / B ES-own-vol / C EDGE32 NQ-vol / D combined)
on a fair, equal-average-risk basis. Central question: does C add
value over B (incremental information beyond ES's own trailing vol)?
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')
from scipy import stats as sstats

TARGET_VOLS = [0.10, 0.15, 0.20]
PRIMARY_TARGET_VOL = 0.15
VOL_MEDIAN_WINDOW = 60
ES_VOL_LOOKBACK = 20
BOUNDS = (0.5, 2.0)  # multiples of Variant A's fixed fraction
PUBLISH_LAG_DAYS = 1
COST_POINTS_ES = 0.6
BASE_COST_MULT = 1.5
COST_STRESS_LEVELS = [1.0, 1.5, 2.0, 3.0]
START_BAL = 70000.0
TRADING_DAYS_YEAR = 252


def load_daily():
    df = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'volume', 'symbol'])
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    return df.groupby(['symbol', 'date']).agg(close=('close', 'last'), volume=('volume', 'sum')).reset_index()


print('Loading and constructing signals...')
daily = load_daily()
es = daily[daily['symbol'] == 'ES.n.0'].sort_values('date').reset_index(drop=True)
nq = daily[daily['symbol'] == 'NQ.n.0'].sort_values('date').reset_index(drop=True)

es['ret'] = np.log(es['close'] / es['close'].shift(1))
es['vol20_ann'] = es['ret'].rolling(ES_VOL_LOOKBACK).std() * np.sqrt(TRADING_DAYS_YEAR)

nq['vol_median60'] = nq['volume'].rolling(VOL_MEDIAN_WINDOW).median()
nq['volume_shock'] = nq['volume'] / nq['vol_median60']
nq['volume_shock_expanding_mean'] = nq['volume_shock'].expanding(min_periods=VOL_MEDIAN_WINDOW).mean()

m = pd.merge(es[['date', 'close', 'ret', 'vol20_ann']],
             nq[['date', 'volume_shock', 'volume_shock_expanding_mean']], on='date', how='inner')
m = m.dropna().reset_index(drop=True)
m['signal_available_date'] = m['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)

# predicted vol for C and D (mechanical, no fitted coefficients)
m['pred_vol_C'] = m['vol20_ann'] * (m['volume_shock'] / m['volume_shock_expanding_mean'])
m['pred_vol_D'] = np.sqrt(m['vol20_ann'] * m['pred_vol_C'])

print(f'  {len(m)} usable daily observations, {m["date"].min().date()} -> {m["date"].max().date()}')

n = len(m)
disc_end = m['date'].iloc[int(n * 0.50)]
val_end = m['date'].iloc[int(n * 0.75)]
print(f'  Discovery:  {m["date"].iloc[0].date()} -> {disc_end.date()}')
print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
print(f'  Final OOS:  {val_end.date()} -> {m["date"].iloc[-1].date()}')


def build_variants(m, target_vol):
    disc_mask = m['date'] < disc_end
    fixed_fraction_A = target_vol / m.loc[disc_mask, 'vol20_ann'].mean()  # calibrated on Discovery only

    lo, hi = BOUNDS[0] * fixed_fraction_A, BOUNDS[1] * fixed_fraction_A

    frac_A = np.full(len(m), fixed_fraction_A)
    frac_B = np.clip(target_vol / m['vol20_ann'].values, lo, hi)
    frac_C = np.clip(target_vol / m['pred_vol_C'].values, lo, hi)
    frac_D = np.clip(target_vol / m['pred_vol_D'].values, lo, hi)

    # signal known at t, applied to the NEXT trading day's return (1-day lag already in signal_available_date,
    # but for a daily-rebalanced series we simply lag the fraction by one row to avoid using day t's own
    # close-to-close return with a same-day-computed fraction)
    out = pd.DataFrame({'date': m['date'], 'ret': m['ret'],
                         'frac_A': frac_A, 'frac_B': frac_B, 'frac_C': frac_C, 'frac_D': frac_D})
    for col in ['frac_A', 'frac_B', 'frac_C', 'frac_D']:
        out[col] = out[col].shift(1)  # position decided using info through t-1, applied to day t's return
    out = out.dropna().reset_index(drop=True)
    return out, fixed_fraction_A


def compute_costed_returns(out, cost_mult):
    results = {}
    for label in ['A', 'B', 'C', 'D']:
        frac = out[f'frac_{label}'].values
        turnover = np.abs(np.diff(frac, prepend=frac[0]))
        gross_ret = frac * out['ret'].values
        # cost per unit of turnover in the position FRACTION, in return terms, using COST_POINTS_ES
        # relative to a representative ES price level (~5000, mid-sample) -- avoids needing the exact
        # daily price for a fraction-space cost, consistent in magnitude with the point-cost convention
        # used throughout this research programme
        cost_ret = turnover * (COST_POINTS_ES / 5000.0)
        net_ret = gross_ret - cost_ret * cost_mult
        results[label] = {'gross_ret': gross_ret, 'net_ret': net_ret, 'frac': frac, 'turnover': turnover}
    return results


def stats_block(net_ret, frac, label=''):
    ann_ret = net_ret.mean() * TRADING_DAYS_YEAR
    ann_vol = net_ret.std() * np.sqrt(TRADING_DAYS_YEAR)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    downside = net_ret[net_ret < 0]
    sortino = ann_ret / (downside.std() * np.sqrt(TRADING_DAYS_YEAR)) if len(downside) and downside.std() > 0 else 0.0
    equity = (1 + pd.Series(net_ret)).cumprod()
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    max_dd = dd.min()
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0.0
    worst_day = net_ret.min()
    return dict(CAGR=ann_ret, AnnVol=ann_vol, Sharpe=sharpe, Sortino=sortino, MaxDD=max_dd,
                Calmar=calmar, WorstDay=worst_day, AvgExposure=frac.mean())


def print_stats_row(label, s):
    print(f'  {label:<12} CAGR={s["CAGR"]*100:>+7.2f}%  AnnVol={s["AnnVol"]*100:>6.2f}%  Sharpe={s["Sharpe"]:>+6.3f}  '
          f'Sortino={s["Sortino"]:>+6.3f}  MaxDD={s["MaxDD"]*100:>7.2f}%  Calmar={s["Calmar"]:>+6.3f}  '
          f'WorstDay={s["WorstDay"]*100:>+6.2f}%  AvgExp={s["AvgExposure"]*100:>6.1f}%')


print(f'\n{"#"*100}\n  PRIMARY RESULT (TARGET_ANN_VOL = {PRIMARY_TARGET_VOL*100:.0f}%, base cost)\n{"#"*100}')
out, fixed_frac_A = build_variants(m, PRIMARY_TARGET_VOL)
res = compute_costed_returns(out, BASE_COST_MULT)

print(f'\n  Variant A fixed fraction (calibrated on Discovery only): {fixed_frac_A:.3f}')
print(f'\n  --- FULL HISTORY (net of base costs) ---')
for label, name in [('A', 'A (constant)'), ('B', 'B (ES-own-vol)'), ('C', 'C (EDGE32 NQ-vol)'), ('D', 'D (combined)')]:
    s = stats_block(res[label]['net_ret'], res[label]['frac'])
    print_stats_row(name, s)

out['year'] = out['date'].dt.year
print(f'\n  --- BY YEAR (net of base costs) ---')
for year in sorted(out['year'].unique()):
    mask = (out['year'] == year).values
    print(f'  {year}:')
    for label, name in [('A', '  A'), ('B', '  B'), ('C', '  C'), ('D', '  D')]:
        r = res[label]['net_ret'][mask]
        f = res[label]['frac'][mask]
        if len(r) < 5:
            continue
        s = stats_block(r, f)
        print_stats_row(name, s)

print(f'\n  --- BY PERIOD (net of base costs) ---')
for plabel, mask in [('DISCOVERY', (out['date'] < disc_end).values),
                      ('VALIDATION', ((out['date'] >= disc_end) & (out['date'] < val_end)).values),
                      ('FINAL OOS', (out['date'] >= val_end).values)]:
    print(f'  {plabel}:')
    for label, name in [('A', '  A'), ('B', '  B'), ('C', '  C'), ('D', '  D')]:
        r = res[label]['net_ret'][mask]
        f = res[label]['frac'][mask]
        s = stats_block(r, f)
        print_stats_row(name, s)

# beta to ES
for label, name in [('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D')]:
    beta, alpha = np.polyfit(out['ret'].values, res[label]['net_ret'], 1)
    print(f'  Beta to ES ({name}): {beta:+.4f}   Daily alpha: {alpha*10000:+.3f}bp')

# ============================================================
# Incremental value: C vs B
# ============================================================
print(f'\n{"#"*100}\n  INCREMENTAL VALUE TEST: C (EDGE32) vs B (ES-own-vol only)\n{"#"*100}')
excess = res['C']['net_ret'] - res['B']['net_ret']
mean_excess = excess.mean() * TRADING_DAYS_YEAR
t_stat, p_val = sstats.ttest_1samp(excess, 0)
print(f'  Mean daily excess return (C - B), annualized: {mean_excess*100:+.3f}%   t-stat={t_stat:+.3f}  p={p_val:.4f}')

# block bootstrap (250 blocks of 20 days)
rng_bb = np.random.default_rng(32)
block_len = 20
n_blocks_needed = int(np.ceil(len(excess) / block_len))
boot_means = []
for _ in range(500):
    starts = rng_bb.integers(0, len(excess) - block_len, size=n_blocks_needed)
    sample = np.concatenate([excess[s:s + block_len] for s in starts])[:len(excess)]
    boot_means.append(sample.mean() * TRADING_DAYS_YEAR)
boot_means = np.array(boot_means)
ci_lo, ci_hi = np.percentile(boot_means, [2.5, 97.5])
print(f'  Block-bootstrap 95% CI on annualized excess (C-B): [{ci_lo*100:+.3f}%, {ci_hi*100:+.3f}%]')
print(f'  {"Excludes zero -- incremental value supported" if ci_lo > 0 or ci_hi < 0 else "Includes zero -- NO incremental value established"}')

sharpe_B = stats_block(res['B']['net_ret'], res['B']['frac'])['Sharpe']
sharpe_C = stats_block(res['C']['net_ret'], res['C']['frac'])['Sharpe']
print(f'\n  Sharpe B (ES-own-vol): {sharpe_B:+.3f}   Sharpe C (EDGE32): {sharpe_C:+.3f}   Delta: {sharpe_C-sharpe_B:+.3f}')

# permutation: circular-shift the NQ volume_shock series specifically, rebuild C, compare Sharpe delta
print(f'\n  --- Permutation test (circular-shift NQ volume_shock, 500 shifts) ---')
rng_perm = np.random.default_rng(320)
shock_vals = m['volume_shock'].values
shock_mean_exp = m['volume_shock_expanding_mean'].values
vol20 = m['vol20_ann'].values
null_deltas = []
for _ in range(500):
    shift = rng_perm.integers(1, len(shock_vals))
    shock_shift = np.roll(shock_vals, shift)
    pred_vol_C_null = vol20 * (shock_shift / shock_mean_exp)
    m_null = m.copy()
    m_null['pred_vol_C'] = pred_vol_C_null
    m_null['pred_vol_D'] = np.sqrt(m_null['vol20_ann'] * m_null['pred_vol_C'])
    out_null, _ = build_variants(m_null, PRIMARY_TARGET_VOL)
    res_null = compute_costed_returns(out_null, BASE_COST_MULT)
    s_c_null = stats_block(res_null['C']['net_ret'], res_null['C']['frac'])['Sharpe']
    s_b_null = stats_block(res_null['B']['net_ret'], res_null['B']['frac'])['Sharpe']
    null_deltas.append(s_c_null - s_b_null)
null_deltas = np.array(null_deltas)
real_delta = sharpe_C - sharpe_B
pct = (null_deltas < real_delta).mean() * 100
print(f'  Real Sharpe delta (C-B): {real_delta:+.4f}')
print(f'  Null distribution: mean={null_deltas.mean():+.4f}  std={null_deltas.std():.4f}')
print(f'  Real result percentile: {pct:.1f}%')

# ============================================================
# Parameter robustness: TARGET_ANN_VOL in {10,15,20}%
# ============================================================
print(f'\n{"#"*100}\n  PARAMETER ROBUSTNESS: TARGET_ANN_VOL sweep (not optimized)\n{"#"*100}')
for tv in TARGET_VOLS:
    out_tv, _ = build_variants(m, tv)
    res_tv = compute_costed_returns(out_tv, BASE_COST_MULT)
    s_b = stats_block(res_tv['B']['net_ret'], res_tv['B']['frac'])
    s_c = stats_block(res_tv['C']['net_ret'], res_tv['C']['frac'])
    marker = '  <-- PRIMARY' if tv == PRIMARY_TARGET_VOL else ''
    print(f'  TARGET_ANN_VOL={tv*100:.0f}%{marker}   B Sharpe={s_b["Sharpe"]:+.3f}  C Sharpe={s_c["Sharpe"]:+.3f}  Delta={s_c["Sharpe"]-s_b["Sharpe"]:+.3f}')

# ============================================================
# Cost stress
# ============================================================
print(f'\n{"#"*100}\n  COST STRESS\n{"#"*100}')
for stress in COST_STRESS_LEVELS:
    total_mult = BASE_COST_MULT * stress
    res_cs = compute_costed_returns(out, total_mult)
    s_b = stats_block(res_cs['B']['net_ret'], res_cs['B']['frac'])
    s_c = stats_block(res_cs['C']['net_ret'], res_cs['C']['frac'])
    label = f'x{total_mult:.2f}' + (' [BASE]' if stress == 1.0 else '')
    print(f'  Cost {label:<12} B Sharpe={s_b["Sharpe"]:+.3f}  C Sharpe={s_c["Sharpe"]:+.3f}  Delta={s_c["Sharpe"]-s_b["Sharpe"]:+.3f}')

print('\nDone.')
