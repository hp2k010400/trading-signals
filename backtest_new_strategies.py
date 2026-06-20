"""
backtest_new_strategies.py — 3 new strategy archetypes

1. PDH/PDL BREAKOUT — previous day high/low as institutional entry trigger
   Instruments: DAX, UK100, NAS100, SP500, NatGas, Gold, EURUSD, GBPUSD, GBPJPY

2. BB/KC SQUEEZE (Carter) — Bollinger Band inside Keltner Channel = compression
   releases = explosive move. Enter on the first bar that breaks compression.
   Instruments: DAX, NAS100, SP500, NatGas, Gold, EURUSD, GBPJPY

3. M30 ORB — first 30-min bar as range (tighter than H1)
   ⚠️  yfinance 30-min data = 60 days only. Directional test, not final verdict.
   Instruments: DAX, UK100, NAS100, SP500, NatGas, EURUSD, GBPUSD

All: 0.2R trail (consistent with other breakout strategies)

Run: python backtest_new_strategies.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT = 70_000
RISK    = ACCOUNT * 0.005   # £350 @ 0.5%
TRAIL   = 0.2

# ── Data ──────────────────────────────────────────────────────────────────────
_cache = {}

def get_data(sym, interval="1h", period="730d"):
    key = (sym, interval, period)
    if key not in _cache:
        try:
            df = yf.download(sym, interval=interval, period=period,
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None: df.index = df.index.tz_localize('UTC')
            else:                   df.index = df.index.tz_convert('UTC')
            _cache[key] = df if len(df) > 30 else None
        except: _cache[key] = None
    return _cache[key]

def calc_atr(df, period=14):
    hi, lo, cl = df['high'], df['low'], df['close']
    tr = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],
                   axis=1).max(axis=1)
    return tr.ewm(com=period-1, adjust=False).mean()

# ── Simulator (0.2R trail) ────────────────────────────────────────────────────
def sim(bars_df, direction, entry, sl, trail_mult=TRAIL, max_bars=60):
    sl_dist = abs(entry - sl)
    if sl_dist <= 0 or len(bars_df) == 0: return 0.0
    trail  = sl_dist * trail_mult
    sl_cur = sl; best = entry; be = False
    rows   = bars_df.iloc[:max_bars]
    ex     = rows.iloc[-1]['close']
    for _, b in rows.iterrows():
        if direction == 'buy':
            if b['low']  <= sl_cur: return (sl_cur-entry)/sl_dist
            if b['high'] > best:    best = b['high']
            if not be and best >= entry+sl_dist: be=True; sl_cur=entry
            if be:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur: return (entry-sl_cur)/sl_dist
            if b['low']  < best:    best = b['low']
            if not be and best <= entry-sl_dist: be=True; sl_cur=entry
            if be:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns
    return ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist

# ── Stats ──────────────────────────────────────────────────────────────────────
def stats(trades, label=""):
    if len(trades) < 10: return None
    arr   = np.array([t['r'] for t in trades])
    gbp   = arr * RISK
    wins  = gbp[gbp >  5]; losses = gbp[gbp < -5]
    n     = len(arr)
    wr    = len(wins)/n*100
    pf_   = wins.sum() / (abs(losses.sum()) if len(losses) else 1)
    total = gbp.sum()
    cum   = np.cumsum(gbp); pk = np.maximum.accumulate(cum)
    dd    = (cum-pk).min()
    days  = max(1,(trades[-1]['date']-trades[0]['date']).days)
    mo    = total/days*30
    tpm   = n/days*30
    v     = "✅ STRONG" if pf_>=1.5 else ("⚠️  OK" if pf_>=1.2 else "❌")
    note  = f" [{label}]" if label else ""
    print(f"  {(name+note):<30} {wr:>5.1f}%  {tpm:>5.1f}/mo  "
          f"£{mo*2:>7,.0f}@1%  PF:{pf_:>5.2f}  DD:£{dd*2:>7,.0f}  {v}")
    return {'name':name,'wr':round(wr,1),'pf':round(pf_,2),
            'mo':round(mo*2,0),'dd':round(dd*2,0),'tpm':round(tpm,1),'n':n}

# ══════════════════════════════════════════════════════════════════════════════
# 1. PDH/PDL BREAKOUT
# Previous day high/low = institutional magnet levels.
# When price breaks PDH → buy (trend continuation / liquidity sweep)
# SL = 1.5×ATR below entry (not at PDL — keep SL tight)
# ══════════════════════════════════════════════════════════════════════════════

PDH_INSTRUMENTS = [
    # (name, symbol, session_start, session_end, min_rng_atr, max_rng_atr)
    ("PDH DAX",    "^GDAXI",   8,  17,  0.4, 4.0),
    ("PDH UK100",  "^FTSE",    8,  17,  0.4, 4.0),
    ("PDH NAS100", "NQ=F",    14,  21,  0.3, 4.0),
    ("PDH SP500",  "ES=F",    14,  21,  0.3, 4.0),
    ("PDH NatGas", "NG=F",    14,  21,  0.3, 4.0),
    ("PDH Gold",   "GC=F",     8,  20,  0.3, 4.0),
    ("PDH EURUSD", "EURUSD=X", 7,  17,  0.3, 4.0),
    ("PDH GBPUSD", "GBPUSD=X", 7,  17,  0.3, 4.0),
    ("PDH GBPJPY", "GBPJPY=X", 7,  17,  0.3, 4.0),
]

def run_pdh(sym, s_start, s_end, min_ra, max_ra):
    df = get_data(sym)
    if df is None: return []
    df['atr'] = calc_atr(df)
    trades = []
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day  = pd.Timestamp(d, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if day.dayofweek >= 5: continue

        # Build previous day's range (all H1 bars from that calendar day)
        prev_bars = df[df.index.normalize() == prev.normalize()]
        if len(prev_bars) < 4: continue
        pdh = prev_bars['high'].max()
        pdl = prev_bars['low'].min()
        prev_rng = pdh - pdl

        # ATR at start of today
        atr_row = df[df.index < day]
        if len(atr_row) == 0: continue
        atr = atr_row['atr'].iloc[-1]
        if atr <= 0: continue

        # Previous day range quality filter
        if prev_rng < min_ra * atr: continue
        if prev_rng > max_ra * atr: continue

        # Session bars today — find first break of PDH or PDL
        sb = df[(df.index >= day+pd.Timedelta(hours=s_start)) &
                (df.index <  day+pd.Timedelta(hours=s_end))]
        if len(sb) < 2: continue

        buf       = atr * 0.05           # tiny buffer to confirm break
        direction = entry = et = None
        for bt, b in sb.iterrows():
            if b['high'] > pdh + buf:
                direction='buy';  entry=pdh+buf; et=bt; break
            if b['low']  < pdl - buf:
                direction='sell'; entry=pdl-buf; et=bt; break
        if direction is None: continue

        # Tight ATR-based SL — if price retreats 1.5×ATR from the PDH/PDL level, exit
        sl = (entry-1.5*atr) if direction=='buy' else (entry+1.5*atr)
        if abs(entry-sl) <= 0: continue

        eb = df[(df.index > et) &
                (df.index <= day+pd.Timedelta(hours=s_end))]
        r = sim(eb, direction, entry, sl)
        trades.append({'r':r,'date':day,'month':day.month})

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 2. BOLLINGER BAND / KELTNER CHANNEL SQUEEZE (John Carter method)
# Squeeze ON:  Bollinger Bands are INSIDE Keltner Channel (volatility compressed)
# Squeeze OFF: BB breaks outside KC = release = big move starting
# Momentum: direction determined by close vs KC midpoint
# ══════════════════════════════════════════════════════════════════════════════

BB_INSTRUMENTS = [
    # (name, symbol, session_start, session_end)
    ("BB DAX",    "^GDAXI",   8,  17),
    ("BB UK100",  "^FTSE",    8,  17),
    ("BB NAS100", "NQ=F",    14,  21),
    ("BB SP500",  "ES=F",    14,  21),
    ("BB NatGas", "NG=F",    14,  21),
    ("BB Gold",   "GC=F",     8,  20),
    ("BB EURUSD", "EURUSD=X", 7,  17),
    ("BB GBPJPY", "GBPJPY=X", 7,  17),
]

def add_squeeze(df, bb_p=20, bb_std=2.0, kc_p=20, kc_mult=1.5):
    d = df.copy()
    # Bollinger Bands
    sma       = d['close'].rolling(bb_p).mean()
    std_      = d['close'].rolling(bb_p).std()
    d['bb_up'] = sma + bb_std * std_
    d['bb_lo'] = sma - bb_std * std_
    # Keltner Channel
    atr       = calc_atr(d, kc_p)
    ema       = d['close'].ewm(span=kc_p, adjust=False).mean()
    d['kc_up'] = ema + kc_mult * atr
    d['kc_lo'] = ema - kc_mult * atr
    d['kc_mid']= ema
    d['atr']   = atr
    # Squeeze: BB completely inside KC
    d['in_sq'] = (d['bb_up'] <= d['kc_up']) & (d['bb_lo'] >= d['kc_lo'])
    # Momentum: close vs KC midpoint (determines direction when squeeze releases)
    d['mom']   = d['close'] - d['kc_mid']
    return d

def run_bb(sym, s_start, s_end):
    df = get_data(sym)
    if df is None: return []
    df = add_squeeze(df)
    trades = []
    fired  = set()

    for i in range(40, len(df)):
        bar = df.iloc[i]
        if bar.name.dayofweek >= 5: continue
        h = bar.name.hour
        if not (s_start <= h < s_end): continue

        date_key = bar.name.date()
        if date_key in fired: continue

        prev = df.iloc[i-1]

        # Squeeze must have been ON last bar, OFF this bar (the release moment)
        if not prev['in_sq']: continue
        if bar['in_sq']:      continue

        # Direction from momentum at release
        direction = 'buy' if bar['mom'] > 0 else 'sell'

        entry = bar['close']
        atr   = bar['atr']
        sl    = (entry-1.5*atr) if direction=='buy' else (entry+1.5*atr)
        if abs(entry-sl) <= 0: continue

        day = pd.Timestamp(bar.name.date(), tz='UTC')
        eb  = df[(df.index > bar.name) &
                 (df.index <= day+pd.Timedelta(hours=s_end))]
        r = sim(eb, direction, entry, sl)
        trades.append({'r':r,'date':day,'month':bar.name.month})
        fired.add(date_key)

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 3. M30 ORB — first 30-minute bar of session as the range
# Tighter range = cleaner SL = better R:R vs H1 ORB
# ⚠️  yfinance limits 30-min data to 60 days — directional test only
# ══════════════════════════════════════════════════════════════════════════════

M30_INSTRUMENTS = [
    # (name, symbol, range_hour, entry_start_hour, exit_hour, min_rng, max_rng)
    ("M30 DAX",    "^GDAXI",  8,   9,  13,  10,  400),
    ("M30 UK100",  "^FTSE",   8,   9,  13,   8,  200),
    ("M30 NAS100", "NQ=F",   14,  15,  19,  25, 1200),
    ("M30 SP500",  "ES=F",   14,  15,  19,   5,  250),
    ("M30 NatGas", "NG=F",   14,  15,  19, 0.01,  0.8),
    ("M30 EURUSD", "EURUSD=X",7,   8,  11, 0.0003,0.015),
    ("M30 GBPUSD", "GBPUSD=X",7,   8,  11, 0.0003,0.018),
]

def run_m30(sym, rng_h, entry_h, exit_h, min_rng, max_rng):
    df = get_data(sym, interval="30m", period="60d")
    if df is None: return []
    trades = []
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day = pd.Timestamp(d, tz='UTC')
        if day.dayofweek >= 5: continue

        # First M30 bar of session (the range-forming bar)
        rb = df[(df.index >= day+pd.Timedelta(hours=rng_h)) &
                (df.index <  day+pd.Timedelta(hours=rng_h+0.5))]
        if len(rb) == 0: continue
        r_hi = rb['high'].max()
        r_lo = rb['low'].min()
        rng  = r_hi - r_lo
        if not (min_rng <= rng <= max_rng): continue

        # Entry bars — session after the range bar
        eb = df[(df.index >= day+pd.Timedelta(hours=entry_h)) &
                (df.index <  day+pd.Timedelta(hours=exit_h))]
        if len(eb) < 2: continue

        direction = entry = et = None
        for bt, b in eb.iterrows():
            if b['high'] > r_hi: direction='buy';  entry=r_hi; et=bt; break
            if b['low']  < r_lo: direction='sell'; entry=r_lo; et=bt; break
        if direction is None: continue

        buf = rng * 0.15
        sl  = (r_lo-buf) if direction=='buy' else (r_hi+buf)
        if abs(entry-sl) <= 0: continue

        exit_bars = df[(df.index > et) &
                       (df.index <= day+pd.Timedelta(hours=exit_h))]
        r = sim(exit_bars, direction, entry, sl, max_bars=25)
        trades.append({'r':r,'date':day,'month':day.month})

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*85)
    print("  NEW STRATEGIES — PDH/PDL Breakout | BB/KC Squeeze | M30 ORB")
    print("  H1 data 2yr | Trail 0.2R | 0.5% risk | £70k account")
    print("="*85)
    print(f"\n  {'Strategy':<30} {'Win%':>5}  {'T/mo':>5}  {'Monthly@1%':>10}  "
          f"{'PF':>5}  {'DD@1%':>8}  Verdict")
    print(f"  {'─'*82}")

    all_results = []

    # 1. PDH/PDL
    print("\n  1. PREVIOUS DAY HIGH/LOW BREAKOUT  (2yr H1)")
    print(f"  {'─'*82}")
    for row in PDH_INSTRUMENTS:
        name = row[0]
        trades = run_pdh(row[1], row[2], row[3], row[4], row[5])
        s = stats(trades)
        if s: all_results.append(s)

    # 2. BB/KC Squeeze
    print("\n  2. BB/KC SQUEEZE (Carter)  (2yr H1)")
    print(f"  {'─'*82}")
    for row in BB_INSTRUMENTS:
        name = row[0]
        trades = run_bb(row[1], row[2], row[3])
        s = stats(trades)
        if s: all_results.append(s)

    # 3. M30 ORB
    print("\n  3. M30 ORB  ⚠️  60-day sample — directional test, not final verdict")
    print(f"  {'─'*82}")
    for row in M30_INSTRUMENTS:
        name = row[0]
        trades = run_m30(row[1], row[2], row[3], row[4], row[5], row[6])
        s = stats(trades, label="60d")
        if s: all_results.append(s)

    # ── Final ranking ─────────────────────────────────────────────────────────
    strong = sorted([r for r in all_results if r['pf']>=1.5], key=lambda x:-x['pf'])
    ok     = sorted([r for r in all_results if 1.2<=r['pf']<1.5], key=lambda x:-x['pf'])

    print(f"\n{'='*85}")
    print("  RANKING — EA CANDIDATES")
    print(f"{'='*85}")

    print(f"\n  ✅ STRONG (PF ≥ 1.5) — add to EA:")
    for r in strong:
        print(f"     {r['name']:<25} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['mo']:,.0f}/mo @1%")

    print(f"\n  ⚠️  MARGINAL (PF 1.2–1.5):")
    for r in ok:
        print(f"     {r['name']:<25} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['mo']:,.0f}/mo @1%")

    if strong:
        total_mo = sum(r['mo'] for r in strong)
        total_tpm = sum(r['tpm'] for r in strong)
        print(f"\n  Combined strong at 0.5% risk each:")
        print(f"  Monthly: £{total_mo//2:,.0f}/mo  |  Trades: ~{total_tpm:.0f}/month")
    print()
