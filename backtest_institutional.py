"""
backtest_institutional.py — 8 Institutional & Elite Strategy Types

1. FAIR VALUE GAP (FVG)     — ICT / Smart Money: 3-bar imbalance, enter on retest
2. PREV WEEK HIGH/LOW       — Weekly PDH/PDL (bigger institutional levels)
3. AMD MANIPULATION         — ICT: Asian range stop hunt, enter the reversal
4. DONCHIAN 20-DAY          — Turtle Trading System (CTAs, systematic funds)
5. END OF MONTH FLOW        — Pension/fund rebalancing bias last+first 3 days
6. VWAP DEVIATION           — Goldman/institutional: fade extreme VWAP deviations
7. PAIRS MEAN REVERSION     — Stat arb: NAS100 vs SP500 relative performance
8. LIQUIDITY SWEEP REVERSAL — Stop hunt fade: PDH/PDL false break then reverse

All: 0.2R trail | 0.5% risk | £70k account | 2yr H1 data

Run: python backtest_institutional.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT = 70_000
RISK    = ACCOUNT * 0.005
TRAIL   = 0.2

# ── Data ──────────────────────────────────────────────────────────────────────
_cache = {}
def get_h1(sym):
    if sym not in _cache:
        try:
            df = yf.download(sym, interval="1h", period="730d",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None: df.index = df.index.tz_localize('UTC')
            else:                   df.index = df.index.tz_convert('UTC')
            hi,lo,cl = df['high'],df['low'],df['close']
            tr = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],
                           axis=1).max(axis=1)
            df['atr'] = tr.ewm(com=13, adjust=False).mean()
            _cache[sym] = df if len(df) > 200 else None
        except: _cache[sym] = None
    return _cache[sym]

# ── Simulator ──────────────────────────────────────────────────────────────────
def sim(bars_df, direction, entry, sl, max_bars=48):
    sl_dist = abs(entry - sl)
    if sl_dist <= 0 or len(bars_df) == 0: return 0.0
    trail  = sl_dist * TRAIL
    sl_cur = sl; best = entry; be = False
    ex     = bars_df.iloc[-1]['close']
    for _, b in bars_df.iloc[:max_bars].iterrows():
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

# ── Stats printer ─────────────────────────────────────────────────────────────
all_results = []

def show(trades, name):
    if len(trades) < 12: return
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
    mo    = total/days*30; tpm = n/days*30
    v     = "✅ STRONG" if pf_>=1.5 else ("⚠️  OK" if pf_>=1.2 else "❌")
    print(f"  {name:<28} {wr:>5.1f}%  {tpm:>5.1f}/mo  "
          f"£{mo*2:>7,.0f}@1%  PF:{pf_:>5.2f}  DD:£{dd*2:>7,.0f}  {v}")
    all_results.append({'name':name,'pf':round(pf_,2),'wr':round(wr,1),
                        'mo':round(mo*2,0),'tpm':round(tpm,1),'dd':round(dd*2,0)})

# ══════════════════════════════════════════════════════════════════════════════
# 1. FAIR VALUE GAP (FVG) — ICT Smart Money
# 3-bar imbalance: a strong impulse candle leaves a gap between bar[i-2]
# and bar[i]. Price later retraces INTO that gap → enter in impulse direction.
# Bullish FVG: bar[i-2].high < bar[i].low → retest = buy
# Bearish FVG: bar[i-2].low  > bar[i].high → retest = sell
# ══════════════════════════════════════════════════════════════════════════════

FVG_INSTRUMENTS = [
    ("FVG DAX",    "^GDAXI",   8, 17),
    ("FVG UK100",  "^FTSE",    8, 17),
    ("FVG NAS100", "NQ=F",    14, 21),
    ("FVG SP500",  "ES=F",    14, 21),
    ("FVG NatGas", "NG=F",    14, 21),
    ("FVG EURUSD", "EURUSD=X", 7, 17),
    ("FVG GBPJPY", "GBPJPY=X", 7, 17),
]

def run_fvg(sym, s_start, s_end, min_gap_atr=0.15, max_age=16):
    df = get_h1(sym)
    if df is None: return []
    trades = []; open_fvgs = []; fired = set()

    for i in range(3, len(df)):
        bar = df.iloc[i]
        if bar.name.dayofweek >= 5: continue
        atr = bar['atr']
        if atr <= 0: continue

        # Build new FVGs from 3-bar pattern ending at bar[i]
        b0, b2 = df.iloc[i-2], df.iloc[i]
        gap_bull = b2['low']  - b0['high']   # bullish: gap above b0
        gap_bear = b0['low']  - b2['high']   # bearish: gap below b0 (wait, corrected below)

        if gap_bull > min_gap_atr * atr:
            open_fvgs.append({'t':'bull','hi':b2['low'],'lo':b0['high'],'age':0})
        gap_bear2 = b0['low'] - b2['high']
        if gap_bear2 > min_gap_atr * atr:
            open_fvgs.append({'t':'bear','hi':b0['low'],'lo':b2['high'],'age':0})

        # Age and prune
        for f in open_fvgs: f['age'] += 1
        open_fvgs = [f for f in open_fvgs if f['age'] <= max_age]

        # Session filter
        h = bar.name.hour
        if not (s_start <= h < s_end): continue
        date_key = bar.name.date()
        if date_key in fired: continue

        # Check if price is entering any open FVG
        for f in list(open_fvgs):
            if f['age'] < 2: continue  # don't trade the candle that created it
            entry = sl = direction = None

            if f['t'] == 'bull':
                # Bullish FVG: price retraces DOWN into gap → buy
                if bar['low'] <= f['hi'] and bar['close'] >= f['lo']:
                    direction = 'buy'
                    entry     = bar['close']
                    sl        = f['lo'] - 0.5*atr
            else:
                # Bearish FVG: price retraces UP into gap → sell
                if bar['high'] >= f['lo'] and bar['close'] <= f['hi']:
                    direction = 'sell'
                    entry     = bar['close']
                    sl        = f['hi'] + 0.5*atr

            if direction is None: continue
            if abs(entry-sl) <= 0: continue

            day = pd.Timestamp(bar.name.date(), tz='UTC')
            eb  = df[(df.index > bar.name) &
                     (df.index <= day+pd.Timedelta(hours=s_end))]
            r   = sim(eb, direction, entry, sl)
            trades.append({'r':r,'date':day,'month':bar.name.month})
            open_fvgs.remove(f)
            fired.add(date_key)
            break

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 2. PREVIOUS WEEK HIGH/LOW (PWH/PWL)
# Weekly version of PDH/PDL — larger institutional levels.
# Fires 1-2x per instrument per week when price breaks previous week's range.
# ══════════════════════════════════════════════════════════════════════════════

PWH_INSTRUMENTS = [
    ("PWH DAX",    "^GDAXI",   8, 17),
    ("PWH UK100",  "^FTSE",    8, 17),
    ("PWH NAS100", "NQ=F",    14, 21),
    ("PWH SP500",  "ES=F",    14, 21),
    ("PWH NatGas", "NG=F",    14, 21),
    ("PWH EURUSD", "EURUSD=X", 7, 17),
    ("PWH GBPUSD", "GBPUSD=X", 7, 17),
    ("PWH GBPJPY", "GBPJPY=X", 7, 17),
]

def run_pwh(sym, s_start, s_end):
    df = get_h1(sym)
    if df is None: return []
    trades = []; fired = set()
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day = pd.Timestamp(d, tz='UTC')
        if day.dayofweek >= 5: continue
        date_key = day.date()
        if date_key in fired: continue

        # Previous week: Monday to Friday of last week
        cur_mon  = day - pd.Timedelta(days=day.dayofweek)
        prev_mon = cur_mon - pd.Timedelta(weeks=1)
        pw_bars  = df[(df.index >= prev_mon) & (df.index < cur_mon)]
        if len(pw_bars) < 10: continue

        pwh = pw_bars['high'].max()
        pwl = pw_bars['low'].min()
        rng = pwh - pwl
        if rng <= 0: continue

        atr_row = df[df.index < day]
        if len(atr_row) == 0: continue
        atr = atr_row['atr'].iloc[-1]
        if atr <= 0 or rng < 0.5*atr or rng > 6*atr: continue

        sb = df[(df.index >= day+pd.Timedelta(hours=s_start)) &
                (df.index <  day+pd.Timedelta(hours=s_end))]
        if len(sb) < 2: continue

        buf = atr * 0.05
        direction = entry = et = None
        for bt, b in sb.iterrows():
            if b['high'] > pwh+buf: direction='buy';  entry=pwh+buf; et=bt; break
            if b['low']  < pwl-buf: direction='sell'; entry=pwl-buf; et=bt; break
        if direction is None: continue

        sl = (entry-1.5*atr) if direction=='buy' else (entry+1.5*atr)
        if abs(entry-sl) <= 0: continue

        eb = df[(df.index > et) & (df.index <= day+pd.Timedelta(hours=s_end))]
        r  = sim(eb, direction, entry, sl)
        trades.append({'r':r,'date':day,'month':day.month})
        fired.add(date_key)

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 3. AMD MANIPULATION REVERSAL (ICT)
# Asian range = accumulation. London 07:00-09:00 = manipulation (fake break).
# Signal: price sweeps the Asian high OR low then CLOSES BACK INSIDE the range.
# = Institutions grabbed the retail stops, real move now goes the other way.
# Enter: at close of the manipulation candle. Direction: opposite to the sweep.
# ══════════════════════════════════════════════════════════════════════════════

AMD_INSTRUMENTS = [
    ("AMD EURUSD", "EURUSD=X", 0.0001),
    ("AMD GBPUSD", "GBPUSD=X", 0.0001),
    ("AMD GBPJPY", "GBPJPY=X", 0.01),
    ("AMD DAX",    "^GDAXI",   None),
    ("AMD NAS100", "NQ=F",     None),
]

def run_amd(sym, pip):
    df = get_h1(sym)
    if df is None: return []
    trades = []
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day  = pd.Timestamp(d, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if day.dayofweek >= 5 or day.dayofweek == 0: continue

        # Asian range (previous 22:00 → today 07:00)
        ab = df[(df.index >= prev+pd.Timedelta(hours=22)) &
                (df.index <  day +pd.Timedelta(hours=7))]
        if len(ab) < 3: continue
        ah = ab['high'].max(); al = ab['low'].min()
        rng = ah - al
        if pip and rng/pip < 8: continue
        if rng <= 0: continue

        atr_row = df[df.index < day]
        if len(atr_row) == 0: continue
        atr = atr_row['atr'].iloc[-1]
        if atr <= 0: continue

        # London manipulation window 07:00-09:00
        lb = df[(df.index >= day+pd.Timedelta(hours=7)) &
                (df.index <  day+pd.Timedelta(hours=9))]
        direction = entry = sl = et = None

        for bt, b in lb.iterrows():
            sweep_up   = b['high'] > ah and b['close'] < ah
            sweep_down = b['low']  < al and b['close'] > al

            if sweep_up and (b['high']-ah) < rng*0.6:
                # Swept above Asian high and rejected → SELL
                direction='sell'; entry=b['close']; sl=b['high']+atr*0.1; et=bt; break
            if sweep_down and (al-b['low']) < rng*0.6:
                # Swept below Asian low and rejected → BUY
                direction='buy'; entry=b['close']; sl=b['low']-atr*0.1; et=bt; break

        if direction is None: continue
        if abs(entry-sl) <= 0: continue

        eb = df[(df.index > et) & (df.index <= day+pd.Timedelta(hours=17))]
        r  = sim(eb, direction, entry, sl)
        trades.append({'r':r,'date':day,'month':day.month})

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 4. DONCHIAN 20-DAY BREAKOUT (Turtle Trading)
# New 20-day high → buy. New 20-day low → sell.
# Exit: 10-day counter-channel or 2×ATR trail.
# Works on trending commodities (NatGas, Gold) and indices.
# ══════════════════════════════════════════════════════════════════════════════

DONCHIAN_INSTRUMENTS = [
    ("DCH NatGas", "NG=F",     20, 10),
    ("DCH Gold",   "GC=F",     20, 10),
    ("DCH DAX",    "^GDAXI",   20, 10),
    ("DCH NAS100", "NQ=F",     20, 10),
    ("DCH Oil",    "CL=F",     20, 10),
]

def run_donchian(sym, n_enter=20, n_exit=10):
    df = get_h1(sym)
    if df is None: return []

    daily = df.resample('1D').agg({'open':'first','high':'max',
                                   'low':'min','close':'last'}).dropna()
    daily = daily[daily.index.dayofweek < 5]
    hi,lo,cl = daily['high'],daily['low'],daily['close']
    tr = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],
                   axis=1).max(axis=1)
    daily['atr']   = tr.ewm(com=13, adjust=False).mean()
    daily['d_hi']  = daily['high'].rolling(n_enter).max().shift(1)
    daily['d_lo']  = daily['low'].rolling(n_enter).min().shift(1)
    daily['x_hi']  = daily['high'].rolling(n_exit).max().shift(1)
    daily['x_lo']  = daily['low'].rolling(n_exit).min().shift(1)

    trades = []; trade = None

    for i in range(n_enter+1, len(daily)):
        row = daily.iloc[i]
        ts  = row.name if row.name.tzinfo else pd.Timestamp(row.name, tz='UTC')
        if pd.isna(row['d_hi']): continue
        atr = row['atr']

        # Manage open trade
        if trade:
            sl = trade['sl']
            if trade['dir'] == 'buy':
                if row['low'] <= sl or row['close'] < row['x_lo']:
                    ex = min(sl, row['x_lo']) if row['close'] < row['x_lo'] else sl
                    trades.append({'r':(ex-trade['e'])/trade['sld'],
                                   'date':trade['date'],'month':trade['date'].month})
                    trade = None
                else:
                    new_sl = row['high'] - 2*atr
                    if new_sl > trade['sl']: trade['sl'] = new_sl
            else:
                if row['high'] >= sl or row['close'] > row['x_hi']:
                    ex = max(sl, row['x_hi']) if row['close'] > row['x_hi'] else sl
                    trades.append({'r':(trade['e']-ex)/trade['sld'],
                                   'date':trade['date'],'month':trade['date'].month})
                    trade = None

        # New entry
        if trade is None and atr > 0:
            sld = 2*atr
            if row['close'] > row['d_hi']:
                trade = {'dir':'buy','e':row['close'],'sl':row['close']-sld,'sld':sld,'date':ts}
            elif row['close'] < row['d_lo']:
                trade = {'dir':'sell','e':row['close'],'sl':row['close']+sld,'sld':sld,'date':ts}

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 5. END-OF-MONTH FLOW
# Last 3 + first 3 trading days of each month — institutional rebalancing
# creates upward bias on equities. Buy pullbacks during this window only.
# Entry: H1 bar that retraces > 0.8×ATR below the session's 5-bar SMA.
# ══════════════════════════════════════════════════════════════════════════════

EOM_INSTRUMENTS = [
    ("EOM NAS100", "NQ=F",   14, 20),
    ("EOM SP500",  "ES=F",   14, 20),
    ("EOM DAX",    "^GDAXI",  8, 16),
    ("EOM UK100",  "^FTSE",   8, 16),
]

def eom_window(dates_in_month, current_date):
    month = current_date.month; year = current_date.year
    mo_days = [d for d in dates_in_month
               if d.month==month and d.year==year]
    mo_days.sort()
    if not mo_days: return False
    # Next month
    nm = month+1 if month<12 else 1; ny = year if month<12 else year+1
    next_mo = [d for d in dates_in_month if d.month==nm and d.year==ny]
    next_mo.sort()
    last3  = mo_days[-3:]
    first3 = next_mo[:3]
    return current_date.date() in [d.date() for d in last3+first3]

def run_eom(sym, s_start, s_end):
    df = get_h1(sym)
    if df is None: return []
    dates_in_month = [pd.Timestamp(d, tz='UTC')
                      for d in sorted(set(df.index.normalize().date))]
    trades = []; fired = set()

    for d in dates_in_month:
        day = d
        if day.dayofweek >= 5: continue
        if not eom_window(dates_in_month, day): continue

        sb = df[(df.index >= day+pd.Timedelta(hours=s_start)) &
                (df.index <  day+pd.Timedelta(hours=s_end))]
        if len(sb) < 6: continue

        date_key = day.date()
        if date_key in fired: continue

        sma5 = sb['close'].rolling(5).mean()
        for idx in range(5, len(sb)):
            b   = sb.iloc[idx]
            s   = sma5.iloc[idx]
            atr = b['atr']
            if pd.isna(s) or atr <= 0: continue
            # Pullback: close is > 0.8×ATR below 5-bar SMA → buy dip
            if b['close'] < s - 0.8*atr:
                entry = b['close']
                sl    = entry - 1.5*atr
                eb    = df[(df.index > b.name) &
                           (df.index <= day+pd.Timedelta(hours=s_end))]
                r     = sim(eb, 'buy', entry, sl)
                trades.append({'r':r,'date':day,'month':day.month})
                fired.add(date_key)
                break

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 6. VWAP DEVIATION FADE
# Goldman/Citi benchmark: when price extends > threshold×ATR from session VWAP,
# fade it back. Mean reversion. Exit when price returns to VWAP or trails.
# ══════════════════════════════════════════════════════════════════════════════

VWAP_INSTRUMENTS = [
    ("VWAP DAX",    "^GDAXI",  8, 16, 1.8),
    ("VWAP UK100",  "^FTSE",   8, 16, 1.8),
    ("VWAP NAS100", "NQ=F",   14, 20, 1.8),
    ("VWAP SP500",  "ES=F",   14, 20, 1.8),
    ("VWAP NatGas", "NG=F",   14, 20, 1.5),
    ("VWAP EURUSD", "EURUSD=X",7, 17, 1.8),
]

def run_vwap(sym, s_start, s_end, threshold=1.8):
    df = get_h1(sym)
    if df is None: return []
    trades = []
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day = pd.Timestamp(d, tz='UTC')
        if day.dayofweek >= 5: continue

        sb = df[(df.index >= day+pd.Timedelta(hours=s_start)) &
                (df.index <  day+pd.Timedelta(hours=s_end))].copy()
        if len(sb) < 4: continue

        tp      = (sb['high']+sb['low']+sb['close'])/3
        cum_pv  = (tp * sb['volume']).cumsum()
        cum_v   = sb['volume'].cumsum().replace(0, np.nan)
        sb['vwap'] = cum_pv / cum_v

        fired_today = False
        for idx in range(3, len(sb)):
            if fired_today: break
            b   = sb.iloc[idx]
            v   = sb['vwap'].iloc[idx]
            atr = b['atr']
            if pd.isna(v) or atr <= 0: continue

            dev = (b['close'] - v) / atr
            if abs(dev) < threshold: continue

            direction = 'sell' if dev > 0 else 'buy'
            entry     = b['close']
            sl        = (entry+1.5*atr) if direction=='sell' else (entry-1.5*atr)
            if abs(entry-sl) <= 0: continue

            # Exit: return to VWAP or trail
            future_sb = sb.iloc[idx+1:]
            ex, r_val = entry, 0.0
            sl_dist   = abs(entry-sl)
            trail_pts = sl_dist * TRAIL
            sl_cur    = sl; best = entry; be = False

            for jdx, (_, fb) in enumerate(future_sb.iterrows()):
                fv = sb['vwap'].iloc[idx+1+jdx] if idx+1+jdx < len(sb) else np.nan
                if direction == 'buy':
                    if fb['low'] <= sl_cur: r_val=(sl_cur-entry)/sl_dist; break
                    if not pd.isna(fv) and fb['close'] >= fv: r_val=(fb['close']-entry)/sl_dist; break
                    if fb['high']>best: best=fb['high']
                    if not be and best>=entry+sl_dist: be=True; sl_cur=entry
                    if be:
                        ns=best-trail_pts
                        if ns>sl_cur: sl_cur=ns
                else:
                    if fb['high'] >= sl_cur: r_val=(entry-sl_cur)/sl_dist; break
                    if not pd.isna(fv) and fb['close'] <= fv: r_val=(entry-fb['close'])/sl_dist; break
                    if fb['low']<best: best=fb['low']
                    if not be and best<=entry-sl_dist: be=True; sl_cur=entry
                    if be:
                        ns=best+trail_pts
                        if ns<sl_cur: sl_cur=ns
            else:
                last = future_sb.iloc[-1]['close'] if len(future_sb) else entry
                r_val = ((last-entry) if direction=='buy' else (entry-last)) / sl_dist

            trades.append({'r':r_val,'date':day,'month':day.month})
            fired_today = True

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 7. PAIRS MEAN REVERSION — NAS100 vs SP500
# Stat arb / relative value. Calculate rolling Z-score of the NAS100/SP500
# price ratio. When NAS100 is significantly above its historical ratio
# (z > 1.5) → short NAS100 (expect reversion). And vice versa.
# ══════════════════════════════════════════════════════════════════════════════

def run_pairs():
    nq = get_h1("NQ=F")
    es = get_h1("ES=F")
    if nq is None or es is None: return []

    merged = pd.DataFrame({'nq':nq['close'],'es':es['close']}).dropna()
    merged['ratio'] = np.log(merged['nq'] / merged['es'])
    merged['z']     = (merged['ratio'] - merged['ratio'].rolling(40).mean()) / \
                       merged['ratio'].rolling(40).std()
    merged['atr']   = nq['atr'].reindex(merged.index).ffill()

    trades = []; fired = set()

    for i in range(42, len(merged)):
        bar = merged.iloc[i]
        if bar.name.dayofweek >= 5: continue
        h = bar.name.hour
        if not (14 <= h < 20): continue

        date_key = bar.name.date()
        if date_key in fired: continue
        if pd.isna(bar['z']): continue

        # Only trade extreme Z-scores
        if abs(bar['z']) < 1.5: continue

        # NAS100 is expensive relative to SP500 → short NAS100
        # NAS100 is cheap → long NAS100
        direction = 'sell' if bar['z'] > 0 else 'buy'
        entry = merged['nq'].iloc[i]
        atr   = bar['atr']
        if atr <= 0: continue
        sl = (entry+1.5*atr) if direction=='sell' else (entry-1.5*atr)

        day = pd.Timestamp(bar.name.date(), tz='UTC')
        eb  = nq[(nq.index > bar.name) &
                 (nq.index <= day+pd.Timedelta(hours=20))]
        r = sim(eb, direction, entry, sl, max_bars=8)
        trades.append({'r':r,'date':day,'month':bar.name.month})
        fired.add(date_key)

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# 8. LIQUIDITY SWEEP REVERSAL
# Inverse of PDH/PDL. Price briefly exceeds yesterday's high/low (grabbing
# retail stop losses), then CLOSES BACK inside → enter OPPOSITE direction.
# The stop hunt is over, real move begins the other way.
# ══════════════════════════════════════════════════════════════════════════════

LSR_INSTRUMENTS = [
    ("LSR DAX",    "^GDAXI",   8, 17),
    ("LSR UK100",  "^FTSE",    8, 17),
    ("LSR NAS100", "NQ=F",    14, 21),
    ("LSR SP500",  "ES=F",    14, 21),
    ("LSR NatGas", "NG=F",    14, 21),
    ("LSR EURUSD", "EURUSD=X", 7, 17),
    ("LSR GBPUSD", "GBPUSD=X", 7, 17),
]

def run_lsr(sym, s_start, s_end):
    df = get_h1(sym)
    if df is None: return []
    trades = []; fired = set()
    dates  = sorted(set(df.index.normalize().date))

    for d in dates:
        day  = pd.Timestamp(d, tz='UTC')
        prev = day - pd.Timedelta(days=1)
        if day.dayofweek >= 5: continue

        prev_bars = df[df.index.normalize() == prev.normalize()]
        if len(prev_bars) < 4: continue
        pdh = prev_bars['high'].max()
        pdl = prev_bars['low'].min()
        rng = pdh - pdl

        atr_row = df[df.index < day]
        if len(atr_row) == 0: continue
        atr = atr_row['atr'].iloc[-1]
        if atr <= 0 or rng < 0.3*atr: continue

        sb = df[(df.index >= day+pd.Timedelta(hours=s_start)) &
                (df.index <  day+pd.Timedelta(hours=s_end))]
        if len(sb) < 2: continue

        date_key = day.date()
        if date_key in fired: continue

        for bt, b in sb.iterrows():
            # Bearish sweep: wick above PDH, candle closes below PDH
            if (b['high'] > pdh and b['close'] < pdh
                    and (b['high']-pdh) < 0.6*atr):
                entry='sell'; e=b['close']; sl=b['high']+atr*0.1; et=bt; break
            # Bullish sweep: wick below PDL, candle closes above PDL
            if (b['low'] < pdl and b['close'] > pdl
                    and (pdl-b['low']) < 0.6*atr):
                entry='buy'; e=b['close']; sl=b['low']-atr*0.1; et=bt; break
        else:
            continue

        direction = entry
        entry_p   = e
        if abs(entry_p-sl) <= 0: continue

        eb = df[(df.index > et) & (df.index <= day+pd.Timedelta(hours=s_end))]
        r  = sim(eb, direction, entry_p, sl)
        trades.append({'r':r,'date':day,'month':day.month})
        fired.add(date_key)

    return trades

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "="*82)
    print("  INSTITUTIONAL STRATEGIES — 8 Types | 2yr H1 | Trail 0.2R | £70k")
    print("="*82)
    print(f"\n  {'Strategy':<28} {'Win%':>5}  {'T/mo':>5}  {'Monthly@1%':>10}  "
          f"{'PF':>5}  {'DD@1%':>8}  Verdict")
    print(f"  {'─'*80}")

    print("\n  1. FAIR VALUE GAP (ICT Smart Money)")
    print(f"  {'─'*80}")
    for r in FVG_INSTRUMENTS:
        name=r[0]; show(run_fvg(r[1],r[2],r[3]), name)

    print("\n  2. PREVIOUS WEEK HIGH/LOW")
    print(f"  {'─'*80}")
    for r in PWH_INSTRUMENTS:
        name=r[0]; show(run_pwh(r[1],r[2],r[3]), name)

    print("\n  3. AMD MANIPULATION REVERSAL (ICT)")
    print(f"  {'─'*80}")
    for r in AMD_INSTRUMENTS:
        name=r[0]; show(run_amd(r[1],r[2]), name)

    print("\n  4. DONCHIAN 20-DAY BREAKOUT (Turtle Trading)")
    print(f"  {'─'*80}")
    for r in DONCHIAN_INSTRUMENTS:
        name=r[0]; show(run_donchian(r[1],r[2],r[3]), name)

    print("\n  5. END-OF-MONTH FLOW")
    print(f"  {'─'*80}")
    for r in EOM_INSTRUMENTS:
        name=r[0]; show(run_eom(r[1],r[2],r[3]), name)

    print("\n  6. VWAP DEVIATION FADE")
    print(f"  {'─'*80}")
    for r in VWAP_INSTRUMENTS:
        name=r[0]; show(run_vwap(r[1],r[2],r[3],r[4]), name)

    print("\n  7. PAIRS MEAN REVERSION (NAS100 vs SP500)")
    print(f"  {'─'*80}")
    name="PAIRS NAS/SP5"; show(run_pairs(), name)

    print("\n  8. LIQUIDITY SWEEP REVERSAL")
    print(f"  {'─'*80}")
    for r in LSR_INSTRUMENTS:
        name=r[0]; show(run_lsr(r[1],r[2],r[3]), name)

    # ── Final ranking ─────────────────────────────────────────────────────────
    strong = sorted([r for r in all_results if r['pf']>=1.5], key=lambda x:-x['pf'])
    ok     = sorted([r for r in all_results if 1.2<=r['pf']<1.5], key=lambda x:-x['pf'])

    print(f"\n{'='*82}")
    print("  RANKING — WHAT TO ADD TO THE EA")
    print(f"{'='*82}")
    print(f"\n  ✅ STRONG (PF ≥ 1.5):")
    for r in strong:
        print(f"     {r['name']:<28} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['mo']:,.0f}/mo @1%")
    print(f"\n  ⚠️  MARGINAL (PF 1.2–1.5):")
    for r in ok:
        print(f"     {r['name']:<28} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['mo']:,.0f}/mo @1%")
    if strong:
        print(f"\n  Combined strong @0.5% each: £{sum(r['mo'] for r in strong)//2:,.0f}/mo")
    print()
