"""
edge22_strategy_validation.py

Gates 2-7 for Edge #4 (E22): CFTC speculator (non-commercial) net
positioning EXTREME -> S&P 500 reversal, converted to the simplest
executable strategy.

PRESERVES THE PRE-REGISTRATION IN EDGE22_HYPOTHESIS.MD EXACTLY:
  - 156-week z-score lookback (not re-tuned)
  - net_noncomm_frac signal definition (not re-tuned)
  - 3-day publish-lag no-lookahead rule (not re-tuned)
  - 1/2/4-week horizons, ALL THREE reported, none selected as "the best"
  - S&P 500 primary; NAS100/US30/US2000 as an unmodified generalization
    check

Strategy: direction = -sign(z) (CONTRARIAN, per the pre-registered
NEGATIVE-correlation prediction: extreme long speculative positioning
predicts below-average returns, so we go short when z is high, long
when z is low) -- this is the direct, principled consequence of the
locked hypothesis direction, not a new free parameter. Same
methodology (vol-scaled sizing, cost table, stress levels) as E19/E20
for controlled cross-candidate comparison.

Gate 7 sweeps the z-score lookback and reports ALL values without
adopting the best one. Canonical result stays the pre-registered
156-week version regardless.
"""
import urllib.request
import urllib.parse
import json
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

ZSCORE_WINDOW_WEEKS = 156
PUBLISH_LAG_DAYS = 3
HORIZONS_WEEKS = [1, 2, 4]
PRIMARY_SYMBOL = 'SP500'

RISK_PCT = 0.30
VOL_LOOKBACK_DAYS = 20
BASE_COST_MULT = 1.5
COST_STRESS_LEVELS = [1.0, 1.2, 1.5, 2.0]
COST_POINTS = {'SP500': 0.6, 'NAS100': 1.5, 'US30': 2.0, 'US2000': 0.4}

INSTRUMENTS = {
    'SP500':  {'cot_markets': ['S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE'], 'yahoo': '%5EGSPC'},
    'NAS100': {'cot_markets': ['NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE'], 'yahoo': '%5ENDX'},
    'US30':   {'cot_markets': ['DOW JONES INDUSTRIAL AVG- x $5 - CHICAGO BOARD OF TRADE'], 'yahoo': '%5EDJI'},
    'US2000': {'cot_markets': ['E-MINI RUSSELL 2000 INDEX - CHICAGO MERCANTILE EXCHANGE',
                                'RUSSELL E-MINI - CHICAGO MERCANTILE EXCHANGE'], 'yahoo': '%5ERUT'},
}


def fetch_cot(markets):
    base = 'https://publicreporting.cftc.gov/resource/jun7-fc8e.json'
    frames = []
    for m in markets:
        params = {
            '$where': f"market_and_exchange_names = '{m}'",
            '$order': 'report_date_as_yyyy_mm_dd ASC',
            '$limit': '5000',
            '$select': 'report_date_as_yyyy_mm_dd,noncomm_positions_long_all,noncomm_positions_short_all,open_interest_all',
        }
        url = base + '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'User-Agent': 'edge-research'})
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        frames.append(pd.DataFrame(data))
    df = pd.concat(frames, ignore_index=True)
    df['report_date'] = pd.to_datetime(df['report_date_as_yyyy_mm_dd']).dt.tz_localize('UTC')
    for c in ['noncomm_positions_long_all', 'noncomm_positions_short_all', 'open_interest_all']:
        df[c] = df[c].astype(float)
    df = df.drop_duplicates(subset=['report_date']).sort_values('report_date').reset_index(drop=True)
    return df[['report_date', 'noncomm_positions_long_all', 'noncomm_positions_short_all', 'open_interest_all']]


def fetch_price(yahoo_ticker):
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}'
           '?period1=1000000000&period2=1893456000&interval=1d')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    resp = urllib.request.urlopen(req, timeout=30)
    data = json.loads(resp.read())
    result = data['chart']['result'][0]
    ts = result['timestamp']
    closes = result['indicators']['quote'][0]['close']
    df = pd.DataFrame({'time': pd.to_datetime(ts, unit='s', utc=True), 'close': closes})
    df = df.dropna().sort_values('time').reset_index(drop=True)
    return df


def compute_signal(cot, zwin):
    cot = cot.copy()
    cot['net_noncomm_frac'] = (cot['noncomm_positions_long_all'] - cot['noncomm_positions_short_all']) / cot['open_interest_all']
    cot['z'] = (cot['net_noncomm_frac'] - cot['net_noncomm_frac'].rolling(zwin).mean()) / \
               cot['net_noncomm_frac'].rolling(zwin).std()
    return cot.dropna(subset=['z']).reset_index(drop=True)


def build_trades(cot, px, horizon_weeks, symbol=PRIMARY_SYMBOL):
    px = px.copy()
    px['ret'] = np.log(px['close'] / px['close'].shift(1))
    px['vol20'] = px['ret'].rolling(VOL_LOOKBACK_DAYS).std()
    px_idx = px['time'].values
    px_close = px['close'].values
    px_vol = px['vol20'].values

    def pos_on_or_after(target_ts):
        pos = np.searchsorted(px_idx, np.datetime64(target_ts))
        return pos if pos < len(px_idx) else -1

    cot = cot.copy()
    cot['signal_available_date'] = cot['report_date'] + pd.Timedelta(days=PUBLISH_LAG_DAYS)

    rows = []
    for _, r in cot.iterrows():
        entry_pos = pos_on_or_after(r['signal_available_date'])
        if entry_pos < 0 or np.isnan(px_vol[entry_pos]) or px_vol[entry_pos] <= 0:
            continue
        target = r['signal_available_date'] + pd.Timedelta(weeks=horizon_weeks)
        exit_pos = pos_on_or_after(target)
        if exit_pos < 0 or exit_pos <= entry_pos:
            continue
        entry_price = px_close[entry_pos]
        exit_price = px_close[exit_pos]
        direction = -1.0 if r['z'] > 0 else 1.0  # CONTRARIAN: predicted negative correlation
        raw_log_ret = np.log(exit_price / entry_price)
        signed_ret = direction * raw_log_ret
        period_vol = px_vol[entry_pos] * np.sqrt(5 * horizon_weeks)
        r_gross = signed_ret / period_vol
        cost_r_unit = (COST_POINTS[symbol] / entry_price) / period_vol
        rows.append({'report_date': r['report_date'], 'entry_date': px['time'].iloc[entry_pos],
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
    print(f'  {label:<{width}}  N={s["N"]:>4}  WR={s["WR"]:>5.1f}%  PF={s["PF"]:>6.2f}  '
          f'R={s["R"]:>+8.2f}  avg={s["avg"]:>+8.5f}  sharpe={s["sharpe"]:>+7.4f}')


print(f'{"#"*100}\n  GATE 2-3: SP500 strategy construction + realistic costs (CONTRARIAN)\n{"#"*100}')
print('Fetching SP500 COT (non-commercial) + price data...')
cot_sp500 = fetch_cot(INSTRUMENTS['SP500']['cot_markets'])
px_sp500 = fetch_price(INSTRUMENTS['SP500']['yahoo'])
sig_sp500 = compute_signal(cot_sp500, ZSCORE_WINDOW_WEEKS)
print(f'  {len(sig_sp500)} usable weekly signals after {ZSCORE_WINDOW_WEEKS}-week warmup')

trades_by_horizon = {}
for h in HORIZONS_WEEKS:
    t = build_trades(sig_sp500, px_sp500, h)
    trades_by_horizon[h] = t
    months = (t["entry_date"].max() - t["entry_date"].min()).days / 30.4 if len(t) else 1
    print(f'\n--- Horizon: {h}-week hold, N={len(t)} trades, {len(t)/months:.1f} trades/month ---')
    gross_stats = compute_stats(t['r_gross'].values)
    print_stats('GROSS', gross_stats)
    for stress in COST_STRESS_LEVELS:
        total_mult = BASE_COST_MULT * stress
        r_net = t['r_gross'].values - t['cost_r_unit'].values * total_mult
        s = compute_stats(r_net)
        label = f'NET x{total_mult:.2f}' + (' [BASE]' if stress == 1.0 else '')
        print_stats(label, s)
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

print(f'\n{"#"*100}\n  GATE 6: PERMUTATION TEST (circular-shift null, 500 shifts)\n{"#"*100}')
rng = np.random.default_rng(22)
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
        direction_shift = np.where(z_shift > 0, -1.0, 1.0)
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

print(f'\n{"#"*100}\n  GATE 7: PARAMETER STABILITY (z-score lookback sweep, 4-week horizon)\n{"#"*100}')
print('  Looking for a stable plateau around 156 weeks, NOT selecting the best value.\n')
for zwin in [104, 130, 156, 182, 208]:
    sig = compute_signal(cot_sp500, zwin)
    t = build_trades(sig, px_sp500, 4)
    if len(t) == 0:
        continue
    r_net = t['r_gross'].values - t['cost_r_unit'].values * BASE_COST_MULT
    s = compute_stats(r_net)
    marker = '  <-- PRE-REGISTERED' if zwin == ZSCORE_WINDOW_WEEKS else ''
    print_stats(f'{zwin}w lookback{marker}', s, width=24)

print(f'\n{"#"*100}\n  GENERALIZATION CHECK: NAS100 / US30 / US2000 (identical construction, no re-tuning)\n{"#"*100}')
for sym in ['NAS100', 'US30', 'US2000']:
    print(f'\n--- {sym} ---')
    try:
        cot = fetch_cot(INSTRUMENTS[sym]['cot_markets'])
        px = fetch_price(INSTRUMENTS[sym]['yahoo'])
        sig = compute_signal(cot, ZSCORE_WINDOW_WEEKS)
        print(f'  COT: {cot["report_date"].iloc[0].date()} -> {cot["report_date"].iloc[-1].date()}, '
              f'{len(sig)} usable signals. Price: {px["time"].iloc[0].date()} -> {px["time"].iloc[-1].date()}')
        for h in HORIZONS_WEEKS:
            t = build_trades(sig, px, h, symbol=sym)
            if len(t) == 0:
                print(f'  {h}w: no trades')
                continue
            s_gross = compute_stats(t['r_gross'].values)
            r_net = t['r_gross'].values - t['cost_r_unit'].values * BASE_COST_MULT
            s_net = compute_stats(r_net)
            print_stats(f'{h}w GROSS', s_gross, width=18)
            print_stats(f'{h}w NET [BASE]', s_net, width=18)
            t2 = t.copy()
            t2['r_net'] = r_net
            n = len(t2)
            if n >= 30:
                t2s = t2.sort_values('entry_date').reset_index(drop=True)
                disc_end = t2s['entry_date'].iloc[int(n * 0.50)]
                val_end = t2s['entry_date'].iloc[int(n * 0.75)]
                print_stats('    Discovery', compute_stats(t2s[t2s['entry_date'] < disc_end]['r_net'].values), width=18)
                print_stats('    Validation', compute_stats(t2s[(t2s['entry_date'] >= disc_end) & (t2s['entry_date'] < val_end)]['r_net'].values), width=18)
                print_stats('    Final OOS', compute_stats(t2s[t2s['entry_date'] >= val_end]['r_net'].values), width=18)
    except Exception as e:
        print(f'  ERROR fetching/processing {sym}: {e}')

print('\nDone.')
