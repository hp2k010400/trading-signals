"""
alpha02_strategy_ftmo.py

The pre-registered, simplest-possible strategy expression of alpha02
(see ALPHA02_HYPOTHESIS.md and ALPHA02_PRE_REGISTRATION.md, both
written and locked BEFORE this script's results exist). Per the
directive: no stop-loss, no target, no volatility/session/trend
filter -- the purest test of "does the observed pre-event drift
survive as a directly tradeable rule after realistic costs."

RULE (fixed, not tuned):
  Long every mapped instrument for exactly the 24h window before each
  high-impact calendar event, direction always long (matching the
  unconditionally-positive observed drift), position sized by the
  instrument's own trailing volatility, held with no stop/target,
  closed at the event itself.

Reports GROSS (no cost) and NET (real cost, 1.5x-stressed base, then
+20%/+50%/+100% additional stress) separately -- NET is the primary
result.

Also includes Phase 10's permutation test: for each instrument, in
addition to the real event-anchored trades, generates N_PERMUTATIONS
sets of trades anchored at RANDOM times (same count, same 24h window,
same real price data) -- this tests whether there's something special
about PRE-EVENT windows specifically, or whether any random 24h window
would show similar performance (which would mean the finding is just
general market drift, not an event-specific phenomenon). And a cluster
-risk-sized monthly P&L (many mapped instruments react to the same
calendar event simultaneously; giving each independent full risk
double-counts correlated exposure -- same fix applied to
news_breakout_ftmo.py earlier in this research programme).

Run in Codespace: python -u alpha02_strategy_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
CALENDAR_UTC_OFFSET_HOURS = 3
PRE_WINDOW_HOURS = 24
VOL_LOOKBACK_DAYS = 20
BASE_COST_MULT = 1.5
COST_STRESS_LEVELS = [1.0, 1.2, 1.5, 2.0]   # multipliers ON TOP of BASE_COST_MULT (1.0 = base, 2.0 = +100%)
RISK_PCT = 0.30
START_BAL = 70000.0
CALENDAR_FILE = 'HighImpactCalendar.csv'
N_PERMUTATIONS = 100

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'AUDCAD':'AUDCAD_M1_ftmo.csv',
    'AUDNZD':'AUDNZD_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0, 'UK100':1.8,
    'FRA40':1.5, 'JP225':8.0, 'AUS200':2.0, 'EU50':1.2, 'US2000':0.4, 'HK50':10.0,
    'AUDCAD':0.0004, 'AUDNZD':0.0004,
}
CURRENCY_MAP = {
    'USD': ['NAS100','SP500','US30','US2000','DAX','UK100','FRA40','EU50','JP225','AUS200','HK50'],
    'EUR': ['DAX','FRA40','EU50'],
    'GBP': ['UK100'],
    'JPY': ['JP225'],
    'AUD': ['AUS200','AUDCAD','AUDNZD'],
}


def load_price(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    daily_close = df['close'].resample('1D').last().dropna()
    daily_ret = np.log(daily_close / daily_close.shift(1))
    vol20 = daily_ret.rolling(VOL_LOOKBACK_DAYS).std()
    return df, vol20


def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        return None
    df = pd.read_csv(CALENDAR_FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=CALENDAR_UTC_OFFSET_HOURS)
    df = df.drop_duplicates(subset=['currency', 'event_name', 'time'])
    return df.sort_values('time').reset_index(drop=True)


cal = load_calendar()
if cal is None:
    raise SystemExit(f'{CALENDAR_FILE} not found.')
print(f'Loaded {len(cal)} calendar events.\n')

events_for_symbol = {s: [] for s in FILES}
for currency, symbols in CURRENCY_MAP.items():
    times = list(cal[cal['currency'] == currency]['time'])
    for s in symbols:
        events_for_symbol[s].extend(times)

rng = np.random.default_rng(42)
all_trades = []
loaded = []
null_r_by_perm = [[] for _ in range(N_PERMUTATIONS)]

for symbol in FILES:
    ev_times = events_for_symbol.get(symbol, [])
    if not ev_times or not os.path.exists(FILES[symbol]):
        continue
    result = load_price(symbol)
    if result is None:
        continue
    m1, vol20 = result
    loaded.append(symbol)
    idx = m1.index
    vol_idx = vol20.index

    # ---- REAL, event-anchored trades ----
    for t in ev_times:
        pre_time = t - pd.Timedelta(hours=PRE_WINDOW_HOURS)
        entry_pos = idx.searchsorted(pre_time)
        exit_pos = idx.searchsorted(t)
        if entry_pos <= 0 or exit_pos >= len(m1) or entry_pos >= exit_pos:
            continue
        entry_price = float(m1['close'].iloc[entry_pos])
        exit_price = float(m1['close'].iloc[exit_pos - 1])
        if entry_price <= 0:
            continue
        vol_pos = vol_idx.searchsorted(pre_time.normalize()) - 1
        if vol_pos < 0 or vol_pos >= len(vol20):
            continue
        vol = vol20.iloc[vol_pos]
        if pd.isna(vol) or vol <= 0:
            continue
        period_vol = vol

        unsigned_log_ret = np.log(exit_price / entry_price)
        r_gross = np.clip(unsigned_log_ret / period_vol, -3.0, 3.0)
        cost_return = COST_POINTS[symbol] / entry_price
        cost_r_per_unit_mult = cost_return / period_vol

        all_trades.append({'symbol': symbol, 'entry_time': idx[entry_pos], 'event_time': t,
                            'r_gross': r_gross, 'cost_r_unit': cost_r_per_unit_mult})

    # ---- PERMUTATION: same instrument, same # of "events", RANDOM anchor times ----
    # Vectorized (numpy) rather than a per-event Python loop, since this repeats
    # N_PERMUTATIONS times per instrument -- otherwise far too slow.
    idx_vals = idx.values
    close_vals = m1['close'].values
    vol_idx_vals = vol_idx.values
    vol_vals = vol20.values
    n_events = len(ev_times)
    if n_events > 0 and len(idx_vals) > 10:
        valid_start = idx_vals[0] + np.timedelta64(PRE_WINDOW_HOURS, 'h')
        valid_end = idx_vals[-1]
        span_ns = (valid_end - valid_start) / np.timedelta64(1, 'ns')
        if span_ns > 0:
            for p in range(N_PERMUTATIONS):
                offsets_ns = rng.uniform(0, span_ns, size=n_events).astype('timedelta64[ns]')
                rand_times = valid_start + offsets_ns
                pre_times = rand_times - np.timedelta64(PRE_WINDOW_HOURS, 'h')

                entry_pos = np.searchsorted(idx_vals, pre_times, side='left')
                exit_pos = np.searchsorted(idx_vals, rand_times, side='left')
                mask = (entry_pos > 0) & (exit_pos < len(idx_vals)) & (entry_pos < exit_pos)
                entry_pos = entry_pos[mask]; exit_pos = exit_pos[mask]; pre_times_v = pre_times[mask]

                entry_price = close_vals[entry_pos]
                exit_price = close_vals[exit_pos - 1]
                pmask = entry_price > 0
                entry_pos = entry_pos[pmask]; entry_price = entry_price[pmask]
                exit_price = exit_price[pmask]; pre_times_v = pre_times_v[pmask]

                pre_days = pre_times_v.astype('datetime64[D]').astype('datetime64[ns]')
                vol_pos = np.searchsorted(vol_idx_vals, pre_days, side='left') - 1
                vmask = (vol_pos >= 0) & (vol_pos < len(vol_vals))
                vol_pos = vol_pos[vmask]; entry_price = entry_price[vmask]; exit_price = exit_price[vmask]

                vol = vol_vals[vol_pos]
                v2mask = ~np.isnan(vol) & (vol > 0)
                vol = vol[v2mask]; entry_price = entry_price[v2mask]; exit_price = exit_price[v2mask]
                if len(vol) == 0:
                    continue

                unsigned_ret = np.log(exit_price / entry_price)
                r_gross_null = np.clip(unsigned_ret / vol, -3.0, 3.0)
                cost_return = COST_POINTS[symbol] / entry_price
                cost_r_null = cost_return / vol * BASE_COST_MULT
                null_r_by_perm[p].extend((r_gross_null - cost_r_null).tolist())

    del m1, vol20
    gc.collect()

print(f'Loaded {len(loaded)} instruments: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) == 0:
    raise SystemExit('No trades generated.')
df = df.sort_values('entry_time').reset_index(drop=True)
df['year'] = df['entry_time'].dt.year
print(f'Total trades: {len(df)}\n')


def compute_stats(r_values):
    if len(r_values) == 0:
        return dict(N=0, WR=0.0, PF=0.0, R=0.0, avg=0.0, sharpe=0.0, maxdd=0.0)
    r = np.asarray(r_values)
    wins = r[r > 0]; losses = r[r <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r) * 100, 2)
    sharpe = round(r.mean() / r.std(), 4) if r.std() > 0 else 0.0
    equity = np.cumsum(r)
    running_max = np.maximum.accumulate(equity)
    maxdd = round((equity - running_max).min(), 2)
    return dict(N=len(r), WR=wr, PF=pf, R=round(r.sum(), 2), avg=round(r.mean(), 5),
                sharpe=sharpe, maxdd=maxdd)


def print_stats(label, s, width=16):
    print(f'  {label:<{width}}  N={s["N"]:>6}  WR={s["WR"]:>5.1f}%  PF={s["PF"]:>5.2f}  '
          f'R={s["R"]:>+9.2f}  avg={s["avg"]:>+8.5f}  sharpe={s["sharpe"]:>+7.4f}  maxDD(R)={s["maxdd"]:>+8.2f}')


# ============================================================
# GROSS vs NET (base cost + stress levels)
# ============================================================
print(f'{"#"*100}\n  GROSS vs NET (cost stress test)\n{"#"*100}')
gross_stats = compute_stats(df['r_gross'].values)
print_stats('GROSS (no cost)', gross_stats)

net_by_level = {}
for stress in COST_STRESS_LEVELS:
    total_mult = BASE_COST_MULT * stress
    r_net = df['r_gross'].values - df['cost_r_unit'].values * total_mult
    s = compute_stats(r_net)
    net_by_level[stress] = r_net
    label = f'NET (cost x{total_mult:.2f})' + (' [BASE]' if stress == 1.0 else '')
    print_stats(label, s)

df['r_net'] = net_by_level[1.0]

# ============================================================
# BY YEAR
# ============================================================
print(f'\n{"#"*100}\n  BY YEAR (net, base cost)\n{"#"*100}')
for year in sorted(df['year'].unique()):
    s = compute_stats(df[df['year'] == year]['r_net'].values)
    flag = ' <- LOSING' if s['R'] < 0 else ''
    print_stats(f'{year}{flag}', s)

# ============================================================
# DISCOVERY / VALIDATION / FINAL OOS
# ============================================================
dates = df['entry_time'].sort_values()
n = len(dates)
disc_end = dates.iloc[int(n * 0.50)]
val_end = dates.iloc[int(n * 0.75)]
print(f'\n{"#"*100}\n  DISCOVERY / VALIDATION / FINAL OOS (net, base cost)\n{"#"*100}')
print(f'  Discovery:  {dates.iloc[0].date()} -> {disc_end.date()}')
print(f'  Validation: {disc_end.date()} -> {val_end.date()}')
print(f'  Final OOS:  {val_end.date()} -> {dates.iloc[-1].date()}\n')
print_stats('DISCOVERY', compute_stats(df[df['entry_time'] < disc_end]['r_net'].values))
print_stats('VALIDATION', compute_stats(df[(df['entry_time'] >= disc_end) & (df['entry_time'] < val_end)]['r_net'].values))
print_stats('FINAL OOS', compute_stats(df[df['entry_time'] >= val_end]['r_net'].values))

# ============================================================
# BY INSTRUMENT
# ============================================================
print(f'\n{"#"*100}\n  BY INSTRUMENT (net, base cost)\n{"#"*100}')
for symbol in loaded:
    s = compute_stats(df[df['symbol'] == symbol]['r_net'].values)
    print_stats(symbol, s)

# ============================================================
# CLUSTER-RISK-SIZED MONTHLY P&L
# ============================================================
print(f'\n{"#"*100}')
print(f'  MONTHLY P&L (each month fresh from £{START_BAL:,.0f}, {RISK_PCT}% risk PER EVENT split across')
print(f'  however many mapped instruments react to it, net/base cost)')
print(f'{"#"*100}')
cluster_size = df.groupby('event_time')['symbol'].transform('count')
df['risk_frac_pct'] = RISK_PCT / cluster_size
periods = df['entry_time'].dt.to_period('M')
rows = []
for period, g in df.groupby(periods):
    pnl = START_BAL * (g['r_net'] * g['risk_frac_pct'] / 100.0).sum()
    rows.append({'month': str(period), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl / START_BAL * 100})
monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
trades_per_month = len(df) / max(len(monthly), 1)
print(f'  Months with activity: {len(monthly)}   Trades/month (avg): {trades_per_month:.1f}')
print(f'  Best month:   {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  £{monthly["pnl_gbp"].max():>+9,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
print(f'  Worst month:  {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  £{monthly["pnl_gbp"].min():>+9,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
print(f'  Median month: £{monthly["pnl_gbp"].median():>+9,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
print(f'  Mean month:   £{monthly["pnl_gbp"].mean():>+9,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

# ============================================================
# PHASE 10: PERMUTATION TEST
# ============================================================
print(f'\n{"#"*100}\n  PHASE 10: PERMUTATION TEST ({N_PERMUTATIONS} random-anchor-time shuffles)\n{"#"*100}')
print('  Tests whether PRE-EVENT windows specifically matter, or whether any random')
print('  24h window in the same instruments/date range would show similar performance.\n')

real_pf = compute_stats(df['r_net'].values)['PF']
real_r = compute_stats(df['r_net'].values)['R']
null_pfs = []
null_rs = []
for p in range(N_PERMUTATIONS):
    r = np.array(null_r_by_perm[p])
    if len(r) == 0:
        continue
    s = compute_stats(r)
    null_pfs.append(s['PF'])
    null_rs.append(s['R'])
null_pfs = np.array(null_pfs)
null_rs = np.array(null_rs)

if len(null_pfs) > 0:
    pct_pf = (null_pfs < real_pf).mean() * 100
    pct_r = (null_rs < real_r).mean() * 100
    print(f'  REAL (event-anchored):  PF={real_pf}  R={real_r:+.2f}')
    print(f'  NULL (random-anchored, N={len(null_pfs)} permutations):')
    print(f'    Mean PF:  {null_pfs.mean():.3f}   Std PF: {null_pfs.std():.3f}')
    print(f'    5th pct:  {np.percentile(null_pfs, 5):.3f}   95th pct: {np.percentile(null_pfs, 95):.3f}')
    print(f'\n  REAL PF beats {pct_pf:.1f}% of random-anchor permutations.')
    print(f'  REAL total R beats {pct_r:.1f}% of random-anchor permutations.')
    print(f'  (>=95th percentile is conventionally "significant", p<0.05 one-sided)')
else:
    print('  No valid permutation samples generated.')

print('\nDone.')
