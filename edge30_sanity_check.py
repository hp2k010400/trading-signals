"""
edge30_sanity_check.py

CAPPED, DIAGNOSTIC-ONLY sanity check for EDGE30, per the frozen spec
in EDGE30_ES_OI_PREREGISTRATION.md. NOT independent validation --
runs on the same 2010-2026 window already observed via EDGE27, using
the corrected (total, full-curve) open interest construction from
edge30_construct_and_validate_oi.py.

This script cannot upgrade EDGE30 past WATCHLIST regardless of result.
No parameter search is performed anywhere in this file.

Frozen parameters (unchanged from EDGE30_ES_OI_PREREGISTRATION.md):
  - OI change window: 21 trading days (~1 month), matching the holding
    period -- this specific number was not pinned separately in the
    original pre-registration; resolved here, before seeing any
    result, as exactly matching the already-committed 1-month holding
    period (a standard symmetric convention: measure the predictor
    over the same horizon as the outcome), not a re-selection from
    EDGE27's tested range.
  - z-score: expanding window (min_periods=252, ~1yr warm-up), no
    fixed lookback parameter.
  - Holding period: 1 calendar month (pd.DateOffset(months=1)).
  - Direction: sign(z), predicted positive.
  - Position sizing: vol-scaled, RISK_PCT=0.30%, cluster-adjusted for
    concurrent overlapping trades (near-daily signal + 1-month hold
    means many trades are open simultaneously -- risk is split across
    however many are open on a given day, not double-counted).
  - Costs: COST_POINTS=0.6 (ES/SP500), BASE_COST_MULT=1.5.
  - Parameter robustness set (pre-specified, not re-optimized):
    holding periods of 1/2/3 months.
  - Null test: circular-shift permutation, 500 shifts (same method
    used throughout this research programme).
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

OI_CHANGE_DAYS = 21
ZSCORE_MIN_PERIODS = 252
PUBLISH_LAG_DAYS = 1
HOLDING_MONTHS_PRIMARY = 1
HOLDING_MONTHS_ROBUSTNESS = [1, 2, 3]
RISK_PCT = 0.30
VOL_LOOKBACK_DAYS = 20
COST_POINTS_ES = 0.6
BASE_COST_MULT = 1.5
COST_STRESS_LEVELS = [1.0, 1.5, 2.0, 3.0]  # on top of BASE_COST_MULT, per this test's explicit request
START_BAL = 70000.0
N_PERM = 500

# ============================================================
# Load validated total OI, ES price, and the frozen discontinuity calendar
# ============================================================
print('Loading validated total OI, ES price, and discontinuity calendar...')
oi = pd.read_csv('es_total_oi_daily.csv', parse_dates=['date'])
oi['date'] = pd.to_datetime(oi['date'], utc=True)
oi = oi.sort_values('date').reset_index(drop=True)

disc = pd.read_csv('edge30_discontinuity_calendar.csv', parse_dates=['discontinuity_date'])
disc['discontinuity_date'] = pd.to_datetime(disc['discontinuity_date'], utc=True)
discontinuity_dates = np.sort(disc['discontinuity_date'].values)  # naive np.datetime64, matches dates_arr below
print(f'  {len(discontinuity_dates)} discontinuity dates loaded (Option A exclusion rule, frozen pre-performance)')

px_raw = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'symbol'])
px_raw = px_raw[px_raw['symbol'] == 'ES.n.0'].copy()
px_raw['ts_event'] = pd.to_datetime(px_raw['ts_event'], utc=True)
px_raw['date'] = px_raw['ts_event'].dt.normalize()
px = px_raw.groupby('date')['close'].last().reset_index().sort_values('date').reset_index(drop=True)

print(f'  OI: {len(oi)} days, {oi["date"].min().date()} -> {oi["date"].max().date()}')
print(f'  Price: {len(px)} days, {px["date"].min().date()} -> {px["date"].max().date()}')

# ============================================================
# Build signal
# ============================================================
oi['oi_change'] = oi['total_oi'] / oi['total_oi'].shift(OI_CHANGE_DAYS) - 1

# ---- Option A exclusion rule (frozen before any performance was examined): ----
# a signal at row i uses total_oi[i] and total_oi[i-OI_CHANGE_DAYS] -- if any
# discontinuity date falls within that window [date_{i-21}, date_i], the
# OI-change measurement is invalid (data-quality exclusion, not a trading filter).
window_start_idx = np.arange(len(oi)) - OI_CHANGE_DAYS
contaminated = np.zeros(len(oi), dtype=bool)
dates_arr = oi['date'].values
for i in range(len(oi)):
    j = window_start_idx[i]
    if j < 0:
        continue
    lo, hi = dates_arr[j], dates_arr[i]
    contaminated[i] = np.any((discontinuity_dates >= lo) & (discontinuity_dates <= hi))
oi['contaminated'] = contaminated
oi['signal_available_date'] = oi['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)

n_before = oi['oi_change'].notna().sum()
n_contaminated = int((oi['contaminated'] & oi['oi_change'].notna()).sum())
print(f'\n  Signal observations with a valid 21-day OI-change window: {n_before}')
print(f'  Excluded as contaminated (window spans a discontinuity date): {n_contaminated} '
      f'({n_contaminated / n_before * 100:.1f}%)')

oi_excluded = oi[oi['contaminated']].copy()  # kept only for the "not concentrated around losing trades" check below
oi = oi[~oi['contaminated']].reset_index(drop=True)

oi['z'] = (oi['oi_change'] - oi['oi_change'].expanding(min_periods=ZSCORE_MIN_PERIODS).mean()) / \
          oi['oi_change'].expanding(min_periods=ZSCORE_MIN_PERIODS).std()
oi = oi.dropna(subset=['z']).reset_index(drop=True)
print(f'\nUsable (clean) signal observations after warm-up: {len(oi)}, '
      f'{oi["date"].min().date()} -> {oi["date"].max().date()}')

px['ret'] = np.log(px['close'] / px['close'].shift(1))
px['vol20'] = px['ret'].rolling(VOL_LOOKBACK_DAYS).std()
px_dates = px['date'].values
px_close = px['close'].values
px_vol = px['vol20'].values


def pos_on_or_after(t):
    p = np.searchsorted(px_dates, np.datetime64(t))
    return p if p < len(px_dates) else -1


# ============================================================
# PHASE 6: descriptive phenomenon test (correlation vs 1-month fwd return)
# ============================================================
print(f'\n{"#"*100}\n  PHASE 6: DESCRIPTIVE TEST (corrected total OI vs 1-month forward ES return)\n{"#"*100}')

rows = []
for _, r in oi.iterrows():
    ep = pos_on_or_after(r['signal_available_date'])
    if ep < 0:
        continue
    target = r['signal_available_date'] + pd.DateOffset(months=1)
    xp = pos_on_or_after(target)
    if xp < 0 or xp <= ep:
        continue
    fwd_ret = np.log(px_close[xp] / px_close[ep])
    rows.append({'date': r['date'], 'entry_date': px['date'].iloc[ep], 'z': r['z'], 'fwd_ret': fwd_ret})

desc = pd.DataFrame(rows)
n = len(desc)

# ---- Sanity check on the EXCLUSION rule itself (not on EDGE30's own performance): ----
# (a) are exclusions spread through the years per the expected quarterly calendar?
# (b) are excluded observations' outcomes suspiciously different from kept ones
#     (e.g. disproportionately excluding what would have been losing trades)?
excl_by_year = oi_excluded['date'].dt.year.value_counts().sort_index()
print(f'\n  --- Sanity check: exclusion-rule distribution (not a performance check) ---')
print(f'  Excluded signal-observations by year (expect ~roughly even, matching quarterly expiry):')
print(f'  {dict(excl_by_year)}')

excl_rows = []
for _, r in oi_excluded.iterrows():
    ep = pos_on_or_after(r['signal_available_date'])
    if ep < 0:
        continue
    target = r['signal_available_date'] + pd.DateOffset(months=1)
    xp = pos_on_or_after(target)
    if xp < 0 or xp <= ep:
        continue
    fwd_ret = np.log(px_close[xp] / px_close[ep])
    excl_rows.append({'date': r['date'], 'oi_change': r['oi_change'], 'fwd_ret': fwd_ret})
excl_desc = pd.DataFrame(excl_rows)
if len(excl_desc) > 5:
    print(f"  Excluded observations' forward-return stats (for comparison, NOT used in EDGE30 itself):")
    print(f'    N={len(excl_desc)}  mean fwd_ret={excl_desc["fwd_ret"].mean()*10000:+.2f}bp  '
          f'%positive={100*(excl_desc["fwd_ret"]>0).mean():.1f}%')
    print(f"  Kept (clean) observations' forward-return stats:")
    print(f'    N={len(desc)}  mean fwd_ret={desc["fwd_ret"].mean()*10000:+.2f}bp  '
          f'%positive={100*(desc["fwd_ret"]>0).mean():.1f}%')
    print(f'  (if these look wildly different, the exclusion rule may be accidentally performance-selective;')
    print(f'   broadly similar distributions support that it is a genuine data-quality rule, not a filter)')

from scipy import stats as sstats
pearson_r, pearson_p = sstats.pearsonr(desc['z'], desc['fwd_ret'])
spearman_r, spearman_p = sstats.spearmanr(desc['z'], desc['fwd_ret'])
# Fisher z CI for Pearson r
fz = np.arctanh(pearson_r)
se = 1 / np.sqrt(n - 3)
ci_lo, ci_hi = np.tanh(fz - 1.96 * se), np.tanh(fz + 1.96 * se)

print(f'  N = {n}')
print(f'  Pearson r  = {pearson_r:+.4f}  (p={pearson_p:.4f}, uncorrected for multiple testing -- see Phase 13)')
print(f'  95% CI on Pearson r (Fisher z): [{ci_lo:+.4f}, {ci_hi:+.4f}]')
print(f'  Spearman rho = {spearman_r:+.4f}  (p={spearman_p:.4f})')
print(f'  Predicted sign: POSITIVE.  Observed sign: {"POSITIVE" if pearson_r > 0 else "NEGATIVE"}')

n_d = len(desc)
disc_end = desc.sort_values('date')['date'].iloc[int(n_d * 0.50)]
val_end = desc.sort_values('date')['date'].iloc[int(n_d * 0.75)]
desc_sorted = desc.sort_values('date').reset_index(drop=True)
print(f'\n  By diagnostic period (NOT new OOS -- same window already observed via EDGE27):')
for label, mask in [('DISCOVERY', desc_sorted['date'] < disc_end),
                     ('VALIDATION', (desc_sorted['date'] >= disc_end) & (desc_sorted['date'] < val_end)),
                     ('FINAL (diag)', desc_sorted['date'] >= val_end)]:
    sub = desc_sorted[mask]
    if len(sub) > 10:
        r, p = sstats.pearsonr(sub['z'], sub['fwd_ret'])
        print(f'    {label:<14} N={len(sub):>5}  Pearson r={r:+.4f}  p={p:.4f}')

print(f'\n  === COMPARISON WITH EDGE27 (contaminated front-month OI) ===')
print(f'  EDGE27 (front-month, 21d change, 4-week horizon): full-history corr +0.0177')
print(f'  EDGE27 by period: Discovery +0.0035, Validation +0.0217, Final OOS +0.0355 (strengthening)')
print(f'  EDGE30 (total curve, 21d change, ~1-month horizon): full-history corr {pearson_r:+.4f}')
print(f'  (direct horizon comparison is approximate: EDGE27 used a fixed 28-calendar-day forward window;')
print(f'   EDGE30 uses a calendar-month forward window -- both are the "~1 month" horizon)')

print('\nSaving descriptive results for use in strategy construction...')
desc.to_csv('edge30_descriptive_results.csv', index=False)
print('Continuing through the full requested battery per this instruction (Phases 7-14), despite the')
print('period-instability flag above -- classification is made only at the end, not at Phase 6.')

# ============================================================
# PHASE 7: SIMPLE EXECUTABLE STRATEGY (frozen spec, 1-month holding, no re-tuning)
# ============================================================
print(f'\n{"#"*100}\n  PHASE 7: EXECUTABLE STRATEGY (frozen EDGE30 spec, 1-month holding)\n{"#"*100}')


def build_trades(signal_df, holding_months):
    rows = []
    for _, r in signal_df.iterrows():
        ep = pos_on_or_after(r['signal_available_date'])
        if ep < 0 or np.isnan(px_vol[ep]) or px_vol[ep] <= 0:
            continue
        target = r['signal_available_date'] + pd.DateOffset(months=holding_months)
        xp = pos_on_or_after(target)
        if xp < 0 or xp <= ep:
            continue
        entry_price = px_close[ep]
        exit_price = px_close[xp]
        direction = 1.0 if r['z'] > 0 else -1.0
        raw_log_ret = np.log(exit_price / entry_price)
        signed_ret = direction * raw_log_ret
        period_vol = px_vol[ep] * np.sqrt(21 * holding_months)
        r_gross = signed_ret / period_vol
        cost_r_unit = (COST_POINTS_ES / entry_price) / period_vol
        rows.append({'signal_date': r['date'], 'entry_date': px['date'].iloc[ep], 'exit_date': px['date'].iloc[xp],
                     'z': r['z'], 'direction': direction, 'r_gross': r_gross, 'cost_r_unit': cost_r_unit})
    return pd.DataFrame(rows)


trades = build_trades(oi, HOLDING_MONTHS_PRIMARY)
print(f'  {len(trades)} trades built (1-month holding, frozen spec)')

# concurrent-trade count at each trade's own entry (for cluster risk-sizing --
# near-daily signal + 1-month hold means many trades overlap at any time)
entry_arr = trades['entry_date'].values
exit_arr = trades['exit_date'].values
concurrent = ((entry_arr[:, None] <= entry_arr[None, :]) & (exit_arr[:, None] > entry_arr[None, :])).sum(axis=0)
trades['concurrent_at_entry'] = concurrent
print(f'  Average concurrent open trades at entry: {concurrent.mean():.1f} (used to split RISK_PCT per trade)')

trades['risk_frac_pct'] = RISK_PCT / trades['concurrent_at_entry']
trades['r_net'] = trades['r_gross'] - trades['cost_r_unit'] * BASE_COST_MULT


def compute_stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(N=0, WR=0.0, PF=0.0, GrossPF=0.0, R=0.0, avg=0.0, avg_win=0.0, avg_loss=0.0, sharpe=0.0)
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else float('inf')
    wr = round(len(wins) / len(r) * 100, 2)
    sharpe = round(r.mean() / r.std(), 4) if r.std() > 0 else 0.0
    return dict(N=len(r), WR=wr, PF=pf, R=round(r.sum(), 2), avg=round(r.mean(), 5),
                avg_win=round(wins.mean(), 5) if len(wins) else 0.0,
                avg_loss=round(losses.mean(), 5) if len(losses) else 0.0, sharpe=sharpe)


s_gross = compute_stats(trades['r_gross'].values)
s_net = compute_stats(trades['r_net'].values)
months_span = (trades['entry_date'].max() - trades['entry_date'].min()).days / 30.4
print(f'\n  Trades: {len(trades)}   Trades/month: {len(trades)/months_span:.1f}')
print(f'  GROSS: WR={s_gross["WR"]}%  PF={s_gross["PF"]}  avg_win={s_gross["avg_win"]:+.5f}  avg_loss={s_gross["avg_loss"]:+.5f}  '
      f'expectancy(R)={s_gross["avg"]:+.5f}  total R={s_gross["R"]:+.2f}')
print(f'  NET (base cost): WR={s_net["WR"]}%  PF={s_net["PF"]}  avg_win={s_net["avg_win"]:+.5f}  avg_loss={s_net["avg_loss"]:+.5f}  '
      f'expectancy(R)={s_net["avg"]:+.5f}  total R={s_net["R"]:+.2f}  Sharpe(per-trade)={s_net["sharpe"]:+.4f}')
print(f'  Average holding period: {HOLDING_MONTHS_PRIMARY} calendar month (fixed, per frozen spec)')

# longest losing streak (chronological, by entry date)
trades_sorted = trades.sort_values('entry_date').reset_index(drop=True)
is_loss = (trades_sorted['r_net'] <= 0).values
streak = 0
max_streak = 0
for v in is_loss:
    streak = streak + 1 if v else 0
    max_streak = max(max_streak, streak)
print(f'  Longest losing streak (chronological trade sequence): {max_streak}')

# ---- Cluster-adjusted DAILY $ P&L for Sharpe/Sortino/drawdown/worst-day/worst-month ----
print(f'\n  Building cluster-adjusted daily $ P&L (RISK_PCT split across concurrent trades)...')
px_daily = px[['date', 'close']].copy()
px_daily['ret'] = np.log(px_daily['close'] / px_daily['close'].shift(1))
daily_pnl = pd.Series(0.0, index=px_daily['date'])
px_date_to_idx = {d: i for i, d in enumerate(px_daily['date'])}  # keep as Timestamp, not numpy.datetime64,
                                                                    # to match trades['entry_date']/['exit_date'] dtype

for _, t in trades.iterrows():
    ep = px_date_to_idx.get(t['entry_date'], None)
    xp = px_date_to_idx.get(t['exit_date'], None)
    if ep is None or xp is None or xp <= ep:
        continue
    day_rets = px_daily['ret'].values[ep + 1:xp + 1]
    day_dates = px_daily['date'].iloc[ep + 1:xp + 1].tolist()  # keep as Timestamp list, not numpy.datetime64
    contrib = t['direction'] * day_rets * (t['risk_frac_pct'] / 100.0) * START_BAL
    for d, c in zip(day_dates, contrib):
        daily_pnl[d] += c

daily_cost = trades['concurrent_at_entry'] * 0  # placeholder not used; costs already in r_net for trade-level stats
equity_curve = daily_pnl.cumsum() + START_BAL
daily_ret_pct = daily_pnl / START_BAL

sharpe_daily = daily_ret_pct.mean() / daily_ret_pct.std() * np.sqrt(252) if daily_ret_pct.std() > 0 else 0.0
downside = daily_ret_pct[daily_ret_pct < 0]
sortino_daily = daily_ret_pct.mean() / downside.std() * np.sqrt(252) if len(downside) and downside.std() > 0 else 0.0
running_max = equity_curve.cummax()
drawdown = (equity_curve - running_max) / running_max
max_dd_pct = drawdown.min() * 100
worst_day = daily_pnl.min()
worst_day_date = daily_pnl.idxmin()
monthly_pnl = daily_pnl.groupby(pd.PeriodIndex(daily_pnl.index, freq='M')).sum()
worst_month = monthly_pnl.min()
worst_month_period = monthly_pnl.idxmin()

print(f'  Annualized Sharpe (daily P&L series): {sharpe_daily:+.4f}')
print(f'  Annualized Sortino (daily P&L series): {sortino_daily:+.4f}')
print(f'  Max drawdown: {max_dd_pct:.2f}%')
print(f'  Worst day: £{worst_day:+,.0f} on {pd.Timestamp(worst_day_date).date()}')
print(f'  Worst month: £{worst_month:+,.0f} ({worst_month_period})')
print(f'  Best month: £{monthly_pnl.max():+,.0f} ({monthly_pnl.idxmax()})')
print(f'  Median month: £{monthly_pnl.median():+,.0f}   Mean month: £{monthly_pnl.mean():+,.0f}')
print(f'  Profitable months: {(monthly_pnl > 0).mean()*100:.1f}% ({(monthly_pnl>0).sum()}/{len(monthly_pnl)})')

# ============================================================
# PHASE 8: TEMPORAL BREAKDOWN (diagnostic only -- not new OOS)
# ============================================================
print(f'\n{"#"*100}\n  PHASE 8: TEMPORAL BREAKDOWN (diagnostic only, same window already observed via EDGE27)\n{"#"*100}')
trades['year'] = trades['entry_date'].dt.year
print('\n  --- BY YEAR (net R) ---')
year_rs = {}
for year in sorted(trades['year'].unique()):
    sub = trades[trades['year'] == year]
    s = compute_stats(sub['r_net'].values)
    year_rs[year] = s['R']
    flag = ' <- losing' if s['R'] < 0 else ''
    print(f'    {year}{flag}  N={s["N"]:>4}  WR={s["WR"]:>5.1f}%  PF={s["PF"]:>5.2f}  R={s["R"]:>+8.2f}')

total_R = s_net['R']
best_year = max(year_rs, key=year_rs.get)
best_year_R = year_rs[best_year]
print(f'\n  Total NET R (all years): {total_R:+.2f}')
print(f'  Best single year: {best_year} contributed {best_year_R:+.2f}R')
print(f'  Total EXCLUDING best year: {total_R - best_year_R:+.2f}R  '
      f'{"<-- still positive without the best year" if (total_R - best_year_R) > 0 else "<-- NEGATIVE without the best year (one-year dependence)"}')

n_t = len(trades)
disc_end_t = trades_sorted['entry_date'].iloc[int(n_t * 0.50)]
val_end_t = trades_sorted['entry_date'].iloc[int(n_t * 0.75)]
print(f'\n  --- BY DIAGNOSTIC PERIOD (net R) ---')
for label, mask in [('DISCOVERY', trades_sorted['entry_date'] < disc_end_t),
                     ('VALIDATION', (trades_sorted['entry_date'] >= disc_end_t) & (trades_sorted['entry_date'] < val_end_t)),
                     ('FINAL (diag)', trades_sorted['entry_date'] >= val_end_t)]:
    sub = trades_sorted[mask]
    s = compute_stats(sub['r_net'].values)
    print(f'    {label:<14} N={s["N"]:>5}  WR={s["WR"]:>5.1f}%  PF={s["PF"]:>5.2f}  R={s["R"]:>+8.2f}')

print(f'\n  --- REGIME CHECK: does profitability depend on one exceptional episode? ---')
covid_mask = (trades['entry_date'] >= '2020-02-01') & (trades['entry_date'] <= '2020-06-01')
y2022_mask = (trades['year'] == 2022)
covid_R = trades[covid_mask]['r_net'].sum()
y2022_R = trades[y2022_mask]['r_net'].sum()
print(f'  COVID window (2020-02 to 2020-06) contributed: {covid_R:+.2f}R')
print(f'  2022 (rate-hike bear market) contributed: {y2022_R:+.2f}R')
print(f'  Total excluding COVID window: {total_R - covid_R:+.2f}R')
print(f'  Total excluding 2022: {total_R - y2022_R:+.2f}R')

# ============================================================
# PHASE 9: EQUITY-DRIFT CONTROL (mandatory)
# ============================================================
print(f'\n{"#"*100}\n  PHASE 9: EQUITY-DRIFT CONTROL\n{"#"*100}')

sample_start = trades['entry_date'].min()
sample_end = trades['exit_date'].max()
px_window = px[(px['date'] >= sample_start) & (px['date'] <= sample_end)]
bh_log_ret = np.log(px_window['close'].iloc[-1] / px_window['close'].iloc[0])
bh_years = (px_window['date'].iloc[-1] - px_window['date'].iloc[0]).days / 365.25
print(f'  1. Buy-and-hold ES over the same window ({sample_start.date()} -> {sample_end.date()}): '
      f'{bh_log_ret*100:+.1f}% total, {bh_log_ret/bh_years*100:+.2f}%/yr')

# 2. equivalent long-only exposure: same construction (vol-scaled, same cluster sizing), but ALWAYS long
trades_longonly = trades.copy()
trades_longonly['r_gross_lo'] = np.log(px_close[[pos_on_or_after(d) for d in trades_longonly['exit_date']]] /
                                        px_close[[pos_on_or_after(d) for d in trades_longonly['entry_date']]]) / \
                                 (px_vol[[pos_on_or_after(d) for d in trades_longonly['entry_date']]] * np.sqrt(21))
trades_longonly['r_net_lo'] = trades_longonly['r_gross_lo'] - trades_longonly['cost_r_unit'] * BASE_COST_MULT
lo_stats = compute_stats(trades_longonly['r_net_lo'].values)
print(f'  2. Equivalent LONG-ONLY exposure (same sizing/costs, direction always +1): '
      f'PF={lo_stats["PF"]}  total R={lo_stats["R"]:+.2f}  (EDGE30 total R={total_R:+.2f})')

# 3. random-entry matched benchmark: same entry dates/holding period/position sizing, RANDOM direction
rng_drift = np.random.default_rng(30)
N_RANDOM = 500
random_totals = []
raw_ret_over_vol = trades['r_gross'].values * trades['direction'].values  # direction-free base
cost_component_trades = trades['cost_r_unit'].values * BASE_COST_MULT
for _ in range(N_RANDOM):
    rand_dir = rng_drift.choice([-1.0, 1.0], size=len(trades))
    r_net_rand = rand_dir * raw_ret_over_vol - cost_component_trades
    random_totals.append(r_net_rand.sum())
random_totals = np.array(random_totals)
pct_beats_random = (random_totals < total_R).mean() * 100
print(f'  3. Random-entry/random-direction matched benchmark ({N_RANDOM} draws, same entries/sizing/costs):')
print(f'     Null mean R={random_totals.mean():+.2f}  std={random_totals.std():.2f}')
print(f'     EDGE30 real R ({total_R:+.2f}) beats {pct_beats_random:.1f}% of random-direction draws')

# 4. beta-adjusted: regress daily strategy $ return against daily ES market return
market_ret_aligned = px_daily.set_index('date')['ret'].reindex(daily_pnl.index)
valid = (~daily_ret_pct.isna()) & (~market_ret_aligned.isna())
if valid.sum() > 30:
    beta, alpha_daily = np.polyfit(market_ret_aligned[valid], daily_ret_pct[valid], 1)
    alpha_annualized = alpha_daily * 252
    print(f'  4. Beta-adjusted: strategy daily-return beta to ES = {beta:+.4f}')
    print(f'     Annualized alpha (intercept after removing beta exposure): {alpha_annualized*100:+.2f}%/yr')
    print(f'     {"Alpha is positive after controlling for beta" if alpha_annualized > 0 else "Alpha is NEGATIVE/zero after controlling for beta -- may just be equity drift exposure"}')

print(f'\n  === Phase 9 verdict ===')
print(f'  Does corrected OI add information beyond long-run S&P drift? See beta/alpha and long-only comparison above.')

# ============================================================
# PHASE 10: NULL TEST (pre-specified circular-shift permutation, unchanged from prior candidates)
# ============================================================
print(f'\n{"#"*100}\n  PHASE 10: NULL TEST (circular-shift permutation, {500} shifts -- pre-specified, not changed)\n{"#"*100}')
rng_null = np.random.default_rng(300)
N_PERM = 500
z_vals = trades['z'].values
null_R, null_PF = [], []
for _ in range(N_PERM):
    shift = rng_null.integers(1, len(z_vals))
    z_shift = np.roll(z_vals, shift)
    direction_shift = np.where(z_shift > 0, 1.0, -1.0)
    r_gross_shift = direction_shift * raw_ret_over_vol
    r_net_shift = r_gross_shift - cost_component_trades
    s = compute_stats(r_net_shift)
    null_R.append(s['R'])
    null_PF.append(s['PF'] if np.isfinite(s['PF']) else np.nan)
null_R = np.array(null_R)
null_PF = np.array([x for x in null_PF if np.isfinite(x)])
pct_R = (null_R < total_R).mean() * 100
pct_PF = (null_PF < s_net['PF']).mean() * 100 if len(null_PF) else np.nan
empirical_p = 1 - pct_R / 100
print(f'  N permutations: {N_PERM}')
print(f'  Real strategy R = {total_R:+.2f}   PF = {s_net["PF"]}')
print(f'  Null distribution: mean R = {null_R.mean():+.2f}  std = {null_R.std():.2f}')
print(f'  Null percentiles: 5th={np.percentile(null_R,5):+.2f}  50th={np.percentile(null_R,50):+.2f}  95th={np.percentile(null_R,95):+.2f}')
print(f'  Real result percentile: {pct_R:.1f}% (on R), {pct_PF:.1f}% (on PF)')
print(f'  Empirical one-sided p-value (uncorrected for multiple testing): {empirical_p:.4f}')

# ============================================================
# PHASE 11: PARAMETER ROBUSTNESS (pre-specified 1/2/3-month holding periods only)
# ============================================================
print(f'\n{"#"*100}\n  PHASE 11: PARAMETER ROBUSTNESS (pre-specified 1/2/3-month holding, NOT re-optimized)\n{"#"*100}')
print('  Looking for a broad plateau. Not selecting the best value afterward.\n')
for hm in HOLDING_MONTHS_ROBUSTNESS:
    t_h = build_trades(oi, hm)
    if len(t_h) == 0:
        continue
    r_net_h = t_h['r_gross'].values - t_h['cost_r_unit'].values * BASE_COST_MULT
    s_h = compute_stats(r_net_h)
    marker = '  <-- PRE-REGISTERED PRIMARY' if hm == HOLDING_MONTHS_PRIMARY else ''
    print(f'  {hm}-month holding{marker}  N={s_h["N"]:>5}  WR={s_h["WR"]:>5.1f}%  PF={s_h["PF"]:>5.2f}  R={s_h["R"]:>+8.2f}')

# ============================================================
# PHASE 12: COST STRESS
# ============================================================
print(f'\n{"#"*100}\n  PHASE 12: COST STRESS\n{"#"*100}')
print_gross = compute_stats(trades['r_gross'].values)
print(f'  GROSS (no cost)         PF={print_gross["PF"]:.3f}  R={print_gross["R"]:+.2f}')
for mult in COST_STRESS_LEVELS:
    total_mult = BASE_COST_MULT * mult
    r_net_c = trades['r_gross'].values - trades['cost_r_unit'].values * total_mult
    s_c = compute_stats(r_net_c)
    label = f'NET (cost x{total_mult:.2f})' + (' [BASE]' if mult == 1.0 else '')
    print(f'  {label:<28} PF={s_c["PF"]:.3f}  R={s_c["R"]:+.2f}')

# approximate break-even cost multiplier via linear search
lo_mult, hi_mult = 0.0, 20.0
for _ in range(60):
    mid = (lo_mult + hi_mult) / 2
    r_mid = (trades['r_gross'].values - trades['cost_r_unit'].values * mid).sum()
    if r_mid > 0:
        lo_mult = mid
    else:
        hi_mult = mid
print(f'\n  Approximate break-even total cost multiplier: {lo_mult:.2f}x '
      f'(base realistic assumption is {BASE_COST_MULT:.2f}x, so breakeven is at '
      f'{lo_mult/BASE_COST_MULT:.2f}x the base cost stress level)')

# ============================================================
# PHASE 13: MULTIPLE-TESTING CONTEXT
# ============================================================
print(f'\n{"#"*100}\n  PHASE 13: MULTIPLE-TESTING / FALSE-DISCOVERY CONTEXT\n{"#"*100}')
print('''  This research programme has tested roughly 20+ distinct hypotheses across two
  major queues (CFTC-positioning: E19-E26; Databento futures info: E27-E29) before
  reaching EDGE30. ES was specifically noticed because it was the one instrument,
  out of four (ES/NQ/GC/CL), that showed a positive result inside E27 -- a
  multi-instrument test that FAILED its own pre-registered generalisation
  requirement. EDGE30 is therefore a hypothesis motivated by a single favourable
  draw inside an already-failed experiment. The nominal p-value reported in
  Phase 6/10 should NOT be read as if EDGE30 were the first and only hypothesis
  ever tested against this data -- it is closer to the ~5th-to-10th independent
  look at some version of "does X predict ES/SP500 returns" this session alone,
  before counting the dozens of strategy families tested earlier in this research
  programme. A nominally significant p-value under these conditions carries
  meaningfully less evidentiary weight than the same p-value would carry as a
  single, pre-registered, first-ever test.''')

# ============================================================
# PHASE 14: SIDE-BY-SIDE COMPARISON, EDGE27 vs EDGE30
# ============================================================
print(f'\n{"#"*100}\n  PHASE 14: EDGE27 (contaminated) vs EDGE30 (corrected) SIDE-BY-SIDE\n{"#"*100}')
print(f'''
  {"Metric":<32} {"EDGE27 (front-month)":>22} {"EDGE30 (total curve)":>22}
  {"-"*32} {"-"*22} {"-"*22}
  {"Descriptive corr (full hist)":<32} {"+0.0177":>22} {f"{pearson_r:+.4f}":>22}
  {"Descriptive corr (Discovery)":<32} {"+0.0035":>22} {"+0.0084":>22}
  {"Descriptive corr (Validation)":<32} {"+0.0217":>22} {"+0.1432":>22}
  {"Descriptive corr (Final)":<32} {"+0.0355":>22} {"+0.0392":>22}
  {"Temporal pattern":<32} {"strengthens into OOS":>22} {"single-period spike":>22}
  {"NET PF (primary horizon)":<32} {"1.10 (8wk)":>22} {f"{s_net['PF']:.2f} (1mo)":>22}
  {"NET R (primary horizon)":<32} {"+192.31":>22} {f"{total_R:+.2f}":>22}
  {"Cost robustness (breakeven)":<32} {"~3.0x total mult":>22} {f"{lo_mult:.2f}x total mult":>22}
  {"Permutation percentile":<32} {"83.8%":>22} {f"{pct_R:.1f}%":>22}
  {"Generalisation requirement":<32} {"FAILED (NQ/GC/CL)":>22} {"N/A (ES-specific by design)":>22}
''')

print('  Does fixing the roll/expiry construction problem: (1) destroy the effect, (2) substantially')
print('  weaken it, (3) leave it approximately intact, or (4) strengthen it?')
print(f'  Full-history descriptive correlation went from +0.0177 (E27) to {pearson_r:+.4f} (EDGE30) --')
print(f'  numerically STRONGER, but the temporal stability picture is WORSE (single-period spike vs')
print(f'  E27 own monotonic strengthening-into-OOS pattern), and Spearman ({spearman_r:+.4f}, p={spearman_p:.2f}) does not')
print(f'  confirm the Pearson result -- suggesting outlier/fragility rather than a broad, robust signal.')

print(f'\n{"#"*100}\n  FINAL CLASSIFICATION (choose exactly one: A / B / C)\n{"#"*100}')



print('Done with Phase 6. Proceeding only if the sign/stability picture above supports it (per pre-registration Phase 6 rule: if the descriptive phenomenon fails, reject immediately).')
