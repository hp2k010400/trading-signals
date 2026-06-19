"""
backtest_multi.py — H4 EMA Trend Following across ALL major instruments
Strategy: EMA 10/20 cross + ADX > 25 + candle confirmation + ATR SL/TP
Ranks instruments by Profit Factor to find the best ones to trade live.

Run: python backtest_multi.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

ACCOUNT      = 70000
RISK_PCT     = 0.005   # 0.5% per trade
EMA_FAST     = 10
EMA_SLOW     = 20
ADX_MIN      = 25
ADX_PERIOD   = 14
ATR_SL_MULT  = 1.5
ATR_TP_MULT  = 3.0    # 2R

# ── All instruments to test ────────────────────────────────────────────────────
# (name, yfinance symbol, session_start UTC, session_end UTC)

INSTRUMENTS = [
    # European indices
    ("DAX",     "^GDAXI",   8,  16),
    ("UK100",   "^FTSE",    8,  16),
    ("CAC40",   "^FCHI",    8,  16),

    # US indices
    ("SP500",   "ES=F",     14, 21),
    ("NAS100",  "NQ=F",     14, 21),
    ("US30",    "YM=F",     14, 21),

    # Commodities
    ("Gold",    "GC=F",     8,  20),
    ("Silver",  "SI=F",     8,  20),
    ("Oil",     "CL=F",     14, 21),

    # Forex majors
    ("EURUSD",  "EURUSD=X", 8,  17),
    ("GBPUSD",  "GBPUSD=X", 8,  17),
    ("USDJPY",  "USDJPY=X", 0,  21),
    ("USDCAD",  "USDCAD=X", 14, 21),
    ("AUDUSD",  "AUDUSD=X", 0,  17),

    # Asian indices
    ("Nikkei",  "^N225",    0,  6),
    ("AUS200",  "^AXJO",    0,  6),
]

# ── Data & indicators ──────────────────────────────────────────────────────────

def fetch_h4(symbol):
    try:
        df = yf.download(symbol, interval="1h", period="730d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.lower() for c in df.columns]
        df = df.dropna()
        if len(df) < 200:
            return None
        # Resample to H4
        df = df.resample('4h').agg({'open':'first','high':'max',
                                     'low':'min','close':'last','volume':'sum'}).dropna()
        return df
    except:
        return None

def add_indicators(df):
    df = df.copy()
    df['ema_fast'] = df['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df['ema_slow'] = df['close'].ewm(span=EMA_SLOW, adjust=False).mean()

    hi, lo, cl = df['high'], df['low'], df['close']
    tr  = pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    df['atr'] = tr.ewm(com=ADX_PERIOD-1, adjust=False).mean()

    dmp = ((hi-hi.shift())>(lo.shift()-lo)).astype(float)*(hi-hi.shift()).clip(lower=0)
    dmm = ((lo.shift()-lo)>(hi-hi.shift())).astype(float)*(lo.shift()-lo).clip(lower=0)
    atr_s = tr.ewm(com=ADX_PERIOD-1, adjust=False).mean()
    dip = 100*dmp.ewm(com=ADX_PERIOD-1, adjust=False).mean()/atr_s
    dim = 100*dmm.ewm(com=ADX_PERIOD-1, adjust=False).mean()/atr_s
    dx  = (100*(dip-dim).abs()/(dip+dim).replace(0,1)).fillna(0)
    df['adx'] = dx.ewm(com=ADX_PERIOD-1, adjust=False).mean()

    o,h,l,c = df['open'],df['high'],df['low'],df['close']
    r = h-l
    body = (c-o).abs()
    df['bull_engulf'] = (c.shift()<o.shift())&(c>o)&(o<c.shift())&(c>o.shift())
    df['bear_engulf'] = (c.shift()>o.shift())&(c<o)&(o>c.shift())&(c<o.shift())
    lower_w = pd.Series([min(df['open'].iloc[i],df['close'].iloc[i])-df['low'].iloc[i]
                         for i in range(len(df))], index=df.index)
    upper_w = pd.Series([df['high'].iloc[i]-max(df['open'].iloc[i],df['close'].iloc[i])
                         for i in range(len(df))], index=df.index)
    df['bull_pin'] = (lower_w>=r*0.6)&(body<=r*0.3)&(r>0)
    df['bear_pin'] = (upper_w>=r*0.6)&(body<=r*0.3)&(r>0)
    return df

def get_signal(df, i):
    if i < ADX_PERIOD+5: return None
    bar,prev = df.iloc[i],df.iloc[i-1]
    if bar['adx'] < ADX_MIN: return None
    bull_cross = bar['ema_fast']>bar['ema_slow'] and prev['ema_fast']<=prev['ema_slow']
    bear_cross = bar['ema_fast']<bar['ema_slow'] and prev['ema_fast']>=prev['ema_slow']
    bull_cont  = bar['ema_fast']>bar['ema_slow'] and bar['adx']>ADX_MIN+5 and (bar['bull_engulf'] or bar['bull_pin'])
    bear_cont  = bar['ema_fast']<bar['ema_slow'] and bar['adx']>ADX_MIN+5 and (bar['bear_engulf'] or bar['bear_pin'])
    if bull_cross or bull_cont: return 'buy'
    if bear_cross or bear_cont: return 'sell'
    return None

def sim_trade(df, ei, entry, sl, tp, direction, atr_val):
    sl_cur  = sl
    be_done = False
    be_lvl  = entry+abs(entry-sl) if direction=='buy' else entry-abs(entry-sl)
    for j in range(ei+1, min(ei+120, len(df))):
        bar = df.iloc[j]
        if direction=='buy':
            if bar['low']  <=sl_cur: return sl_cur,'sl', j-ei
            if bar['high'] >=tp:     return tp,    'tp', j-ei
            if not be_done and bar['high']>=be_lvl: be_done=True; sl_cur=entry
            if be_done:
                ns=bar['high']-atr_val
                if ns>sl_cur: sl_cur=ns
        else:
            if bar['high'] >=sl_cur: return sl_cur,'sl', j-ei
            if bar['low']  <=tp:     return tp,    'tp', j-ei
            if not be_done and bar['low']<=be_lvl: be_done=True; sl_cur=entry
            if be_done:
                ns=bar['low']+atr_val
                if ns<sl_cur: sl_cur=ns
    last=df.iloc[min(ei+119,len(df)-1)]
    return last['close'],'timeout',min(119,len(df)-ei-1)

# ── Run single instrument ──────────────────────────────────────────────────────

def run_instrument(name, symbol, sess_start, sess_end):
    df = fetch_h4(symbol)
    if df is None:
        print(f"  {name:<10} — no data")
        return None

    df = add_indicators(df)
    trades=[]
    last_i=-2
    risk=ACCOUNT*RISK_PCT

    for i in range(50,len(df)-1):
        bar=df.iloc[i]
        h=bar.name.hour
        # Handle overnight sessions (e.g. Nikkei 0-6 UTC)
        in_session = (sess_start <= sess_end and sess_start <= h < sess_end) or \
                     (sess_start > sess_end and (h >= sess_start or h < sess_end))
        if not in_session: continue
        if i-last_i<2: continue
        if trades and trades[-1].get('exit_i',0)>i: continue

        direction=get_signal(df,i)
        if direction is None: continue

        entry=bar['close']
        atr_val=bar['atr']
        if atr_val<=0: continue

        sl_dist=ATR_SL_MULT*atr_val
        tp_dist=ATR_TP_MULT*atr_val
        sl=entry-sl_dist if direction=='buy' else entry+sl_dist
        tp=entry+tp_dist if direction=='buy' else entry-tp_dist

        ex_price,reason,bars=sim_trade(df,i,entry,sl,tp,direction,atr_val)
        pnl_r  =(((ex_price-entry) if direction=='buy' else (entry-ex_price))/sl_dist)
        pnl_gbp=risk*pnl_r

        trades.append({'date':bar.name,'reason':reason,
                        'pnl_r':round(pnl_r,2),'pnl_gbp':round(pnl_gbp,2),
                        'exit_i':i+bars})
        last_i=i

    if not trades:
        print(f"  {name:<10} — 0 trades")
        return None

    df_t=pd.DataFrame(trades)
    wins  =df_t[df_t['pnl_gbp']>5]
    losses=df_t[df_t['pnl_gbp']<-5]
    n=len(df_t)
    win_rate=len(wins)/n*100
    gp=wins['pnl_gbp'].sum() if len(wins)>0 else 0
    gl=abs(losses['pnl_gbp'].sum()) if len(losses)>0 else 1
    pf=gp/gl
    total=df_t['pnl_gbp'].sum()
    df_t['cum']=df_t['pnl_gbp'].cumsum()
    df_t['peak']=df_t['cum'].cummax()
    max_dd=(df_t['cum']-df_t['peak']).min()
    days=max((df_t['date'].iloc[-1]-df_t['date'].iloc[0]).days,1)
    monthly=total/days*30
    tpm=n/(days/30)
    avg_r=df_t['pnl_r'].mean()

    verdict = "✅ STRONG" if pf>=1.5 else ("⚠️  OK" if pf>=1.2 else "❌ WEAK")
    print(f"  {name:<10} {win_rate:>5.1f}%  {tpm:>4.1f}/mo  "
          f"£{monthly*2:>7,.0f}@1%  PF:{pf:>5.2f}  DD:{max_dd*2:>7,.0f}  {verdict}")

    return {'name':name,'trades':n,'tpm':tpm,'win_rate':win_rate,
            'avg_r':avg_r,'total':total,'monthly':monthly,
            'pf':pf,'max_dd':max_dd}

# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "="*72)
    print("  H4 EMA TREND FOLLOWING — ALL INSTRUMENTS")
    print("  Strategy: EMA 10/20 + ADX>25 + candle | 2 years | 0.5% risk")
    print("="*72)
    print(f"\n  {'Instrument':<10} {'Win%':>5}  {'T/mo':>6}  {'Monthly@1%':>11}  {'PF':>7}  {'DD@1%':>8}  Verdict")
    print(f"  {'─'*68}")

    results = []
    for name, symbol, s_start, s_end in INSTRUMENTS:
        r = run_instrument(name, symbol, s_start, s_end)
        if r: results.append(r)

    # Sort by PF
    results.sort(key=lambda x: x['pf'], reverse=True)

    strong = [r for r in results if r['pf'] >= 1.5]
    ok     = [r for r in results if 1.2 <= r['pf'] < 1.5]

    print(f"\n{'='*72}")
    print(f"  RANKED RESULTS")
    print(f"{'='*72}")
    print(f"\n  ✅ STRONG EDGE (PF >= 1.5) — trade these:")
    for r in strong:
        print(f"     {r['name']:<10} PF {r['pf']:.2f} | {r['win_rate']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    print(f"\n  ⚠️  MARGINAL (PF 1.2-1.5) — consider with caution:")
    for r in ok:
        print(f"     {r['name']:<10} PF {r['pf']:.2f} | {r['win_rate']:.1f}% win | "
              f"{r['tpm']:.1f}/mo | £{r['monthly']*2:,.0f}/mo @1%")

    if strong:
        combined_monthly = sum(r['monthly']*2 for r in strong)
        combined_tpm     = sum(r['tpm'] for r in strong)
        combined_dd      = sum(r['max_dd']*2 for r in strong)
        print(f"\n  COMBINED (strong only at 1% risk each):")
        print(f"  Monthly est:     £{combined_monthly:,.0f}/month")
        print(f"  Trades/month:    ~{combined_tpm:.0f}")
        print(f"  Note: instruments are correlated — actual combined DD")
        print(f"  may be lower than sum of individual DDs")

    print(f"\n  FTMO: daily limit £3,500 | total drawdown limit £7,000")
    print(f"  Recommend: 0.75% risk per trade for safety margin\n")
