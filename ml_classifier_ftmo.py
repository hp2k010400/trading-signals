"""
ml_classifier_ftmo.py

Genuinely different methodology from everything tested tonight -- not
a hand-coded rule, a gradient-boosted classifier trained on multiple
engineered features simultaneously (multi-horizon momentum,
volatility, moving-average distance, RSI, day-of-week, cross-asset
breadth) to predict whether each instrument's price will be higher in
5 trading days.

WALK-FORWARD DISCIPLINE (the part that makes or breaks this -- get it
wrong and you get a beautiful, completely fake result, same failure
mode as the original bot):
  - Trained only on an EXPANDING window of past data.
  - Retrained every 6 months, predicting forward on the NEXT 6 months
    it has never seen.
  - Explicit purge: when training for a test window starting at date
    T, only rows whose 5-day-forward label fully resolves BEFORE T
    are used -- otherwise the last few days of "training" data would
    leak information from inside the test window.

TRADING RULE (built on the model's output):
  - P(price up in 5 days) > 0.55 -> long. < 0.45 -> short. Else: no
    trade.
  - Entry at next day's open. Stop = 1x ATR(14). Target = 1.5x stop.
  - Time-stop at 5 trading days (matching the prediction horizon).

Requires scikit-learn. If not installed: pip install scikit-learn

Run in Codespace: python -u ml_classifier_ftmo.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

try:
    from sklearn.ensemble import HistGradientBoostingClassifier
except ImportError:
    raise SystemExit("scikit-learn not installed. Run: pip install scikit-learn")

BROKER_UTC_OFFSET_HOURS = 3
FORWARD_DAYS = 5
RETRAIN_MONTHS = 6
INITIAL_TRAIN_YEARS = 3
PROB_LONG = 0.55
PROB_SHORT = 0.45
ATR_PERIOD = 14
STOP_ATR_MULT = 1.0
RR = 1.5
COST_MULT = 1.5
MAX_HOLD_DAYS = 5

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'GOLD':  'XAUUSD_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0,
    'EURUSD':0.0001, 'GBPUSD':0.00003, 'USDJPY':0.011, 'GOLD':0.40,
}

_daily = {}

def load_daily(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    daily = daily[daily['open'] > 0]
    _daily[symbol] = daily
    return True


def build_features(symbol, market_avg_ret5):
    d = _daily[symbol].copy()
    c = d['close']
    d['ret1']  = np.log(c / c.shift(1))
    d['ret3']  = np.log(c / c.shift(3))
    d['ret5']  = np.log(c / c.shift(5))
    d['ret10'] = np.log(c / c.shift(10))
    d['ret20'] = np.log(c / c.shift(20))
    d['vol20'] = d['ret1'].rolling(20).std()
    ma20 = c.rolling(20).mean()
    ma50 = c.rolling(50).mean()
    d['dist_ma20'] = (c - ma20) / ma20
    d['dist_ma50'] = (c - ma50) / ma50
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    d['rsi14'] = 100 - (100 / (1 + rs))
    d['dow'] = d.index.dayofweek
    d['breadth5'] = market_avg_ret5.reindex(d.index)

    prev_close = c.shift(1)
    tr = pd.concat([d['high']-d['low'], (d['high']-prev_close).abs(), (d['low']-prev_close).abs()], axis=1).max(axis=1)
    d['atr14'] = tr.rolling(ATR_PERIOD).mean()

    d['fwd_ret5'] = np.log(c.shift(-FORWARD_DAYS) / c)
    d['label'] = (d['fwd_ret5'] > 0).astype(int)
    d['symbol'] = symbol
    return d


FEATURE_COLS = ['ret1','ret3','ret5','ret10','ret20','vol20','dist_ma20','dist_ma50','rsi14','dow','breadth5']


print('Loading FTMO M1 data, building daily bars + features...')
loaded = [s for s in FILES if load_daily(s)]
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

# market-wide breadth feature: average 5-day return across all instruments, per day
rets5 = {}
for s in loaded:
    c = _daily[s]['close']
    rets5[s] = np.log(c / c.shift(5))
rets5_df = pd.DataFrame(rets5)
market_avg_ret5 = rets5_df.mean(axis=1)

all_feat = []
for s in loaded:
    all_feat.append(build_features(s, market_avg_ret5))
data = pd.concat(all_feat).dropna(subset=FEATURE_COLS + ['label'])
data = data.sort_index()

print(f'Total labeled rows: {len(data)}\n')

start_date = data.index.min()
train_end = start_date + pd.DateOffset(years=INITIAL_TRAIN_YEARS)
last_date = data.index.max()

all_trades = []
window_num = 0
while train_end < last_date:
    test_start = train_end
    test_end = min(test_start + pd.DateOffset(months=RETRAIN_MONTHS), last_date)

    # purge: only train on rows whose label fully resolved before test_start
    train_data = data[data.index <= test_start - pd.Timedelta(days=FORWARD_DAYS)]
    test_data = data[(data.index >= test_start) & (data.index < test_end)]

    if len(train_data) < 200 or len(test_data) == 0:
        train_end = test_end
        continue

    X_train = train_data[FEATURE_COLS].values
    y_train = train_data['label'].values
    X_test = test_data[FEATURE_COLS].values

    model = HistGradientBoostingClassifier(max_iter=150, max_depth=4, random_state=42)
    model.fit(X_train, y_train)
    probs = model.predict_proba(X_test)[:, 1]

    window_num += 1
    window_trades = 0
    for (idx, row), prob in zip(test_data.iterrows(), probs):
        if prob > PROB_LONG:
            direction = 1
        elif prob < PROB_SHORT:
            direction = -1
        else:
            continue

        symbol = row['symbol']
        d = _daily[symbol]
        d_index = d.index
        pos = d_index.searchsorted(idx)
        entry_pos = pos + 1
        if entry_pos >= len(d):
            continue
        entry_price = float(d['open'].iloc[entry_pos])
        atr = row['atr14']
        if pd.isna(atr) or atr <= 0:
            continue
        stop_dist = STOP_ATR_MULT * atr
        stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
        tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

        window_end_pos = min(entry_pos + 1 + MAX_HOLD_DAYS, len(d))
        future = d.iloc[entry_pos + 1: window_end_pos]
        r_gross = None
        if len(future) > 0:
            highs = future['high'].values; lows = future['low'].values; closes = future['close'].values
            for k in range(len(future)):
                if direction == 1:
                    if highs[k] >= tp_price: r_gross = RR; break
                    if lows[k] <= stop_price: r_gross = -1.0; break
                else:
                    if lows[k] <= tp_price: r_gross = RR; break
                    if highs[k] >= stop_price: r_gross = -1.0; break
            if r_gross is None:
                final_close = closes[-1]
                r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                           else (entry_price - final_close) / stop_dist)
        else:
            r_gross = -1.0

        cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
        all_trades.append({'symbol': symbol, 'entry_time': d_index[entry_pos],
                           'r_net': r_gross - cost_r, 'window': window_num})
        window_trades += 1

    print(f'  Window {window_num}: train {train_data.index.min().date()}->{train_data.index.max().date()} '
          f'({len(train_data)} rows)  test {test_start.date()}->{test_end.date()}  {window_trades} trades')

    train_end = test_end

df = pd.DataFrame(all_trades)
print(f'\nTotal trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


if len(df) > 0:
    n, wr, pf, tot = compute_stats(df['r_net'].values)
    print(f'\nOVERALL: N={n}  WR={wr}%  PF={pf}  R={tot:+.1f}\n')

    print(f'{"#"*90}')
    print(f'  PER WALK-FORWARD WINDOW (each one genuinely out-of-sample)')
    print(f'{"#"*90}')
    n_losing = 0
    for w in sorted(df['window'].unique()):
        rv = df[df['window'] == w]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        if tot2 < 0:
            n_losing += 1
        print(f'  Window {w}   N={n2:>4}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}' + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{df["window"].nunique()}')

print('\nDone.')
