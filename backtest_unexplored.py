"""
backtest_unexplored.py — 4 unexplored experiments

  A. CRYPTO H4 EMA — Bitcoin, Ethereum, Solana (trend machines, 24/7)
  B. EMA PULLBACK ENTRY — enter on retest of fast EMA after crossover
     (tighter SL = better R:R vs standard crossover entry)
  C. DAY-OF-WEEK BREAKDOWN — all current live strategies, which days kill PF?
  D. H1 EMA — same DAX/UK100/NatGas edge but 4x more signals per month

Run: python backtest_unexplored.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT  = 70000
RISK_PCT = 0.005
TRAIL    = 0.5

# ── Data ───────────────────────────────────────────────────────────────────────
_cache = {}
def get_data(symbol, interval="1h", period="730d"):
    key = (symbol, interval)
    if key not in _cache:
        try:
            df = yf.download(symbol, interval=interval, period=period,
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            else:
                df.index = df.index.tz_convert('UTC')
            _cache[key] = df if len(df) > 200 else None
        except:
            _cache[key] = None
    return _cache[key]

def resample_h4(df):
    return df.resample('4h').agg({'open':'first','high':'max',
                                   'low':'min','close':'last',
                                   'volume':'sum'}).dropna()

def add_ema_adx(df, fast=10, slow=20, adx_period=14):
    df = df.copy()
    df['ema_fast'] = df['close'].ewm(span=fast, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=slow, adjust=False).mean()
    hi, lo, cl = df['high'], df['low'], df['close']
    tr   = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    df['atr'] = tr.ewm(com=adx_period-1, adjust=False).mean()
    dmp  = ((hi-hi.shift())>(lo.shift()-lo)).astype(float)*(hi-hi.shift()).clip(lower=0)
    dmm  = ((lo.shift()-lo)>(hi-hi.shift())).astype(float)*(lo.shift()-lo).clip(lower=0)
    atr_s = tr.ewm(com=adx_period-1, adjust=False).mean()
    dip  = 100*dmp.ewm(com=adx_period-1,adjust=False).mean()/atr_s
    dim  = 100*dmm.ewm(com=adx_period-1,adjust=False).mean()/atr_s
    dx   = (100*(dip-dim).abs()/(dip+dim).replace(0,1)).fillna(0)
    df['adx'] = dx.ewm(com=adx_period-1, adjust=False).mean()
    df['bull_cross'] = (df['ema_fast']>df['ema_slow']) & (df['ema_fast'].shift()<=df['ema_slow'].shift())
    df['bear_cross'] = (df['ema_fast']<df['ema_slow']) & (df['ema_fast'].shift()>=df['ema_slow'].shift())
    return df

# ── Trade simulator ─────────────────────────────────────────────────────────
def sim_trade(df, ei, direction, entry, sl, atr_val, max_bars=120):
    tp     = entry + 3*abs(entry-sl) if direction=='buy' else entry - 3*abs(entry-sl)
    sl_cur = sl; be = False; be_lvl = entry + abs(entry-sl) if direction=='buy' else entry - abs(entry-sl)
    sl_dist = abs(entry-sl)
    for j in range(ei+1, min(ei+max_bars, len(df))):
        b = df.iloc[j]
        if direction == 'buy':
            if b['low']  <= sl_cur: return (sl_cur-entry)/sl_dist
            if b['high'] >= tp:     return 3.0
            if not be and b['high']>=be_lvl: be=True; sl_cur=entry
            if be:
                ns=b['high']-atr_val
                if ns>sl_cur: sl_cur=ns
        else:
            if b['high'] >= sl_cur: return (entry-sl_cur)/sl_dist
            if b['low']  <= tp:     return 3.0
            if not be and b['low']<=be_lvl: be=True; sl_cur=entry
            if be:
                ns=b['low']+atr_val
                if ns<sl_cur: sl_cur=ns
    ex = df.iloc[min(ei+max_bars-1, len(df)-1)]['close']
    return ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist

def summarise(name, trades_r, day_of_week=None):
    if len(trades_r) < 10: return None
    arr     = np.array(trades_r)
    risk    = ACCOUNT * RISK_PCT
    pnl_gbp = arr * risk
    wins    = pnl_gbp[pnl_gbp >  5]
    losses  = pnl_gbp[pnl_gbp < -5]
    n       = len(arr)
    wr      = len(wins)/n*100
    gp      = wins.sum()      if len(wins)>0   else 0
    gl      = abs(losses.sum()) if len(losses)>0 else 1
    pf      = gp/gl
    total   = pnl_gbp.sum()
    cum     = np.cumsum(pnl_gbp)
    peak    = np.maximum.accumulate(cum)
    max_dd  = (cum-peak).min()
    monthly = total / max(1, n/18) * 18  # normalise to ~18 trades/mo
    tpm     = n / 24  # ~2 years of data
    verdict = "✅ STRONG" if pf>=1.5 else ("⚠️  OK" if pf>=1.2 else "❌")
    dow_str = f" [{day_of_week}]" if day_of_week else ""
    print(f"  {name:<20}{dow_str:<8} {wr:>5.1f}%  {tpm:>5.1f}/mo  "
          f"£{total*2/24:>7,.0f}@1%  PF:{pf:>5.2f}  DD:£{max_dd*2:>7,.0f}  {verdict}")
    return {'name':name,'pf':pf,'wr':wr,'tpm':tpm,'monthly':total*2/24,'max_dd':max_dd,'n':n}

# ══════════════════════════════════════════════════════════════════════════════
# A. CRYPTO H4 EMA
# ══════════════════════════════════════════════════════════════════════════════

CRYPTO = [
    ("Bitcoin",  "BTC-USD",  0, 24),
    ("Ethereum", "ETH-USD",  0, 24),
    ("Solana",   "SOL-USD",  0, 24),
    ("XRP",      "XRP-USD",  0, 24),
]

def run_h4_ema(name, symbol, s_start, s_end, adx_min=25):
    h1 = get_data(symbol)
    if h1 is None: return None
    df = resample_h4(h1)
    df = add_ema_adx(df)
    trades = []
    for i in range(25, len(df)):
        bar = df.iloc[i]
        if bar['adx'] < adx_min: continue
        in_sess = (s_start <= s_end) and (bar.name.hour >= s_start and bar.name.hour < s_end)
        if s_start == 0 and s_end == 24: in_sess = True
        if not in_sess: continue
        direction = None
        if bar['bull_cross']: direction = 'buy'
        elif bar['bear_cross']: direction = 'sell'
        if direction is None: continue
        entry = bar['close']
        sl    = entry - 1.5*bar['atr'] if direction=='buy' else entry + 1.5*bar['atr']
        r = sim_trade(df, i, direction, entry, sl, bar['atr'])
        trades.append(r)
    return summarise(name, trades)

# ══════════════════════════════════════════════════════════════════════════════
# B. EMA PULLBACK ENTRY
# Wait for crossover, then wait for price to pull back to fast EMA, enter there
# with SL at 0.5*ATR from entry — much tighter than crossover SL
# ══════════════════════════════════════════════════════════════════════════════

PULLBACK_INSTRUMENTS = [
    ("DAX   pullback", "^GDAXI",  8, 16),
    ("UK100 pullback", "^FTSE",   8, 16),
    ("NAS100 pullback","NQ=F",   14, 21),
    ("NatGas pullback","NG=F",   14, 21),
    ("GBPJPY pullback","GBPJPY=X",0,21),
    ("EURCHF pullback","EURCHF=X",8,17),
    ("Bitcoin pullback","BTC-USD",0,24),
]

def run_pullback(name, symbol, s_start, s_end, adx_min=25):
    h1 = get_data(symbol)
    if h1 is None: return None
    df = resample_h4(h1)
    df = add_ema_adx(df)

    trades = []
    pending = None   # {'direction':, 'ema_at_cross':, 'atr':, 'bars_waited':}

    for i in range(25, len(df)):
        bar = df.iloc[i]
        in_sess = True if (s_start==0 and s_end==24) else (bar.name.hour>=s_start and bar.name.hour<s_end)

        # new cross — set pending
        if bar['adx'] >= adx_min:
            if bar['bull_cross']:
                pending = {'dir':'buy','ema':bar['ema_fast'],'atr':bar['atr'],'waited':0}
            elif bar['bear_cross']:
                pending = {'dir':'sell','ema':bar['ema_fast'],'atr':bar['atr'],'waited':0}

        if pending is None: continue
        pending['waited'] += 1
        if pending['waited'] > 8:  # don't wait more than 8 bars for pullback
            pending = None
            continue

        if not in_sess: continue

        # detect pullback to fast EMA
        ef = bar['ema_fast']
        a  = pending['atr']
        touched = False
        if pending['dir']=='buy'  and bar['low']  <= ef + 0.1*a:
            touched = True
        elif pending['dir']=='sell' and bar['high'] >= ef - 0.1*a:
            touched = True

        if not touched: continue

        # enter at close of this bar (conservative)
        entry = bar['close']
        if pending['dir']=='buy':
            sl = entry - 0.8*a
            if entry < ef: pending = None; continue  # price broke below EMA, skip
        else:
            sl = entry + 0.8*a
            if entry > ef: pending = None; continue

        r = sim_trade(df, i, pending['dir'], entry, sl, a)
        trades.append(r)
        pending = None

    return summarise(name, trades)

# ══════════════════════════════════════════════════════════════════════════════
# C. DAY-OF-WEEK BREAKDOWN — London Breakout + US Open ORB
# ══════════════════════════════════════════════════════════════════════════════

DOW_NAMES = {0:'Mon',1:'Tue',2:'Wed',3:'Thu',4:'Fri'}

def run_lb_dow(symbol, pip, min_rng=10, max_rng=100):
    df = get_data(symbol)
    if df is None: return

    trades_by_dow = {d:[] for d in range(5)}
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        dow  = day.dayofweek
        if dow >= 5: continue

        range_bars = df[
            (df.index >= prev + pd.Timedelta(hours=22)) &
            (df.index <  day  + pd.Timedelta(hours=7))
        ]
        if len(range_bars) < 3: continue
        r_hi = range_bars['high'].max()
        r_lo = range_bars['low'].min()
        rng  = r_hi - r_lo
        if not (min_rng <= rng/pip <= max_rng): continue

        entry_bars = df[
            (df.index >= day + pd.Timedelta(hours=7)) &
            (df.index <  day + pd.Timedelta(hours=10))
        ]
        direction = entry = None
        for bt, b in entry_bars.iterrows():
            if b['high'] > r_hi: direction='buy';  entry=r_hi; break
            if b['low']  < r_lo: direction='sell'; entry=r_lo; break
        if direction is None: continue

        buf = rng * 0.15
        sl  = (r_lo - buf) if direction=='buy' else (r_hi + buf)
        sl_dist = abs(entry - sl)
        if sl_dist <= 0: continue

        # sim to 13:00 UTC
        exit_bars = df[
            (df.index > bt) &
            (df.index <= day + pd.Timedelta(hours=13))
        ]
        sl_cur = sl; best = entry; be = False; ex = entry
        for _, b2 in exit_bars.iterrows():
            if direction=='buy':
                if b2['low']  <= sl_cur: ex=sl_cur; break
                if b2['high'] > best: best=b2['high']
                if not be and best>=entry+sl_dist: be=True; sl_cur=entry
                if be:
                    ns=best-sl_dist*TRAIL
                    if ns>sl_cur: sl_cur=ns
            else:
                if b2['high'] >= sl_cur: ex=sl_cur; break
                if b2['low']  < best: best=b2['low']
                if not be and best<=entry-sl_dist: be=True; sl_cur=entry
                if be:
                    ns=best+sl_dist*TRAIL
                    if ns<sl_cur: sl_cur=ns
        else:
            ex = exit_bars.iloc[-1]['close'] if len(exit_bars) else entry

        r = ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist
        trades_by_dow[dow].append(r)

    sym_short = "LB_EUR" if "EUR" in symbol else "LB_GBP"
    print(f"\n  {sym_short} by day:")
    all_trades = []
    for d in range(5):
        t = trades_by_dow[d]
        all_trades.extend(t)
        if len(t) < 5: continue
        wins   = [x for x in t if x>0.05]
        losses = [x for x in t if x<-0.05]
        gp = sum(wins); gl = abs(sum(losses)) if losses else 1
        pf = gp/gl
        wr = len(wins)/len(t)*100
        verdict = "✅" if pf>=1.5 else ("⚠️" if pf>=1.2 else "❌")
        print(f"    {DOW_NAMES[d]}  {len(t):>3} trades  {wr:>5.1f}% win  PF:{pf:>5.2f}  {verdict}")

def run_us_open_dow(symbol, min_rng, max_rng, label):
    df = get_data(symbol)
    if df is None: return

    trades_by_dow = {d:[] for d in range(5)}
    dates = sorted(set(df.index.normalize().date))
    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        dow  = day.dayofweek
        if dow >= 5: continue

        # 13:00 bar = pre-market range
        pm = df[df.index == day + pd.Timedelta(hours=13)]
        if len(pm) == 0: continue
        r_hi = pm.iloc[0]['high']
        r_lo = pm.iloc[0]['low']
        rng  = r_hi - r_lo
        if not (min_rng <= rng <= max_rng): continue

        entry_bars = df[
            (df.index >= day + pd.Timedelta(hours=14)) &
            (df.index <  day + pd.Timedelta(hours=16))
        ]
        direction = entry = entry_time = None
        for bt, b in entry_bars.iterrows():
            if b['high'] > r_hi: direction='buy';  entry=r_hi; entry_time=bt; break
            if b['low']  < r_lo: direction='sell'; entry=r_lo; entry_time=bt; break
        if direction is None: continue

        sl = (r_lo) if direction=='buy' else (r_hi)
        sl_dist = abs(entry - sl)
        if sl_dist <= 0: continue

        exit_bars = df[
            (df.index > entry_time) &
            (df.index <= day + pd.Timedelta(hours=20))
        ]
        sl_cur = sl; best = entry; be = False; ex = entry
        for _, b2 in exit_bars.iterrows():
            if direction=='buy':
                if b2['low']  <= sl_cur: ex=sl_cur; break
                if b2['high'] > best: best=b2['high']
                if not be and best>=entry+sl_dist: be=True; sl_cur=entry
                if be:
                    ns=best-sl_dist*TRAIL
                    if ns>sl_cur: sl_cur=ns
            else:
                if b2['high'] >= sl_cur: ex=sl_cur; break
                if b2['low']  < best: best=b2['low']
                if not be and best<=entry-sl_dist: be=True; sl_cur=entry
                if be:
                    ns=best+sl_dist*TRAIL
                    if ns<sl_cur: sl_cur=ns
        else:
            ex = exit_bars.iloc[-1]['close'] if len(exit_bars) else entry

        r = ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist
        trades_by_dow[dow].append(r)

    print(f"\n  {label} by day:")
    for d in range(5):
        t = trades_by_dow[d]
        if len(t) < 5: continue
        wins   = [x for x in t if x>0.05]
        losses = [x for x in t if x<-0.05]
        gp = sum(wins); gl = abs(sum(losses)) if losses else 1
        pf = gp/gl
        wr = len(wins)/len(t)*100
        verdict = "✅" if pf>=1.5 else ("⚠️" if pf>=1.2 else "❌")
        print(f"    {DOW_NAMES[d]}  {len(t):>3} trades  {wr:>5.1f}% win  PF:{pf:>5.2f}  {verdict}")

# ══════════════════════════════════════════════════════════════════════════════
# D. H1 EMA — same DAX/UK100/NatGas edge but hourly timeframe
# ══════════════════════════════════════════════════════════════════════════════

H1_INSTRUMENTS = [
    ("DAX H1 EMA",    "^GDAXI",   8,  16, 20),
    ("UK100 H1 EMA",  "^FTSE",    8,  16, 20),
    ("NatGas H1 EMA", "NG=F",    14,  21, 20),
    ("NAS100 H1 EMA", "NQ=F",    14,  21, 20),
    ("GBPJPY H1 EMA", "GBPJPY=X", 7,  17, 20),
    ("Gold H1 EMA",   "GC=F",     8,  20, 20),
    ("SP500 H1 EMA",  "ES=F",    14,  21, 20),
]

def run_h1_ema(name, symbol, s_start, s_end, adx_min=20):
    df = get_data(symbol)   # already H1
    if df is None: return None
    df = add_ema_adx(df, fast=10, slow=20, adx_period=14)
    trades = []
    for i in range(25, len(df)):
        bar = df.iloc[i]
        h   = bar.name.hour
        if not (s_start <= h < s_end): continue
        if bar['adx'] < adx_min: continue
        direction = None
        if bar['bull_cross']: direction = 'buy'
        elif bar['bear_cross']: direction = 'sell'
        if direction is None: continue
        entry = bar['close']
        sl    = entry - 1.5*bar['atr'] if direction=='buy' else entry + 1.5*bar['atr']
        r = sim_trade(df, i, direction, entry, sl, bar['atr'], max_bars=48)
        trades.append(r)
    return summarise(name, trades)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  UNEXPLORED TERRITORY — 4 new experiments")
    print("  2 years data | 0.5% risk | Trail 0.5R | £70k account")
    print("="*80)
    print(f"\n  {'Strategy':<22} {'Win%':>5}  {'T/mo':>5}  {'Monthly@1%':>10}  "
          f"{'PF':>6}  {'DD@1%':>9}  Verdict")
    print(f"  {'─'*76}")

    # ── A. CRYPTO ────────────────────────────────────────────────────────────
    print("\n  A. CRYPTO H4 EMA (24/7 trending machines)")
    print(f"  {'─'*76}")
    crypto_results = []
    for args in CRYPTO:
        r = run_h4_ema(*args, adx_min=20)  # slightly lower ADX for crypto
        if r: crypto_results.append(r)

    # ── B. EMA PULLBACK ──────────────────────────────────────────────────────
    print("\n  B. EMA PULLBACK ENTRY (retest EMA after crossover)")
    print(f"  {'─'*76}")
    pullback_results = []
    for args in PULLBACK_INSTRUMENTS:
        r = run_pullback(*args, adx_min=22)
        if r: pullback_results.append(r)

    # ── C. DAY OF WEEK ──────────────────────────────────────────────────────
    print("\n  C. DAY-OF-WEEK BREAKDOWN")
    print(f"  {'─'*76}")
    run_lb_dow("EURUSD=X", pip=0.0001)
    run_lb_dow("GBPUSD=X", pip=0.0001)
    run_us_open_dow("NQ=F",  50,  1500, "NAS100 US Open")
    run_us_open_dow("NG=F",  0.03, 1.0, "NatGas US Open")
    run_us_open_dow("ES=F",  10,   200, "SP500  US Open")

    # ── D. H1 EMA ───────────────────────────────────────────────────────────
    print("\n\n  D. H1 EMA — same strategy, hourly timeframe (more signals)")
    print(f"  {'─'*76}")
    h1_results = []
    for args in H1_INSTRUMENTS:
        r = run_h1_ema(*args)
        if r: h1_results.append(r)

    # ── FINAL SUMMARY ────────────────────────────────────────────────────────
    all_results = crypto_results + pullback_results + h1_results
    all_results.sort(key=lambda x: x['pf'], reverse=True)
    strong = [r for r in all_results if r['pf'] >= 1.5]
    ok     = [r for r in all_results if 1.2 <= r['pf'] < 1.5]

    print(f"\n{'='*80}")
    print(f"  RANKING — NEW DISCOVERIES")
    print(f"{'='*80}")
    print(f"\n  ✅ STRONG (PF >= 1.5) — candidates for EA:")
    for r in strong:
        print(f"     {r['name']:<22} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']:,.0f}/mo @1%")
    print(f"\n  ⚠️  MARGINAL (PF 1.2-1.5):")
    for r in ok:
        print(f"     {r['name']:<22} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']:,.0f}/mo @1%")
    print()
