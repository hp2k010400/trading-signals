"""
backtest_h4_all.py — H4 EMA trend following across 41 instruments
Same proven strategy as backtest_multi.py (DAX PF 2.61) but tested
across every major instrument available on FTMO.

Instruments: 21 forex pairs, 10 indices, 7 commodities, 2 crypto
Strategy: EMA 10/20 cross + ADX>25 + ATR SL/TP on H4 timeframe
Goal: find all instruments with genuine H4 trending edge

Run: python backtest_h4_all.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT      = 70000
RISK_PCT     = 0.005
EMA_FAST     = 10
EMA_SLOW     = 20
ADX_MIN      = 25
ADX_PERIOD   = 14
ATR_SL_MULT  = 1.5
ATR_TP_MULT  = 3.0

# ── 41 instruments ─────────────────────────────────────────────────────────────
# (name, yfinance symbol, session_start UTC, session_end UTC)
INSTRUMENTS = [
    # Forex Majors
    ("EURUSD",   "EURUSD=X",   8,  17),
    ("GBPUSD",   "GBPUSD=X",   8,  17),
    ("USDJPY",   "USDJPY=X",   0,  21),
    ("USDCHF",   "USDCHF=X",   8,  17),
    ("AUDUSD",   "AUDUSD=X",   0,  17),
    ("USDCAD",   "USDCAD=X",   14, 21),
    ("NZDUSD",   "NZDUSD=X",   0,  17),

    # Forex Minors
    ("EURGBP",   "EURGBP=X",   8,  17),
    ("EURJPY",   "EURJPY=X",   0,  21),
    ("GBPJPY",   "GBPJPY=X",   0,  21),
    ("EURCHF",   "EURCHF=X",   8,  17),
    ("EURAUD",   "EURAUD=X",   0,  17),
    ("EURCAD",   "EURCAD=X",   8,  21),
    ("GBPCHF",   "GBPCHF=X",   8,  17),
    ("GBPAUD",   "GBPAUD=X",   0,  17),
    ("AUDCAD",   "AUDCAD=X",   0,  21),
    ("AUDJPY",   "AUDJPY=X",   0,  21),
    ("CADJPY",   "CADJPY=X",   0,  21),
    ("CHFJPY",   "CHFJPY=X",   0,  21),
    ("NZDJPY",   "NZDJPY=X",   0,  21),
    ("NZDCAD",   "NZDCAD=X",   0,  21),

    # European Indices
    ("DAX",      "^GDAXI",     8,  16),
    ("UK100",    "^FTSE",      8,  16),
    ("CAC40",    "^FCHI",      8,  16),
    ("STOXX50",  "^STOXX50E",  8,  16),

    # US Indices
    ("SP500",    "ES=F",       14, 21),
    ("NAS100",   "NQ=F",       14, 21),
    ("US30",     "YM=F",       14, 21),
    ("Russell",  "RTY=F",      14, 21),

    # Asian Indices
    ("Nikkei",   "^N225",      0,  6),
    ("HangSeng", "^HSI",       1,  8),
    ("AUS200",   "^AXJO",      23, 6),

    # Commodities
    ("Gold",     "GC=F",       8,  20),
    ("Silver",   "SI=F",       8,  20),
    ("Oil",      "CL=F",       14, 21),
    ("Brent",    "BZ=F",       8,  20),
    ("NatGas",   "NG=F",       14, 21),
    ("Copper",   "HG=F",       8,  20),
    ("Platinum", "PL=F",       8,  20),

    # Crypto (24/7)
    ("Bitcoin",  "BTC-USD",    0,  24),
    ("Ethereum", "ETH-USD",    0,  24),
]

# ── Indicators ─────────────────────────────────────────────────────────────────

def fetch_h4(symbol):
    try:
        df = yf.download(symbol, interval="1h", period="730d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if len(df) < 200: return None
        df = df.resample('4h').agg({'open':'first','high':'max',
                                    'low':'min','close':'last',
                                    'volume':'sum'}).dropna()
        return df
    except:
        return None

def add_indicators(df):
    df = df.copy()
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    hi, lo, cl = df['high'], df['low'], df['close']
    tr   = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    df['atr'] = tr.ewm(com=ADX_PERIOD-1, adjust=False).mean()
    dmp  = ((hi-hi.shift())>(lo.shift()-lo)).astype(float)*(hi-hi.shift()).clip(lower=0)
    dmm  = ((lo.shift()-lo)>(hi-hi.shift())).astype(float)*(lo.shift()-lo).clip(lower=0)
    atr_s = tr.ewm(com=ADX_PERIOD-1, adjust=False).mean()
    dip  = 100*dmp.ewm(com=ADX_PERIOD-1,adjust=False).mean()/atr_s
    dim  = 100*dmm.ewm(com=ADX_PERIOD-1,adjust=False).mean()/atr_s
    dx   = (100*(dip-dim).abs()/(dip+dim).replace(0,1)).fillna(0)
    df['adx'] = dx.ewm(com=ADX_PERIOD-1, adjust=False).mean()
    return df

def get_signal(df, i):
    if i < ADX_PERIOD+5: return None
    bar, prev = df.iloc[i], df.iloc[i-1]
    if bar['adx'] < ADX_MIN: return None
    bull = bar['ema_fast']>bar['ema_slow'] and prev['ema_fast']<=prev['ema_slow']
    bear = bar['ema_fast']<bar['ema_slow'] and prev['ema_fast']>=prev['ema_slow']
    if bull: return 'buy'
    if bear: return 'sell'
    return None

def sim_trade(df, ei, entry, sl, tp, direction, atr_val):
    sl_cur  = sl
    be_done = False
    be_lvl  = entry+abs(entry-sl) if direction=='buy' else entry-abs(entry-sl)
    for j in range(ei+1, min(ei+120, len(df))):
        bar = df.iloc[j]
        if direction == 'buy':
            if bar['low']  <= sl_cur: return sl_cur,'sl',j-ei
            if bar['high'] >= tp:     return tp,'tp',j-ei
            if not be_done and bar['high']>=be_lvl: be_done=True; sl_cur=entry
            if be_done:
                ns=bar['high']-atr_val
                if ns>sl_cur: sl_cur=ns
        else:
            if bar['high'] >= sl_cur: return sl_cur,'sl',j-ei
            if bar['low']  <= tp:     return tp,'tp',j-ei
            if not be_done and bar['low']<=be_lvl: be_done=True; sl_cur=entry
            if be_done:
                ns=bar['low']+atr_val
                if ns<sl_cur: sl_cur=ns
    last = df.iloc[min(ei+119,len(df)-1)]
    return last['close'],'timeout',min(119,len(df)-ei-1)

# ── Run single instrument ──────────────────────────────────────────────────────

def run(name, symbol, sess_start, sess_end):
    df = fetch_h4(symbol)
    if df is None: return None

    df = add_indicators(df)
    trades = []
    last_i = -2
    risk   = ACCOUNT * RISK_PCT

    for i in range(50, len(df)-1):
        bar  = df.iloc[i]
        h    = bar.name.hour
        in_s = (sess_start <= sess_end and sess_start <= h < sess_end) or \
               (sess_start >  sess_end and (h >= sess_start or h < sess_end))
        if not in_s:         continue
        if i-last_i < 2:     continue
        if trades and trades[-1].get('exit_i',0) > i: continue

        direction = get_signal(df, i)
        if direction is None: continue

        entry   = bar['close']
        atr_val = bar['atr']
        if atr_val <= 0: continue

        sl  = entry - ATR_SL_MULT*atr_val if direction=='buy' else entry + ATR_SL_MULT*atr_val
        tp  = entry + ATR_TP_MULT*atr_val if direction=='buy' else entry - ATR_TP_MULT*atr_val

        ex_price, reason, bars = sim_trade(df, i, entry, sl, tp, direction, atr_val)
        pnl_r   = ((ex_price-entry) if direction=='buy' else (entry-ex_price)) / (ATR_SL_MULT*atr_val)
        pnl_gbp = risk * pnl_r

        trades.append({'date':bar.name,'reason':reason,
                       'pnl_r':round(pnl_r,2),'pnl_gbp':round(pnl_gbp,2),
                       'exit_i':i+bars})
        last_i = i

    if not trades: return None

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
    print(f"  {name:<12} {wr:>5.1f}%  {tpm:>4.1f}/mo  "
          f"£{monthly*2:>7,.0f}@1%  PF:{pf:>5.2f}  DD:£{max_dd*2:>7,.0f}  {verdict}")

    return {'name':name,'trades':n,'tpm':tpm,'wr':wr,
            'total':total,'monthly':monthly,'pf':pf,'max_dd':max_dd}

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*76)
    print("  H4 EMA TREND FOLLOWING — 41 INSTRUMENTS")
    print("  EMA 10/20 cross + ADX>25 | 2 years | 0.5% risk per trade")
    print("="*76)
    print(f"\n  {'Instrument':<12} {'Win%':>5}  {'T/mo':>6}  {'Monthly@1%':>10}  "
          f"{'PF':>6}  {'DD@1%':>8}  Verdict")
    print(f"  {'─'*72}")

    results = []
    for name, symbol, s, e in INSTRUMENTS:
        r = run(name, symbol, s, e)
        if r: results.append(r)

    results.sort(key=lambda x: x['pf'], reverse=True)
    strong = [r for r in results if r['pf'] >= 1.5]
    ok     = [r for r in results if 1.2 <= r['pf'] < 1.5]

    print(f"\n{'='*76}")
    print(f"  RANKED — STRONG EDGE (PF >= 1.5)")
    print(f"{'='*76}")
    for r in strong:
        print(f"  {r['name']:<12} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    print(f"\n  MARGINAL (PF 1.2-1.5):")
    for r in ok:
        print(f"  {r['name']:<12} PF {r['pf']:.2f} | {r['wr']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    if strong:
        combined_monthly = sum(r['monthly']*2 for r in strong)
        combined_tpm     = sum(r['tpm'] for r in strong)
        print(f"\n  COMBINED (strong only, 1% risk each):")
        print(f"  Instruments:   {len(strong)}")
        print(f"  Trades/month:  ~{combined_tpm:.0f}")
        print(f"  Monthly est:   £{combined_monthly:,.0f}")
        print(f"\n  Note: some instruments will be correlated.")
        print(f"  Use 0.5-0.75% risk on correlated pairs (e.g. EURUSD+GBPUSD)")

    print(f"\n  FTMO: daily DD £3,500 | total DD £7,000\n")
