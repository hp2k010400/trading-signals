"""
backtest_nas_ml.py — ML classifier to filter NAS100 Open trades

Instead of taking every breakout blindly, train a machine learning model
to predict which trades will win based on market conditions at entry.

Features fed into the model:
  - Day of week
  - Month (seasonality)
  - Pre-market range size vs 20-day average range (is today unusual?)
  - Trade direction (buy or sell)
  - Previous day's NAS100 return (was yesterday bullish or bearish?)
  - VIX level (market fear — high VIX = chaotic, low VIX = calm)
  - Overnight gap size (how much did price gap from yesterday's close?)
  - Previous trade outcome (momentum — does winning/losing streak matter?)
  - Range as % of recent ATR (is the range unusually tight or wide?)

Walk-forward validation: train on first 70% of trades, test on last 30%.
This simulates real trading — you can only learn from the past.

Run: python backtest_nas_ml.py
Requirements: pip install scikit-learn
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report

ACCOUNT  = 70000
RISK_PCT = 0.005
TRAIL    = 0.5

# ── Data ───────────────────────────────────────────────────────────────────────

def fetch():
    print("  Fetching NAS100 (NQ=F)...")
    nas = yf.download("NQ=F", interval="1h", period="730d",
                      auto_adjust=True, progress=False)
    print("  Fetching VIX (^VIX)...")
    vix = yf.download("^VIX", interval="1d", period="730d",
                      auto_adjust=True, progress=False)

    for df in [nas, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]

    nas = nas.dropna()
    vix = vix.dropna()

    if nas.index.tz is None:
        nas.index = nas.index.tz_localize('UTC')
    else:
        nas.index = nas.index.tz_convert('UTC')

    if vix.index.tz is None:
        vix.index = vix.index.tz_localize('UTC')
    else:
        vix.index = vix.index.tz_convert('UTC')

    # Daily NAS100 for prev return and gap calc
    daily = nas.resample('1D').agg({'open':'first','high':'max',
                                    'low':'min','close':'last'}).dropna()
    return nas, vix, daily

# ── Trade simulation ───────────────────────────────────────────────────────────

def sim(df, entry_time, direction, entry, sl):
    sl_dist = abs(entry - sl)
    trail   = sl_dist * TRAIL
    day     = entry_time.normalize()
    bars    = df[(df.index > entry_time) &
                 (df.index <= day + pd.Timedelta(hours=20))]

    sl_cur  = sl; best = entry; be_done = False
    ex = bars.iloc[-1]['close'] if len(bars) else entry

    for _, b in bars.iterrows():
        if direction == 'buy':
            if b['low'] <= sl_cur:  ex = sl_cur; break
            if b['high'] > best:    best = b['high']
            if not be_done and best >= entry + sl_dist:
                be_done = True; sl_cur = entry
            if be_done:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur: ex = sl_cur; break
            if b['low'] < best:     best = b['low']
            if not be_done and best <= entry - sl_dist:
                be_done = True; sl_cur = entry
            if be_done:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns

    pnl_r = ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist
    return round(pnl_r, 2)

# ── Feature extraction ─────────────────────────────────────────────────────────

def build_dataset(nas, vix, daily):
    rows  = []
    dates = sorted(set(nas.index.normalize().date))
    prev_outcome = 0   # previous trade win(1) or loss(-1) or none(0)

    for date in dates:
        day = pd.Timestamp(date, tz='UTC')

        # Tue-Thu only
        if day.dayofweek in [0, 4, 5, 6]:
            continue

        ref_t = day + pd.Timedelta(hours=13)
        ref_rows = nas[nas.index == ref_t]
        if len(ref_rows) == 0:
            continue

        ref = ref_rows.iloc[0]
        hi, lo, rng = ref['high'], ref['low'], ref['high'] - ref['low']
        if not (50 <= rng <= 1500):
            continue

        since = nas[(nas.index >= day + pd.Timedelta(hours=14)) &
                    (nas.index <  day + pd.Timedelta(hours=16))]
        if len(since) == 0:
            continue

        direction = None
        entry_time = None
        for bt, b in since.iterrows():
            if b['high'] > hi:
                direction = 'buy';  entry_time = bt; break
            if b['low']  < lo:
                direction = 'sell'; entry_time = bt; break
        if direction is None:
            continue

        entry = hi if direction == 'buy' else lo
        sl    = lo if direction == 'buy' else hi

        # ── Features ──────────────────────────────────────────────────────────

        # VIX on this day
        vix_rows = vix[vix.index.date == date]
        vix_val  = float(vix_rows['close'].iloc[0]) if len(vix_rows) > 0 else 18.0

        # Previous day return
        prev_rows = daily[daily.index.date < date]
        if len(prev_rows) >= 2:
            prev_ret = (prev_rows.iloc[-1]['close'] - prev_rows.iloc[-2]['close']) / \
                        prev_rows.iloc[-2]['close'] * 100
        else:
            prev_ret = 0.0

        # 20-day average range for normalisation
        if len(prev_rows) >= 20:
            avg_rng = (prev_rows['high'] - prev_rows['low']).tail(20).mean()
        else:
            avg_rng = rng
        range_ratio = rng / avg_rng if avg_rng > 0 else 1.0

        # Overnight gap (close yesterday to today's ref open)
        if len(prev_rows) >= 1:
            prev_close = prev_rows.iloc[-1]['close']
            gap_pct    = (ref['open'] - prev_close) / prev_close * 100
        else:
            gap_pct = 0.0

        # Trade outcome
        pnl_r = sim(nas, entry_time, direction, entry, sl)
        won   = 1 if pnl_r > 0 else 0

        rows.append({
            'date':        day,
            'direction':   1 if direction == 'buy' else 0,
            'day_of_week': day.dayofweek,
            'month':       day.month,
            'range_pts':   rng,
            'range_ratio': round(range_ratio, 3),
            'vix':         round(vix_val, 1),
            'prev_ret':    round(prev_ret, 3),
            'gap_pct':     round(gap_pct, 3),
            'prev_won':    prev_outcome,
            'pnl_r':       pnl_r,
            'pnl_gbp':     round(ACCOUNT * RISK_PCT * pnl_r, 2),
            'won':         won,
        })
        prev_outcome = 1 if pnl_r > 0 else -1

    return pd.DataFrame(rows)

# ── Backtest stats ─────────────────────────────────────────────────────────────

def report(df_t, label):
    if len(df_t) == 0:
        print(f"  {label}: 0 trades"); return None
    wins   = df_t[df_t['pnl_gbp'] >  5]
    losses = df_t[df_t['pnl_gbp'] < -5]
    n      = len(df_t)
    wr     = len(wins)/n*100
    gp     = wins['pnl_gbp'].sum()         if len(wins)   > 0 else 0
    gl     = abs(losses['pnl_gbp'].sum())  if len(losses) > 0 else 1
    pf     = gp/gl
    total  = df_t['pnl_gbp'].sum()
    df_t   = df_t.copy()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd = (df_t['cum']-df_t['peak']).min()
    days   = max((df_t['date'].iloc[-1]-df_t['date'].iloc[0]).days, 1)
    monthly= total/days*30
    tpm    = n/(days/30)
    verdict= "✅ STRONG" if pf>=1.5 else ("⚠️  OK" if pf>=1.2 else "❌ WEAK")
    print(f"  {label:<35} {n:>4} trades  {tpm:>5.1f}/mo  {wr:>5.1f}%  "
          f"PF:{pf:>5.2f}  £{monthly*2:>7,.0f}@1%  DD:£{max_dd*2:>6,.0f}  {verdict}")
    return pf

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  NAS100 ML FILTER — Can AI predict winning trades?")
    print("  Features: VIX, prev return, gap, range ratio, day, month, direction")
    print("  Walk-forward: train on first 70%, predict on last 30%")
    print("="*80 + "\n")

    nas, vix, daily = fetch()
    print(f"\n  Got {len(nas)} NAS100 H1 bars, {len(vix)} VIX daily bars\n")

    print("  Building trade dataset with features...")
    df = build_dataset(nas, vix, daily)
    print(f"  {len(df)} total trades generated\n")

    if len(df) < 50:
        print("  Not enough trades to train ML model"); exit()

    # Features and label
    features = ['direction','day_of_week','month','range_pts','range_ratio',
                'vix','prev_ret','gap_pct','prev_won']
    X = df[features].values
    y = df['won'].values

    # Walk-forward split: train on first 70%, test on last 30%
    split = int(len(df) * 0.70)
    X_train, X_test = X[:split], X[split:]
    y_train, y_test = y[:split], y[split:]

    df_train = df.iloc[:split]
    df_test  = df.iloc[split:]

    print(f"  Train: {len(df_train)} trades | Test: {len(df_test)} trades\n")

    # Scale features
    scaler  = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s  = scaler.transform(X_test)

    # ── Train models ───────────────────────────────────────────────────────────
    models = {
        "Random Forest":     RandomForestClassifier(n_estimators=200, max_depth=4,
                                                    random_state=42, class_weight='balanced'),
        "Gradient Boosting": GradientBoostingClassifier(n_estimators=200, max_depth=3,
                                                        learning_rate=0.05, random_state=42),
        "Logistic Regression": LogisticRegression(C=0.1, random_state=42, max_iter=1000),
    }

    print("  " + "="*76)
    print("  RESULTS ON TEST SET (last 30% of trades — walk-forward)")
    print("  " + "="*76)
    print(f"\n  {'Version':<35} {'N':>5}  {'T/mo':>5}  {'Win%':>5}  {'PF':>6}  "
          f"{'£/mo@1%':>8}  {'DD@1%':>7}")
    print(f"  {'─'*76}")

    # Baseline — no filter
    report(df_test, "No filter (baseline)")

    best_pf = 0
    best_model_name = ""
    best_predictions = None

    for name, model in models.items():
        if "Logistic" in name:
            model.fit(X_train_s, y_train)
            preds = model.predict(X_test_s)
        else:
            model.fit(X_train, y_train)
            preds = model.predict(X_test)

        filtered = df_test[preds == 1].copy()
        pf = report(filtered, name)
        if pf and pf > best_pf:
            best_pf = pf
            best_model_name = name
            best_predictions = preds

    # ── Feature importance (Random Forest) ────────────────────────────────────
    rf = models["Random Forest"]
    importances = pd.Series(rf.feature_importances_, index=features).sort_values(ascending=False)

    print(f"\n  WHAT THE MODEL CARES ABOUT MOST (Random Forest):")
    print(f"  {'─'*40}")
    for feat, imp in importances.items():
        bar = '█' * int(imp * 100)
        print(f"  {feat:<20} {imp:.3f}  {bar}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n  {'='*76}")
    print(f"  VERDICT")
    print(f"  {'='*76}")
    base_pf = report(df_test, "No filter baseline")
    if best_pf > (base_pf or 0) + 0.1:
        print(f"\n  ✅ ML HELPS — {best_model_name} improved PF from {base_pf:.2f} → {best_pf:.2f}")
        print(f"  Worth adding as a filter to the EA")
    else:
        print(f"\n  ⚠️  ML MARGINAL — best model only got PF {best_pf:.2f}")
        print(f"  Not enough improvement to justify adding complexity")
    print()
