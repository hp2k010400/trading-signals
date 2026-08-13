"""
edge27_strategy_validation.py

Gates 2-7 for E27 (open interest change -> forward returns), per
DATABENTO_VALIDATION_PROTOCOL.md. Pre-registration in
EDGE27_HYPOTHESIS.md preserved exactly (36-month z-score lookback,
~1-month OI-change window, 1-business-day lag, direction=sign(z) per
the positive-correlation prediction, horizons 2/4/8 weeks -- none
selected as "the best", all three reported throughout).

Uses real Databento data already downloaded:
  databento_ohlcv_1h_v2.csv, databento_statistics_v2.csv

Gate 6 (generalisation) cost points for NQ/GC/CL use FTMO-equivalent
spreads already established in this research programme's standing
COST_POINTS table (SP500/NAS100) where available; GOLD/OIL points are
not in that table from prior sessions and are flagged explicitly
rather than guessed at with false precision.
"""
import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_DAYS = 756
OI_CHANGE_WINDOW_DAYS = 21
PUBLISH_LAG_DAYS = 1
HORIZONS_WEEKS = [2, 4, 8]
PRIMARY_SYMBOL = 'ES.n.0'
SYMBOLS = ['ES.n.0', 'NQ.n.0', 'GC.n.0', 'CL.n.0']

RISK_PCT = 0.30
VOL_LOOKBACK_DAYS = 20
BASE_COST_MULT = 1.5
COST_STRESS_LEVELS = [1.0, 1.2, 1.5, 2.0]
# FTMO-CFD-equivalent cost points, from this research programme's standing table
# where confirmed; GC/CL flagged as NOT independently confirmed this session.
COST_POINTS = {
    'ES.n.0': 0.6,     # SP500, confirmed (alpha02/E19 COST_POINTS table)
    'NQ.n.0': 1.5,     # NAS100, confirmed
    'GC.n.0': 0.35,    # GOLD/XAUUSD -- NOT independently re-confirmed this session,
                        # reasonable placeholder pending real FTMO spread check
    'CL.n.0': 0.03,    # OIL/USOIL -- NOT independently re-confirmed this session,
                        # reasonable placeholder pending real FTMO spread check
}


def load_price():
    df = pd.read_csv('databento_ohlcv_1h_v2.csv', usecols=['ts_event', 'close', 'symbol'])
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    return df.groupby(['symbol', 'date'])['close'].last().reset_index()


def load_oi():
    df = pd.read_csv('databento_statistics_v2.csv', usecols=['ts_event', 'quantity', 'stat_type', 'symbol'])
    df = df[df['stat_type'] == 9].copy()
    df['ts_event'] = pd.to_datetime(df['ts_event'], utc=True)
    df['date'] = df['ts_event'].dt.normalize()
    daily = df.groupby(['symbol', 'date'])['quantity'].last().reset_index()
    return daily.rename(columns={'quantity': 'oi'})


def compute_signal(oi_sym, zwin):
    o = oi_sym.copy().sort_values('date').reset_index(drop=True)
    o['oi_change'] = o['oi'] / o['oi'].shift(OI_CHANGE_WINDOW_DAYS) - 1
    o['z'] = (o['oi_change'] - o['oi_change'].rolling(zwin).mean()) / o['oi_change'].rolling(zwin).std()
    return o.dropna(subset=['z']).reset_index(drop=True)


def build_trades(sig, price_sym, horizon_weeks, symbol):
    p = price_sym.copy().sort_values('date').reset_index(drop=True)
    p['ret'] = np.log(p['close'] / p['close'].shift(1))
    p['vol20'] = p['ret'].rolling(VOL_LOOKBACK_DAYS).std()
    p_dates = p['date'].values
    p_close = p['close'].values
    p_vol = p['vol20'].values

    def pos_on_or_after(t):
        pos = np.searchsorted(p_dates, np.datetime64(t))
        return pos if pos < len(p_dates) else -1

    sig = sig.copy()
    sig['signal_available_date'] = sig['date'] + pd.tseries.offsets.BDay(PUBLISH_LAG_DAYS)

    rows = []
    for _, r in sig.iterrows():
        ep = pos_on_or_after(r['signal_available_date'])
        if ep < 0 or np.isnan(p_vol[ep]) or p_vol[ep] <= 0:
            continue
        target = r['signal_available_date'] + pd.Timedelta(weeks=horizon_weeks)
        xp = pos_on_or_after(target)
        if xp < 0 or xp <= ep:
            continue
        entry_price = p_close[ep]
        exit_price = p_close[xp]
        direction = 1.0 if r['z'] > 0 else -1.0
        raw_log_ret = np.log(exit_price / entry_price)
        signed_ret = direction * raw_log_ret
        period_vol = p_vol[ep] * np.sqrt(5 * horizon_weeks)
        r_gross = signed_ret / period_vol
        cost_r_unit = (COST_POINTS[symbol] / entry_price) / period_vol
        rows.append({'date': r['date'], 'entry_date': p['date'].iloc[ep],
                     'z': r['z'], 'direction': direction, 'r_gross': r_gross, 'cost_r_unit': cost_r_unit})
    return pd.DataFrame(rows)


def compute_stats(r):
    r = np.asarray(r)
    if len(r) == 0:
        return dict(N=0, WR=0.0, PF=0.0, R=0.0, avg=0.0, sharpe=0.0)
    wins = r[r > 0]
    losses = r[r <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else float('inf')
    wr = round(len(wins) / len(r) * 100, 2)
    sharpe = round(r.mean() / r.std(), 4) if r.std() > 0 else 0.0
    return dict(N=len(r), WR=wr, PF=pf, R=round(r.sum(), 2), avg=round(r.mean(), 5), sharpe=sharpe)


def print_stats(label, s, width=14):
    print(f'  {label:<{width}}  N={s["N"]:>5}  WR={s["WR"]:>5.1f}%  PF={s["PF"]:>6.2f}  '
          f'R={s["R"]:>+9.2f}  avg={s["avg"]:>+8.5f}  sharpe={s["sharpe"]:>+7.4f}')


print('Loading data...')
price_all = load_price()
oi_all = load_oi()

price_es = price_all[price_all['symbol'] == PRIMARY_SYMBOL]
oi_es = oi_all[oi_all['symbol'] == PRIMARY_SYMBOL]
sig_es = compute_signal(oi_es, ZSCORE_WINDOW_DAYS)
print(f'ES: {len(sig_es)} usable signals after {ZSCORE_WINDOW_DAYS}-day z-score warmup')

print(f'\n{"#"*100}\n  GATE 2-3: ES strategy construction + realistic costs\n{"#"*100}')
trades_by_horizon = {}
for h in HORIZONS_WEEKS:
    t = build_trades(sig_es, price_es, h, PRIMARY_SYMBOL)
    trades_by_horizon[h] = t
    months = (t["entry_date"].max() - t["entry_date"].min()).days / 30.4 if len(t) else 1
    print(f'\n--- Horizon: {h}-week hold, N={len(t)} trades, {len(t)/months:.1f} trades/month ---')
    print_stats('GROSS', compute_stats(t['r_gross'].values))
    for stress in COST_STRESS_LEVELS:
        total_mult = BASE_COST_MULT * stress
        r_net = t['r_gross'].values - t['cost_r_unit'].values * total_mult
        label = f'NET x{total_mult:.2f}' + (' [BASE]' if stress == 1.0 else '')
        print_stats(label, compute_stats(r_net))
    t['r_net'] = t['r_gross'] - t['cost_r_unit'] * BASE_COST_MULT

print(f'\n{"#"*100}\n  GATE 4: BY YEAR (net, base cost)\n{"#"*100}')
for h in HORIZONS_WEEKS:
    t = trades_by_horizon[h]
    if len(t) == 0:
        continue
    print(f'\n  --- {h}-week horizon ---')
    t['year'] = t['entry_date'].dt.year
    for year in sorted(t['year'].unique()):
        s = compute_stats(t[t['year'] == year]['r_net'].values)
        flag = ' <- losing' if s['R'] < 0 else ''
        print_stats(f'{year}{flag}', s)

print(f'\n{"#"*100}\n  GATE 4: DISCOVERY / VALIDATION / FINAL-OOS (net, base cost)\n{"#"*100}')
for h in HORIZONS_WEEKS:
    t = trades_by_horizon[h].sort_values('entry_date').reset_index(drop=True)
    n = len(t)
    if n < 30:
        continue
    disc_end = t['entry_date'].iloc[int(n * 0.50)]
    val_end = t['entry_date'].iloc[int(n * 0.75)]
    print(f'\n  --- {h}-week horizon ---')
    print_stats('DISCOVERY', compute_stats(t[t['entry_date'] < disc_end]['r_net'].values))
    print_stats('VALIDATION', compute_stats(t[(t['entry_date'] >= disc_end) & (t['entry_date'] < val_end)]['r_net'].values))
    print_stats('FINAL OOS', compute_stats(t[t['entry_date'] >= val_end]['r_net'].values))

print(f'\n{"#"*100}\n  GATE 5: PERMUTATION TEST (circular-shift null, 500 shifts)\n{"#"*100}')
rng = np.random.default_rng(27)
N_PERM = 500
for h in HORIZONS_WEEKS:
    t = trades_by_horizon[h]
    if len(t) < 30:
        continue
    real_stats = compute_stats(t['r_net'].values)
    z_vals = t['z'].values
    cost_component = t['cost_r_unit'].values * BASE_COST_MULT
    raw_ret_over_vol = t['r_gross'].values * t['direction'].values

    null_R, null_PF = [], []
    for _ in range(N_PERM):
        shift = rng.integers(1, len(z_vals))
        z_shift = np.roll(z_vals, shift)
        direction_shift = np.where(z_shift > 0, 1.0, -1.0)
        r_gross_shift = direction_shift * raw_ret_over_vol
        r_net_shift = r_gross_shift - cost_component
        s = compute_stats(r_net_shift)
        null_R.append(s['R'])
        null_PF.append(s['PF'] if np.isfinite(s['PF']) else np.nan)

    null_R = np.array(null_R)
    null_PF = np.array([x for x in null_PF if np.isfinite(x)])
    pct_R = (null_R < real_stats['R']).mean() * 100
    pct_PF = (null_PF < real_stats['PF']).mean() * 100 if len(null_PF) else np.nan
    print(f'\n  --- {h}-week horizon ---')
    print(f'  REAL: R={real_stats["R"]:+.2f}  PF={real_stats["PF"]:.3f}')
    print(f'  NULL: mean R={null_R.mean():+.2f}  std R={null_R.std():.2f}  mean PF={np.nanmean(null_PF):.3f}')
    print(f'  REAL beats {pct_R:.1f}% of permutations on R, {pct_PF:.1f}% on PF')

print(f'\n{"#"*100}\n  GATE 6: GENERALISATION (NQ / GC / CL, identical construction, no re-tuning)\n{"#"*100}')
for sym in ['NQ.n.0', 'GC.n.0', 'CL.n.0']:
    print(f'\n--- {sym} ---')
    price_sym = price_all[price_all['symbol'] == sym]
    oi_sym = oi_all[oi_all['symbol'] == sym]
    sig = compute_signal(oi_sym, ZSCORE_WINDOW_DAYS)
    for h in HORIZONS_WEEKS:
        t = build_trades(sig, price_sym, h, sym)
        if len(t) == 0:
            print(f'  {h}w: no trades')
            continue
        r_net = t['r_gross'].values - t['cost_r_unit'].values * BASE_COST_MULT
        print_stats(f'{h}w GROSS', compute_stats(t['r_gross'].values), width=18)
        print_stats(f'{h}w NET [BASE]', compute_stats(r_net), width=18)

print(f'\n{"#"*100}\n  GATE 7: PARAMETER STABILITY (z-score lookback sweep, 4-week horizon)\n{"#"*100}')
print('  Looking for a stable plateau around 756 days, NOT selecting the best value.\n')
for zwin in [504, 630, 756, 882, 1008]:
    sig = compute_signal(oi_es, zwin)
    t = build_trades(sig, price_es, 4, PRIMARY_SYMBOL)
    if len(t) == 0:
        continue
    r_net = t['r_gross'].values - t['cost_r_unit'].values * BASE_COST_MULT
    marker = '  <-- PRE-REGISTERED' if zwin == ZSCORE_WINDOW_DAYS else ''
    print_stats(f'{zwin}d lookback{marker}', compute_stats(r_net), width=24)

print('\nDone.')
