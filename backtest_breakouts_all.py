"""
backtest_breakouts_all.py — All breakout strategies across all instruments

Tests 4 types of breakout across 25+ instrument/session combinations:

  A. London Breakout (07:00-10:00 UTC)
     Mark Asian range overnight, trade explosion at London open
     Pairs: EURUSD, GBPUSD, GBPJPY, EURJPY, USDJPY, AUDJPY, EURGBP, EURAUD

  B. Asian Session Breakout (03:00-07:00 UTC) — NEW
     Mark early Tokyo range, trade break as Asia gets going
     Pairs: USDJPY, GBPJPY, AUDJPY, AUDUSD, NZDUSD

  C. European Open ORB (09:00-12:00 UTC)
     First H1 bar at 08:00 UTC forms range, trade break
     Instruments: DAX, UK100, CAC40, Gold

  D. US Open ORB (14:00-16:00 UTC)
     Pre-market 13:00 H1 bar, trade break at NY open
     Instruments: NAS100, US30, SP500, Oil, NatGas, Gold

Run: python backtest_breakouts_all.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT  = 70000
RISK_PCT = 0.005
TRAIL    = 0.5

# ── Strategy definitions ───────────────────────────────────────────────────────
# (name, yf_symbol, pip_or_none, min_range, max_range, asian_start, asian_end,
#  entry_start, entry_end, exit_hour)

STRATEGIES = [
    # A. LONDON BREAKOUT — Asian range 22:00-07:00, entry 07:00-10:00
    ("LB EURUSD",  "EURUSD=X", 0.0001, 10,  100,  22, 7,  7,  10, 13),
    ("LB GBPUSD",  "GBPUSD=X", 0.0001, 10,  100,  22, 7,  7,  10, 13),
    ("LB GBPJPY",  "GBPJPY=X", 0.01,   30,  200,  22, 7,  7,  10, 13),
    ("LB EURJPY",  "EURJPY=X", 0.01,   20,  150,  22, 7,  7,  10, 13),
    ("LB USDJPY",  "USDJPY=X", 0.01,   15,  100,  22, 7,  7,  10, 13),
    ("LB AUDJPY",  "AUDJPY=X", 0.01,   15,  100,  22, 7,  7,  10, 13),
    ("LB CADJPY",  "CADJPY=X", 0.01,   15,  100,  22, 7,  7,  10, 13),
    ("LB EURGBP",  "EURGBP=X", 0.0001, 8,   60,   22, 7,  7,  10, 13),
    ("LB EURAUD",  "EURAUD=X", 0.0001, 15,  120,  22, 7,  7,  10, 13),

    # B. ASIAN BREAKOUT — early Tokyo range 21:00-03:00, entry 03:00-07:00
    ("AS USDJPY",  "USDJPY=X", 0.01,   10,  80,   21, 3,  3,  7,  9),
    ("AS GBPJPY",  "GBPJPY=X", 0.01,   20,  150,  21, 3,  3,  7,  9),
    ("AS AUDJPY",  "AUDJPY=X", 0.01,   10,  80,   21, 3,  3,  7,  9),
    ("AS AUDUSD",  "AUDUSD=X", 0.0001, 8,   60,   21, 3,  3,  7,  9),
    ("AS NZDUSD",  "NZDUSD=X", 0.0001, 8,   60,   21, 3,  3,  7,  9),
    ("AS NZDJPY",  "NZDJPY=X", 0.01,   10,  80,   21, 3,  3,  7,  9),

    # C. EUROPEAN OPEN ORB — 08:00 H1 bar, entry 09:00-12:00
    ("EU DAX",     "^GDAXI",   None,   30,  300,  8,  9,  9,  12, 17),
    ("EU UK100",   "^FTSE",    None,   20,  200,  8,  9,  9,  12, 17),
    ("EU CAC40",   "^FCHI",    None,   20,  200,  8,  9,  9,  12, 17),
    ("EU Gold",    "GC=F",     None,   5,   80,   8,  9,  9,  12, 17),
    ("EU EURCHF",  "EURCHF=X", 0.0001, 5,   50,   8,  9,  9,  12, 17),

    # D. US OPEN ORB — 13:00 H1 bar, entry 14:00-16:00
    ("US NAS100",  "NQ=F",     None,   50,  1500, 13, 14, 14, 16, 20),
    ("US US30",    "YM=F",     None,   50,  800,  13, 14, 14, 16, 20),
    ("US SP500",   "ES=F",     None,   10,  200,  13, 14, 14, 16, 20),
    ("US Oil",     "CL=F",     None,   0.3, 8,    13, 14, 14, 16, 20),
    ("US NatGas",  "NG=F",     None,   0.03,1.0,  13, 14, 14, 16, 20),
    ("US Gold",    "GC=F",     None,   5,   100,  13, 14, 14, 16, 20),
]

# ── Data ───────────────────────────────────────────────────────────────────────

_cache = {}
def get_h1(symbol):
    if symbol not in _cache:
        try:
            df = yf.download(symbol, interval="1h", period="730d",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [c.lower() for c in df.columns]
            df = df.dropna()
            if df.index.tz is None:
                df.index = df.index.tz_localize('UTC')
            else:
                df.index = df.index.tz_convert('UTC')
            _cache[symbol] = df if len(df) > 100 else None
        except:
            _cache[symbol] = None
    return _cache[symbol]

# ── Trade simulation ───────────────────────────────────────────────────────────

def sim(df, entry_time, direction, entry, sl, exit_hour):
    sl_dist = abs(entry - sl)
    if sl_dist <= 0: return 0
    trail   = sl_dist * TRAIL
    day     = entry_time.normalize()
    bars    = df[(df.index > entry_time) &
                 (df.index <= day + pd.Timedelta(hours=exit_hour))]

    sl_cur = sl; best = entry; be = False
    ex = bars.iloc[-1]['close'] if len(bars) else entry

    for _, b in bars.iterrows():
        if direction == 'buy':
            if b['low']  <= sl_cur: ex = sl_cur; break
            if b['high'] > best:    best = b['high']
            if not be and best >= entry + sl_dist: be = True; sl_cur = entry
            if be:
                ns = best - trail
                if ns > sl_cur: sl_cur = ns
        else:
            if b['high'] >= sl_cur: ex = sl_cur; break
            if b['low']  < best:    best = b['low']
            if not be and best <= entry - sl_dist: be = True; sl_cur = entry
            if be:
                ns = best + trail
                if ns < sl_cur: sl_cur = ns

    return ((ex-entry) if direction=='buy' else (entry-ex)) / sl_dist

# ── Run single strategy ────────────────────────────────────────────────────────

def run(name, symbol, pip, min_rng, max_rng,
        range_start, range_end, entry_start, entry_end, exit_hour):

    df = get_h1(symbol)
    if df is None: return None

    trades = []
    risk   = ACCOUNT * RISK_PCT
    dates  = sorted(set(df.index.normalize().date))

    for date in dates:
        day  = pd.Timestamp(date, tz='UTC')
        prev = day - pd.Timedelta(days=1)

        # Build range window (handles overnight: e.g. 22:00 prev → 07:00 today)
        if range_start > range_end:
            # Overnight range (e.g. 22:00-07:00)
            range_bars = df[
                (df.index >= prev + pd.Timedelta(hours=range_start)) &
                (df.index <  day  + pd.Timedelta(hours=range_end))
            ]
        else:
            # Same-day range (e.g. 08:00-09:00 ORB)
            rng_s = day + pd.Timedelta(hours=range_start)
            rng_e = day + pd.Timedelta(hours=range_end)
            rows  = df[df.index == rng_s]
            if len(rows) == 0: continue
            range_bars = rows   # single bar = the ORB bar

        if len(range_bars) == 0: continue

        r_hi  = range_bars['high'].max()
        r_lo  = range_bars['low'].min()
        r_rng = r_hi - r_lo
        r_meas= r_rng / pip if pip else r_rng

        if not (min_rng <= r_meas <= max_rng): continue

        # Entry window
        entry_bars = df[
            (df.index >= day + pd.Timedelta(hours=entry_start)) &
            (df.index <  day + pd.Timedelta(hours=entry_end))
        ]
        if len(entry_bars) == 0: continue

        direction = entry_price = entry_time = None
        for bt, b in entry_bars.iterrows():
            if b['high'] > r_hi:
                direction, entry_price, entry_time = 'buy',  r_hi, bt; break
            if b['low']  < r_lo:
                direction, entry_price, entry_time = 'sell', r_lo, bt; break

        if direction is None: continue

        sl  = (r_lo - r_rng*0.15) if direction=='buy' else (r_hi + r_rng*0.15)
        pnl_r   = sim(df, entry_time, direction, entry_price, sl, exit_hour)
        pnl_gbp = risk * pnl_r
        trades.append({'date':day,'pnl_r':round(pnl_r,2),'pnl_gbp':round(pnl_gbp,2)})

    if len(trades) < 10: return None

    df_t    = pd.DataFrame(trades)
    wins    = df_t[df_t['pnl_gbp'] >  5]
    losses  = df_t[df_t['pnl_gbp'] < -5]
    n       = len(df_t)
    wr      = len(wins)/n*100
    gp      = wins['pnl_gbp'].sum()         if len(wins)   > 0 else 0
    gl      = abs(losses['pnl_gbp'].sum())  if len(losses) > 0 else 1
    pf      = gp/gl
    total   = df_t['pnl_gbp'].sum()
    df_t['cum']  = df_t['pnl_gbp'].cumsum()
    df_t['peak'] = df_t['cum'].cummax()
    max_dd  = (df_t['cum']-df_t['peak']).min()
    days    = max((df_t['date'].iloc[-1]-df_t['date'].iloc[0]).days, 1)
    monthly = total/days*30
    tpm     = n/(days/30)
    verdict = "✅ STRONG" if pf>=1.5 else ("⚠️  OK" if pf>=1.2 else "❌")

    print(f"  {name:<14} {wr:>5.1f}%  {tpm:>5.1f}/mo  "
          f"£{monthly*2:>7,.0f}@1%  PF:{pf:>5.2f}  DD:£{max_dd*2:>7,.0f}  {verdict}")

    return {'name':name,'tpm':tpm,'wr':wr,'pf':pf,'monthly':monthly,'max_dd':max_dd}

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*80)
    print("  ALL BREAKOUT STRATEGIES — 26 instrument/session combinations")
    print("  London Breakout | Asian Breakout | EU ORB | US ORB")
    print("  2 years H1 | Trail=0.5R | 0.5% risk")
    print("="*80)
    print(f"\n  {'Strategy':<14} {'Win%':>5}  {'T/mo':>6}  {'Monthly@1%':>10}  "
          f"{'PF':>6}  {'DD@1%':>9}  Verdict")
    print(f"  {'─'*76}")

    sections = [
        ("A. LONDON BREAKOUT (07:00-10:00 UTC)",   "LB"),
        ("B. ASIAN BREAKOUT (03:00-07:00 UTC)",    "AS"),
        ("C. EUROPEAN OPEN ORB (09:00-12:00 UTC)", "EU"),
        ("D. US OPEN ORB (14:00-16:00 UTC)",       "US"),
    ]

    all_results = []

    for section_name, prefix in sections:
        print(f"\n  {section_name}")
        print(f"  {'─'*76}")
        for args in STRATEGIES:
            if args[0].startswith(prefix):
                r = run(*args)
                if r: all_results.append(r)

    # Final ranking
    all_results.sort(key=lambda x: x['pf'], reverse=True)
    strong = [r for r in all_results if r['pf'] >= 1.5]
    ok     = [r for r in all_results if 1.2 <= r['pf'] < 1.5]

    print(f"\n{'='*80}")
    print(f"  FULL RANKING — BEST TO WORST")
    print(f"{'='*80}\n")
    print(f"  ✅ STRONG (PF >= 1.5):")
    for r in strong:
        print(f"     {r['name']:<14} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    print(f"\n  ⚠️  MARGINAL (PF 1.2-1.5):")
    for r in ok:
        print(f"     {r['name']:<14} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    if strong:
        print(f"\n  COMBINED STRONG (at current 0.5% risk each):")
        print(f"  Monthly: £{sum(r['monthly'] for r in strong)*2:,.0f}/mo @1%")
        print(f"  Trades:  ~{sum(r['tpm'] for r in strong):.0f}/month")
    print()
