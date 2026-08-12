"""
backtest_july_comparison.py

Three-way July 2026 comparison:
  1. OLD  — HasOpenPosition (blocks while a position is open per instrument)
             + wrong USDJPY hours {8,9,13,14,15} — what the live EA was doing
  2. NEW  — v2.07 raw backtest: up to 3/day per instrument, correct USDJPY hours
             no portfolio-level constraints
  3. CAP  — v2.07 + 4% portfolio cap + 4.5% daily stop applied at portfolio level

Run in Codespace: python -u backtest_july_comparison.py
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ---- Params (match live EA exactly) ------------------------------------
BASE_TP    = 4.0
SLIPPAGE   = 0.10
WIN_HOURS  = 3
MAX_BARS   = 480     # 8h time stop
MAX_PD     = 3       # max trades per instrument per day

WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015

RISK_PCT   = 0.5     # % per trade
CAP_PCT    = 4.0     # portfolio cap — (N+1)*0.5 > 4.0 blocks entry
DAILY_STOP = 4.5     # halt day if daily closed loss > 4.5% of balance
START_BAL  = 70000   # £

JULY_START = pd.Timestamp(2026, 7, 1,  tz='UTC')
JULY_END   = pd.Timestamp(2026, 7, 31, tz='UTC')  # covers full month

FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
    # NATGAS disabled — wide FTMO spread inflates losses vs backtest assumption
}
COST = {
    'DAX':0.07,'NAS100':0.06,'SP500':0.06,'US30':0.06,
    'EURUSD':0.08,'GBPUSD':0.08,'USDJPY':0.08,'GOLD':0.08,
}
H1_HOURS_NEW = {
    'DAX':{8,9,10,13,14},'NAS100':{13,14,15,16},'SP500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},
}
# Old: USDJPY used default FX range — missed Asian session entirely
H1_HOURS_OLD = {**H1_HOURS_NEW, 'USDJPY':{8,9,13,14,15}}
H1_SKIP = {
    'DAX':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'USDJPY':frozenset(),'GOLD':frozenset(),
    'NAS100':frozenset({0}),'SP500':frozenset({0}),'US30':frozenset({0}),
}

# ---- Data loading ------------------------------------------------------
_m1 = {}
def load(k):
    fn = FILES[k]
    if not os.path.exists(fn): return False
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna()
    return True

# ---- Signal logic (unchanged from backtest_is_oos.py) ------------------
def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0 or body < full*0.02: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body,full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body,full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def vsim(k, ep, d, entry, sl):
    m1 = _m1[k]; sl_d = abs(entry-sl)
    if sl_d <= 0: return -1.0, MAX_BARS
    end = min(ep+1+MAX_BARS, len(m1))
    hi = m1['high'].values[ep+1:end]; lo = m1['low'].values[ep+1:end]
    if len(hi) == 0: return -1.0, MAX_BARS
    tp = entry+sl_d*BASE_TP if d==1 else entry-sl_d*BASE_TP
    if d==1:
        sl_i = int(np.argmax(lo<=sl)) if np.any(lo<=sl) else len(hi)
        tp_i = int(np.argmax(hi>=tp)) if np.any(hi>=tp) else len(hi)
    else:
        sl_i = int(np.argmax(hi>=sl)) if np.any(hi>=sl) else len(hi)
        tp_i = int(np.argmax(lo<=tp)) if np.any(lo<=tp) else len(hi)
    if tp_i <= sl_i: return BASE_TP, tp_i
    if sl_i < len(hi): return -1.0, sl_i
    close_r = ((m1['close'].values[min(ep+len(hi),len(m1)-1)]-entry)/sl_d if d==1
               else (entry-m1['close'].values[min(ep+len(hi),len(m1)-1)])/sl_d)
    return close_r, len(hi)

# ---- Trade collector ---------------------------------------------------
def collect(k, h1_hours, has_open_pos_mode=False):
    """
    Collect all candidate trades for instrument k in July.
    has_open_pos_mode=True: blocks new entry while a position is open on this instrument
                            (simulates live EA HasOpenPosition() behaviour pre-v2.07)
    Returns list of dicts: instrument, entry_time, exit_time, r_net, hold_bars
    """
    m1 = _m1[k]; mi = m1.index
    skip    = H1_SKIP.get(k, frozenset())
    p_hours = h1_hours.get(k, {8,9,13,14})
    m1w = m1[(m1.index >= JULY_START) & (m1.index < JULY_END)]
    if len(m1w) < 100: return []
    h1 = m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1 = h1[h1['open'] > 0]
    hl = list(h1.index); out = []
    day_count = {}
    blocked_until = JULY_START  # tracks when last position on this instrument closes

    for i in range(1, len(hl)):
        ts = hl[i]
        if ts.dayofweek in skip or ts.dayofweek >= 5: continue
        if ts.hour not in p_hours: continue
        date_k = ts.date()
        if day_count.get(date_k, 0) >= MAX_PD: continue

        bar  = h1.iloc[i]
        prev = h1.iloc[i-1]
        entry_start = ts + pd.Timedelta(hours=1)
        window = m1[(mi >= entry_start) & (mi < entry_start + pd.Timedelta(hours=WIN_HOURS))]
        if len(window) == 0: continue

        taken = False; d = 0; e = 0.0; sl = 0.0

        if k == 'USDJPY':
            pb = pin_bar_dir(float(bar['open']),float(bar['high']),float(bar['low']),float(bar['close']))
            if pb == 0: continue
            pb_h = float(bar['high']); pb_l = float(bar['low'])
            for j in range(len(window)):
                b = window.iloc[j]
                if pb==1  and b['high']>pb_h: d=1;  e=pb_h; sl=pb_l; taken=True; break
                elif pb==-1 and b['low']<pb_l: d=-1; e=pb_l; sl=pb_h; taken=True; break
        else:
            ib_h = float(bar['high']); ib_l = float(bar['low'])
            is_ib = bar['high'] < prev['high'] and bar['low'] > prev['low']
            ib_ok = is_ib and (ib_h-ib_l) > 0 and (ib_h-ib_l)/ib_h >= MIN_RANGE
            if ib_ok:
                for j in range(len(window)):
                    b = window.iloc[j]
                    if b['high']>ib_h:  d=1;  e=ib_h; sl=ib_l; taken=True; break
                    elif b['low']<ib_l: d=-1; e=ib_l; sl=ib_h; taken=True; break
            if not taken:
                pb = pin_bar_dir(float(bar['open']),ib_h,ib_l,float(bar['close']))
                if pb != 0:
                    for j in range(len(window)):
                        b = window.iloc[j]
                        if pb==1  and b['high']>ib_h:  d=1;  e=ib_h; sl=ib_l; taken=True; break
                        elif pb==-1 and b['low']<ib_l: d=-1; e=ib_l; sl=ib_h; taken=True; break

        if not taken: continue
        sl_dist = abs(e-sl)
        if sl_dist <= 0: continue
        ep = mi.searchsorted(window.index[j])
        if ep >= len(m1): continue

        entry_time = window.index[j]

        # HasOpenPosition: skip if previous position on this instrument still open
        if has_open_pos_mode and entry_time < blocked_until:
            continue

        r_gross, hold_bars = vsim(k, ep, d, e, sl)
        exit_time = entry_time + pd.Timedelta(minutes=hold_bars)

        if has_open_pos_mode:
            blocked_until = exit_time

        day_count[date_k] = day_count.get(date_k, 0) + 1
        out.append({
            'instrument': k,
            'entry_time': entry_time,
            'exit_time':  exit_time,
            'r_net':      r_gross - COST[k] - SLIPPAGE,
            'hold_bars':  hold_bars,
        })
    return out


# ---- Portfolio cap + daily stop simulation -----------------------------
def apply_constraints(all_trades):
    """
    Filter trades from all instruments applying:
      - Portfolio cap: block if (open_positions + 1) * RISK_PCT > CAP_PCT
      - Daily stop:   block if closed P&L on entry day <= -DAILY_STOP% of balance
    Operates on a merged, time-sorted list of candidates.
    """
    sorted_trades = sorted(all_trades, key=lambda t: t['entry_time'])
    open_exits   = []      # exit_times of currently open positions
    daily_closed = {}      # date -> cumulative closed P&L (£)
    risk_per_r   = START_BAL * RISK_PCT / 100.0
    accepted     = []

    for trade in sorted_trades:
        et = trade['entry_time']

        # Age out positions that have closed before this entry
        open_exits = [x for x in open_exits if x > et]
        n_open = len(open_exits)

        # Portfolio cap
        if (n_open + 1) * RISK_PCT > CAP_PCT:
            continue

        # Daily stop — use entry day; tracks closed P&L that has already settled
        today_pnl = daily_closed.get(et.date(), 0.0)
        if today_pnl / START_BAL * 100.0 <= -DAILY_STOP:
            continue

        # Accept trade
        open_exits.append(trade['exit_time'])
        pnl = trade['r_net'] * risk_per_r
        exit_day = trade['exit_time'].date()
        daily_closed[exit_day] = daily_closed.get(exit_day, 0.0) + pnl
        accepted.append({**trade, 'pnl_gbp': pnl})

    return accepted


# ---- Reporting ---------------------------------------------------------
DIVIDER = '─' * 72

def report(label, trades):
    risk_per_r = START_BAL * RISK_PCT / 100.0
    print(f'\n  {label}')
    print(f'  {DIVIDER}')
    if not trades:
        print('  NO TRADES'); return
    r = np.array([t['r_net'] for t in trades])
    w = r[r>0]; l = r[r<=0]
    pf   = round(w.sum()/abs(l.sum()), 2) if len(l) and l.sum()!=0 else 0.0
    wr   = round(len(w)/len(r)*100, 1)
    tot  = r.sum()
    gbp  = tot * risk_per_r
    print(f'  Trades: {len(trades):>3}  |  WR: {wr}%  |  PF: {pf}  |  Total: {tot:+.2f}R  |  Est P&L: £{gbp:+,.0f}')

    # Per-instrument
    by_inst = {}
    for t in trades:
        by_inst.setdefault(t['instrument'], []).append(t['r_net'])
    print(f'\n  {"Instrument":>8}  {"N":>4}  {"WR%":>6}  {"PF":>6}  {"Total R":>9}  {"Est £":>9}')
    for k in sorted(by_inst):
        rv = np.array(by_inst[k])
        wv = rv[rv>0]; lv = rv[rv<=0]
        ipf = round(wv.sum()/abs(lv.sum()),2) if len(lv) and lv.sum()!=0 else 0.0
        iwr = round(len(wv)/len(rv)*100,0)
        print(f'  {k:>8}  {len(rv):>4}  {iwr:>5.0f}%  {ipf:>6.2f}  {rv.sum():>+9.2f}  £{rv.sum()*risk_per_r:>+8,.0f}')

    # Day-by-day summary
    by_day = {}
    for t in trades:
        d = t['entry_time'].date()
        by_day.setdefault(d, []).append(t['r_net'])
    print(f'\n  Date         Trades  R')
    for d in sorted(by_day):
        rv = np.array(by_day[d])
        print(f'  {d}    {len(rv):>3}   {rv.sum():+.2f}R')


# ---- Main --------------------------------------------------------------
print('Loading OANDA M1 data...')
loaded = [k for k in FILES if load(k)]
print(f'Loaded: {loaded}\n')

print('Scenario 1: OLD (HasOpenPosition + wrong USDJPY hours)...')
trades_old = []
for k in loaded:
    trades_old.extend(collect(k, H1_HOURS_OLD, has_open_pos_mode=True))

print('Scenario 2: NEW unconstrained (v2.07 pure backtest)...')
trades_new = []
for k in loaded:
    trades_new.extend(collect(k, H1_HOURS_NEW, has_open_pos_mode=False))

print('Scenario 3: NEW + portfolio cap 4% + daily stop 4.5%...')
trades_cap = apply_constraints(trades_new)

print()
print('=' * 72)
print('  JULY 2026 — SCENARIO COMPARISON  (NATGAS excluded — FTMO spread issue)')
print('=' * 72)

report('1. OLD  — HasOpenPosition + wrong USDJPY hours', trades_old)
report('2. NEW  — v2.07 raw backtest (no portfolio constraints)', trades_new)
report('3. CAP  — v2.07 + 4% portfolio cap + 4.5% daily stop', trades_cap)

print()
print('=' * 72)
rpr = START_BAL * RISK_PCT / 100.0
r_old = sum(t['r_net'] for t in trades_old)
r_new = sum(t['r_net'] for t in trades_new)
r_cap = sum(t['r_net'] for t in trades_cap)
print(f'  OLD vs CAP:  {r_old:+.2f}R (£{r_old*rpr:+,.0f})  →  {r_cap:+.2f}R (£{r_cap*rpr:+,.0f})')
print(f'  Backtest ceiling (unconstrained): {r_new:+.2f}R  £{r_new*rpr:+,.0f}')
cap_lost = r_new - r_cap
print(f'  Cost of portfolio cap + daily stop vs raw: {cap_lost:.2f}R  £{cap_lost*rpr:,.0f}')
print('=' * 72)
print('Done.')
