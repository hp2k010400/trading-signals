"""
build_features.py

Step 1 of today's ML approach: build a clean weekly feature matrix per
instrument, reusing everything already computed tonight (COT, rate
differentials) as FEATURES for a model to weigh, rather than as
standalone fixed-threshold rules.

Grid: weekly, week-ending Friday (W-FRI), across all 16 instruments.
Every feature is computed using ONLY data available as of that Friday's
close — no lookahead. The target is the FOLLOWING week's return, so
row t's features must never see row t's own outcome.

Features per instrument per week:
  - mom_1m, mom_3m, mom_6m, mom_12m: trailing return over that many
    months, as of this week's close. Multiple lookbacks instead of one
    fixed 12-month rule — let the model find what matters, rather than
    hand-picking a single threshold like strategy6 did.
  - atr_pct: current daily ATR(20) as a percentile of its own trailing
    2-year distribution (volatility regime, 0=quiet, 1=extreme).
  - rsi_14: 14-period weekly RSI — short-term mean-reversion indicator,
    genuinely new, not tested standalone last night.
  - cot_z: 52-week COT positioning z-score, where available (7 of 16
    instruments — DAX, SILVER, OIL, AUDJPY, EURJPY, GBPJPY, UK100,
    NATGAS, BTCUSD have no CFTC coverage, left NaN). Uses the same
    Friday-release lag as strategy10 — no lookahead.
  - rate_diff: interest rate differential, EURUSD/GBPUSD/USDJPY only
    (the only instruments where carry has a defined mechanism), NaN
    elsewhere.

Target:
  - fwd_ret_1w: the return from THIS week's close to NEXT week's close.
    This is what the model will be trained to predict — never used as
    an input feature.

Output: features_weekly.csv

Run in Codespace: python -u build_features.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    'SILVER':'XAGUSD_M1_oanda.csv',
    'OIL':   'OIL_M1_oanda.csv',
    'AUDJPY':'AUDJPY_M1_oanda.csv',
    'EURJPY':'EURJPY_M1_oanda.csv',
    'GBPJPY':'GBPJPY_M1_oanda.csv',
    'UK100': 'UK100_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
    'BTCUSD':'BTCUSD_M1_oanda.csv',
}
CARRY_PAIRS = {
    'EURUSD': ('EUR', 'USD', 1),
    'GBPUSD': ('GBP', 'USD', 1),
    'USDJPY': ('USD', 'JPY', 1),
}
RATE_FILES = {'USD':'rate_USD.csv','EUR':'rate_EUR.csv','GBP':'rate_GBP.csv','JPY':'rate_JPY.csv'}
PUBLICATION_LAG_DAYS = 6

_rates = {}
_cot = None


def load_daily(k):
    fn = FILES[k]
    if not os.path.exists(fn): return None
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    return daily[daily['open'] > 0]


def load_rates():
    for ccy, fn in RATE_FILES.items():
        if not os.path.exists(fn): continue
        df = pd.read_csv(fn)
        date_col = df.columns[0]; val_col = df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col], utc=True)
        df = df.set_index(date_col).sort_index()
        s = pd.to_numeric(df[val_col], errors='coerce').dropna()
        _rates[ccy] = s.resample('ME').last().ffill()


def load_cot():
    global _cot
    if not os.path.exists('COT_weekly_final.csv'): return
    df = pd.read_csv('COT_weekly_final.csv', parse_dates=['date'])
    df['date'] = pd.to_datetime(df['date'], utc=True)
    _cot = df


def atr_daily(daily, n=20):
    hi, lo, cl_prev = daily['high'], daily['low'], daily['close'].shift(1)
    tr = pd.concat([hi-lo, (hi-cl_prev).abs(), (lo-cl_prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def build_instrument(k):
    daily = load_daily(k)
    if daily is None or len(daily) < 400:
        return None

    weekly_close = daily['close'].resample('W-FRI').last().dropna()
    d_atr = atr_daily(daily)
    atr_weekly = d_atr.resample('W-FRI').last()
    atr_pctile = atr_weekly.rolling(104, min_periods=52).apply(
        lambda x: (x.rank(pct=True).iloc[-1]) if len(x.dropna()) > 10 else np.nan, raw=False)

    weekly_rsi = rsi(weekly_close, 14)

    rows = []
    idx = weekly_close.index
    for i in range(52, len(idx) - 1):   # need 52w history for mom_12m, and 1 fwd week for target
        d = idx[i]
        px_now = weekly_close.iloc[i]

        def mom(months):
            weeks_back = int(months * 4.345)
            j = i - weeks_back
            if j < 0: return np.nan
            past = weekly_close.iloc[j]
            return (px_now / past - 1) if past > 0 else np.nan

        row = {
            'instrument': k, 'date': d,
            'mom_1m': mom(1), 'mom_3m': mom(3), 'mom_6m': mom(6), 'mom_12m': mom(12),
            'atr_pct': atr_pctile.iloc[i] if i < len(atr_pctile) else np.nan,
            'rsi_14': weekly_rsi.iloc[i] if i < len(weekly_rsi) else np.nan,
        }

        # COT z-score, lagged for publication — no lookahead
        row['cot_z'] = np.nan
        if _cot is not None:
            cot_k = _cot[_cot['instrument'] == k]
            if not cot_k.empty:
                actionable = cot_k[cot_k['date'] + pd.Timedelta(days=PUBLICATION_LAG_DAYS) <= d]
                if not actionable.empty:
                    row['cot_z'] = actionable.iloc[-1]['z52']

        # rate differential, FX pairs only
        row['rate_diff'] = np.nan
        if k in CARRY_PAIRS:
            long_ccy, short_ccy, sign = CARRY_PAIRS[k]
            if long_ccy in _rates and short_ccy in _rates:
                lv = _rates[long_ccy].asof(d - pd.Timedelta(days=1))
                sv = _rates[short_ccy].asof(d - pd.Timedelta(days=1))
                if pd.notna(lv) and pd.notna(sv):
                    row['rate_diff'] = (lv - sv) * sign

        # target: NEXT week's return — never used as a feature, only as the label
        px_next = weekly_close.iloc[i + 1]
        row['fwd_ret_1w'] = (px_next / px_now - 1) if px_now > 0 else np.nan

        rows.append(row)

    return pd.DataFrame(rows)


print('Loading rate and COT data...')
load_rates()
load_cot()
print(f'  Rates loaded: {list(_rates.keys())}')
print(f'  COT loaded: {"yes, " + str(len(_cot)) + " rows" if _cot is not None else "no"}')

print('\nBuilding features per instrument...')
all_rows = []
for k in FILES:
    print(f'  {k}...', end=' ', flush=True)
    df = build_instrument(k)
    if df is None:
        print('SKIPPED (no/insufficient data)')
        continue
    df = df.dropna(subset=['mom_12m', 'fwd_ret_1w'])   # need at minimum trend history + a real target
    print(f'{len(df)} weekly rows')
    all_rows.append(df)

if not all_rows:
    print('\nERROR: no instruments produced usable feature rows.')
else:
    features = pd.concat(all_rows).sort_values(['instrument', 'date']).reset_index(drop=True)
    features.to_csv('features_weekly.csv', index=False)
    print(f'\nSaved features_weekly.csv ({len(features):,} rows)')
    print('\nCoverage:')
    for inst, grp in features.groupby('instrument'):
        cot_cov = grp['cot_z'].notna().mean() * 100
        rate_cov = grp['rate_diff'].notna().mean() * 100
        print(f'  {inst:<8} {grp["date"].min().date()} to {grp["date"].max().date()}  '
              f'({len(grp)} weeks, COT coverage {cot_cov:.0f}%, rate coverage {rate_cov:.0f}%)')
    print('\nFeature summary:')
    print(features[['mom_1m','mom_3m','mom_6m','mom_12m','atr_pct','rsi_14','cot_z','rate_diff','fwd_ret_1w']].describe().to_string())
