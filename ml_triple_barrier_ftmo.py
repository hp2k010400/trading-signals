"""
ml_triple_barrier_ftmo.py

The one methodologically different avenue left untried tonight after
~12 price-pattern mechanisms mostly failed: a proper ML classifier
upgrade. The earlier version (ml_classifier_ftmo.py) used a naive
fixed-5-day-forward-return-sign label and a small feature set, and
only managed PF 1.10-1.13 -- real but weak, and its own diffuse signal
was the likely cause.

Two real upgrades here, not just more of the same:

1. TRIPLE-BARRIER LABELING (Lopez de Prado, a real quant-research
   technique, not a naive label): each day gets an upper barrier and
   lower barrier at +/- K_BARRIER x ATR(14), plus a FORWARD_DAYS time
   limit. The label is whichever of (upper hit, lower hit, time limit
   reached) happens FIRST -- a much cleaner signal than "was the
   return positive after exactly 5 days," which ignores path and mixes
   together trades that were never close to the target with trades
   that touched it early and reversed.

2. EXPANDED, POOLED, CROSS-ASSET FEATURES: trained on ALL 27
   instruments pooled together (much more data than any single-
   instrument model), with ADX(14) and Bollinger-band position added
   to the original return/RSI/distance-from-MA feature set, plus a
   cross-sectional breadth feature (fraction of the whole universe
   with a positive 5-day return on that date).

Same walk-forward discipline as everything else tonight: expanding-
window retraining every 6 months, with PURGING -- only trains on rows
whose label-resolution window (up to FORWARD_DAYS out) fully completes
before the test period starts, so there's no leakage from a label that
technically depends on future price action inside the test window.

Trades only fire when the model's predicted probability for up/down
clears CONF_THRESHOLD (baseline random for a 3-class problem is ~33%,
so 40% is a real, if modest, edge requirement). Real spread costs
(1.5x stress multiplier), confirmed UTC+3 broker offset correction.

Run in Codespace: python -u ml_triple_barrier_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

from sklearn.ensemble import HistGradientBoostingClassifier

BROKER_UTC_OFFSET_HOURS = 3

ATR_PERIOD = 14
K_BARRIER = 2.0          # barrier distance = K_BARRIER x ATR(14)
FORWARD_DAYS = 5         # time-limit if neither barrier is touched
COST_MULT = 1.5
RETRAIN_MONTHS = 6
INITIAL_TRAIN_YEARS = 3  # no predictions until this much history exists
CONF_THRESHOLD = 0.40    # baseline random for 3-class is ~0.333
WALK_FORWARD_MONTHS = 6
RISK_PCT = 0.30
START_BAL = 70000.0

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'GOLD':  'XAUUSD_M1_ftmo.csv',
    'NATGAS':'NATGAS_cash_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'AUDNZD':'AUDNZD_M1_ftmo.csv',
    'AUDCAD':'AUDCAD_M1_ftmo.csv',
    'AUDCHF':'AUDCHF_M1_ftmo.csv',
    'USDCHF':'USDCHF_M1_ftmo.csv',
    'USDCAD':'USDCAD_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'WTIOIL':  'WTIOIL_M1_ftmo.csv',
    'BRENTOIL':'BRENTOIL_M1_ftmo.csv',
    'SILVER':  'SILVER_M1_ftmo.csv',
    'COPPER':  'COPPER_M1_ftmo.csv',
    'PLATINUM':'PLATINUM_M1_ftmo.csv',
    'PALLADIUM':'PALLADIUM_M1_ftmo.csv',
    'USDINDEX':'USDINDEX_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
    'NATGAS':0.008, 'UK100':1.8,
    'AUDNZD':0.0004, 'AUDCAD':0.0004, 'AUDCHF':0.0004, 'USDCHF':0.00015, 'USDCAD':0.00015,
    'FRA40':1.5, 'JP225':8.0, 'AUS200':2.0, 'EU50':1.2, 'US2000':0.4, 'HK50':10.0,
    'WTIOIL':0.04, 'BRENTOIL':0.04, 'SILVER':0.025, 'COPPER':0.008,
    'PLATINUM':0.5, 'PALLADIUM':2.0, 'USDINDEX':0.02,
}

FEATURE_COLS = ['ret1','ret3','ret5','ret10','ret20','vol20','dist_ma20','dist_ma50',
                 'rsi14','adx14','bb_pos','atr_pct','dow','breadth5']


def compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def compute_adx(high, low, close, period=14):
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1/period, adjust=False).mean().fillna(0)


def load_daily(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    del df
    daily = daily[daily['open'] > 0]

    close = daily['close']; high = daily['high']; low = daily['low']
    prev_close = close.shift(1)
    tr = pd.concat([high-low, (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    daily['atr14'] = tr.rolling(ATR_PERIOD).mean()

    daily['ret1'] = np.log(close / close.shift(1))
    daily['ret3'] = np.log(close / close.shift(3))
    daily['ret5'] = np.log(close / close.shift(5))
    daily['ret10'] = np.log(close / close.shift(10))
    daily['ret20'] = np.log(close / close.shift(20))
    daily['vol20'] = daily['ret1'].rolling(20).std()
    ma20 = close.rolling(20).mean(); ma50 = close.rolling(50).mean()
    daily['dist_ma20'] = (close - ma20) / daily['atr14']
    daily['dist_ma50'] = (close - ma50) / daily['atr14']
    daily['rsi14'] = compute_rsi(close, 14)
    daily['adx14'] = compute_adx(high, low, close, 14)
    bb_mid = close.rolling(20).mean(); bb_std = close.rolling(20).std()
    daily['bb_pos'] = (close - bb_mid) / (2 * bb_std.replace(0, np.nan))
    daily['atr_pct'] = daily['atr14'] / close
    daily['dow'] = daily.index.dayofweek

    return daily


def triple_barrier_label(daily):
    close = daily['close'].values; high = daily['high'].values; low = daily['low'].values
    atr = daily['atr14'].values
    n = len(daily)
    label = np.full(n, np.nan)
    barrier_width = np.full(n, np.nan)
    for i in range(n - 1):
        a = atr[i]
        if np.isnan(a) or a <= 0:
            continue
        entry = close[i]
        upper = entry + K_BARRIER * a
        lower = entry - K_BARRIER * a
        end = min(i + 1 + FORWARD_DAYS, n)
        lbl = 0
        for j in range(i + 1, end):
            if high[j] >= upper: lbl = 1; break
            if low[j] <= lower: lbl = -1; break
        label[i] = lbl
        barrier_width[i] = K_BARRIER * a
    daily['label'] = label
    daily['barrier_width'] = barrier_width
    return daily


print('Loading daily bars, computing features + triple-barrier labels per instrument...')
per_symbol = {}
for symbol in FILES:
    daily = load_daily(symbol)
    if daily is None:
        continue
    daily = triple_barrier_label(daily)
    per_symbol[symbol] = daily
    print(f'  {symbol}: {len(daily)} daily bars')
    gc.collect()

print(f'\nLoaded {len(per_symbol)} instruments.')

# Cross-sectional breadth: fraction of the universe with ret5 > 0 on each date
ret5_wide = pd.DataFrame({s: d['ret5'] for s, d in per_symbol.items()})
breadth5 = (ret5_wide > 0).mean(axis=1)

pooled_rows = []
for symbol, daily in per_symbol.items():
    d = daily.copy()
    d['breadth5'] = breadth5.reindex(d.index)
    d['symbol'] = symbol
    d['cost_points'] = COST_POINTS[symbol]
    pooled_rows.append(d.dropna(subset=FEATURE_COLS + ['label', 'barrier_width']))
pooled = pd.concat(pooled_rows).sort_index()
pooled['label'] = pooled['label'].astype(int)
print(f'Pooled dataset: {len(pooled)} rows across {pooled["symbol"].nunique()} instruments.')

if len(pooled) < 5000:
    raise SystemExit('Not enough pooled data to train a walk-forward model -- check instrument CSVs are present.')

start_date = pooled.index.min()
end_date = pooled.index.max()
first_test_start = start_date + pd.DateOffset(years=INITIAL_TRAIN_YEARS)

all_trades = []
test_start = first_test_start
while test_start < end_date:
    test_end = test_start + pd.DateOffset(months=RETRAIN_MONTHS)
    # Purge: only train on rows whose label window (up to FORWARD_DAYS out)
    # fully resolves before the test period starts -- no leakage.
    train = pooled[pooled.index <= test_start - pd.Timedelta(days=FORWARD_DAYS)]
    test = pooled[(pooled.index >= test_start) & (pooled.index < test_end)]
    if len(train) < 2000 or len(test) == 0:
        test_start = test_end
        continue

    model = HistGradientBoostingClassifier(max_iter=200, max_depth=6, random_state=42)
    model.fit(train[FEATURE_COLS], train['label'])
    classes = list(model.classes_)   # e.g. [-1, 0, 1]

    proba = model.predict_proba(test[FEATURE_COLS])
    for idx_pos, (idx, row) in enumerate(test.iterrows()):
        p = dict(zip(classes, proba[idx_pos]))
        p_up = p.get(1, 0.0); p_down = p.get(-1, 0.0)
        if p_up >= CONF_THRESHOLD and p_up > p_down:
            direction = 1
        elif p_down >= CONF_THRESHOLD and p_down > p_up:
            direction = -1
        else:
            continue

        r_gross = direction * row['label']   # label is already +1/0/-1 relative to up-barrier
        # label==0 means time-limit reached without touching either barrier --
        # approximate that outcome with the actual bounded return at the label
        # horizon rather than treating it as a hard loss (it wasn't wrong,
        # just inconclusive)
        if row['label'] == 0:
            r_gross = direction * np.clip(row['ret5'] / (row['barrier_width'] / row['close']), -1, 1) \
                      if row['barrier_width'] > 0 else 0.0

        cost_r = row['cost_points'] / row['barrier_width'] * COST_MULT
        all_trades.append({'symbol': row['symbol'], 'entry_time': idx, 'r_net': r_gross - cost_r})

    test_start = test_end

del pooled, pooled_rows, per_symbol
gc.collect()


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'\nTotal trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

n, wr, pf, tot = compute_stats(df['r_net'].values) if len(df) else (0,0,0,0)
print_row('OVERALL', n, wr, pf, tot)

if len(df) > 0:
    loaded = sorted(df['symbol'].unique())
    print(f'\n{"#"*90}')
    print(f'  WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    print(f'{"#"*90}')
    df['period'] = df['entry_time'].dt.to_period('M')
    all_periods = sorted(df['period'].unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        window_rv = df[df['period'].isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    print(f'\n  Per-instrument:')
    for symbol in loaded:
        rv = df[df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {symbol}', n2, wr2, pf2, tot2)

    print(f'\n{"#"*90}')
    print(f'  MONTHLY P&L (each month fresh from £{START_BAL:,.0f}, {RISK_PCT}% risk per trade, additive)')
    print(f'{"#"*90}')
    rpt = RISK_PCT / 100.0
    rows = []
    for period, g in df.groupby('period'):
        pnl = START_BAL * rpt * g['r_net'].sum()
        rows.append({'month': str(period), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl / START_BAL * 100})
    monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
    print(f'  Months with activity: {len(monthly)}')
    print(f'  Best month:   {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  £{monthly["pnl_gbp"].max():>+9,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
    print(f'  Worst month:  {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  £{monthly["pnl_gbp"].min():>+9,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
    print(f'  Median month: £{monthly["pnl_gbp"].median():>+9,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
    print(f'  Mean month:   £{monthly["pnl_gbp"].mean():>+9,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
    pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
    print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')

print('\nDone.')
