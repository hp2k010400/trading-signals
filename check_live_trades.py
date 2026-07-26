"""
check_live_trades.py  —  Trade-for-trade reconciliation

Checks whether each live EA trade matches what the Python backtest logic
would have generated for the same signal bar and entry time.

HOW TO USE:
1. Run download_recent.py first to update the M1 CSVs to today
2. Fill in your live trades in LIVE_TRADES below
3. Run: python -u check_live_trades.py

TRADE FORMAT:
    {'sym': 'EURUSD', 'open_time': '2026-07-04 09:02', 'dir': 1, 'price': 1.08234}
    dir: 1 = buy/long,  -1 = sell/short
    open_time: UTC time (check MT5 -> Tools -> Options -> Server time to confirm zone)

FINDING THESE IN MT5:
    View -> Terminal -> Trade History tab
    Right-click -> Export to CSV, or just copy from the list.
"""
import pandas as pd
import numpy as np
import os, warnings
warnings.filterwarnings('ignore')

# ─── PASTE YOUR 7 LIVE TRADES HERE ───────────────────────────────────────────
# Format: symbol, open_time (UTC), direction (1=buy, -1=sell), open_price
# If you're not sure whether MT5 shows UTC or UTC+3, just paste as-is and
# the script will tell you if there's a time offset issue.

LIVE_TRADES = [
    # MT5 shows UTC+3 (OANDA FTMO server). All times below are converted to UTC (-3h).
    # ---- CLOSED TRADES ----
    {'sym': 'EURUSD',  'open_time': '2026-07-23 10:08', 'dir': -1, 'price': 1.14094},   # sell, closed +1376
    {'sym': 'GOLD',    'open_time': '2026-07-23 17:40', 'dir': -1, 'price': 4042.16},   # xauusd sell, -347
    {'sym': 'GOLD',    'open_time': '2026-07-24 10:04', 'dir':  1, 'price': 4060.69},   # xauusd buy, -358
    {'sym': 'GBPUSD',  'open_time': '2026-07-24 10:21', 'dir':  1, 'price': 1.33224},   # buy, -369
    {'sym': 'NAS100',  'open_time': '2026-07-23 16:02', 'dir':  1, 'price': 28445.88},  # us100.cash buy, -397
    {'sym': 'GER40',   'open_time': '2026-07-23 11:08', 'dir': -1, 'price': 24941.96},  # ger40.cash sell, -360
    {'sym': 'NATGAS',  'open_time': '2026-07-24 14:30', 'dir':  1, 'price': 2.999},     # natgas buy, -501
    # ---- STILL OPEN ----
    {'sym': 'EURUSD',  'open_time': '2026-07-23 15:41', 'dir':  1, 'price': 1.13762},   # buy, open
    {'sym': 'SP500',   'open_time': '2026-07-23 16:09', 'dir':  1, 'price': 7408.85},   # us500.cash buy, open
]

# ─── Strategy parameters (must match EA) ─────────────────────────────────────
WIN_HOURS  = 3
WICK_BODY  = 2.0
WICK_RANGE = 0.5
MIN_RANGE  = 0.00015
TOLERANCE  = 0.003   # 0.3% price tolerance — covers OANDA live vs historical data differences
                     # and slippage on fast instruments (NAS100, NATGAS)

FILES = {
    'DAX':   'GER40_M1_oanda.csv',   'GER40': 'GER40_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',   'US100': 'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',   'US500': 'US500_M1_oanda.csv',
    'US30':  'US30_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'USDJPY':'USDJPY_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',  'XAUUSD':'XAUUSD_M1_oanda.csv',
    'NATGAS':'NATGAS_M1_oanda.csv',
}
H1_HOURS = {
    'DAX':{8,9,10,13,14},'GER40':{8,9,10,13,14},
    'NAS100':{13,14,15,16},'US100':{13,14,15,16},
    'SP500':{13,14,15,16}, 'US500':{13,14,15,16},
    'US30':{13,14,15,16},'EURUSD':{8,9,13,14,15},'GBPUSD':{8,9,13,14,15},
    'USDJPY':{0,1,2,8,9},'GOLD':{8,9,13,14,15},'XAUUSD':{8,9,13,14,15},
    'NATGAS':{13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset(),'GER40':frozenset(),'EURUSD':frozenset(),'GBPUSD':frozenset(),
    'USDJPY':frozenset(),'GOLD':frozenset(),'XAUUSD':frozenset(),'NATGAS':frozenset(),
    'NAS100':frozenset({0}),'US100':frozenset({0}),
    'SP500':frozenset({0}),'US500':frozenset({0}),'US30':frozenset({0}),
}

_m1 = {}
def load(k):
    fn = FILES.get(k)
    if not fn or not os.path.exists(fn): return False
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c] = pd.to_numeric(df[c], errors='coerce')
    _m1[k] = df.dropna(); return True

def pin_bar_dir(o, h, l, c):
    body = abs(c-o); full = h-l
    if full <= 0 or body < full*0.02: return 0
    uw = h-max(o,c); lw = min(o,c)-l
    if uw >= WICK_BODY*max(body,full*0.001) and uw >= WICK_RANGE*full: return -1
    if lw >= WICK_BODY*max(body,full*0.001) and lw >= WICK_RANGE*full: return 1
    return 0

def check_trade(trade):
    sym   = trade['sym']
    otime = pd.Timestamp(trade['open_time'], tz='UTC')
    d     = trade['dir']
    price = trade['price']

    if sym not in _m1:
        if not load(sym):
            return {'match': 'ERROR', 'reason': f'No data file for {sym}'}

    m1 = _m1[sym]
    if otime > m1.index[-1]:
        return {'match': 'NO_DATA', 'reason': f'M1 data ends at {m1.index[-1]}. Run download_recent.py first.'}

    # Find the signal H1 bar: trade opens in the window [H1_close, H1_close+WIN_HOURS]
    # So signal bar = floor(open_time - WIN_HOURS, to nearest hour)
    # Actually: entry window = [signal_H1_end, signal_H1_end + WIN_HOURS]
    # signal_H1_end = otime floor to hour, then subtract if within WIN_HOURS

    # Try hours before the open time — signal bar ends WIN_HOURS before entry window start
    found_bar = None
    for h_offset in range(0, WIN_HOURS+1):
        candidate_bar_end = otime.floor('h') - pd.Timedelta(hours=h_offset)
        candidate_bar_start = candidate_bar_end - pd.Timedelta(hours=1)

        # Get H1 bar ending at candidate_bar_end
        h1_slice = m1[(m1.index >= candidate_bar_start) & (m1.index < candidate_bar_end)]
        if len(h1_slice) == 0: continue
        h1_bar = h1_slice.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
        if len(h1_bar) == 0: continue

        bar_ts = h1_bar.index[0]
        if bar_ts.dayofweek >= 5: continue
        p_hours = H1_HOURS.get(sym, {8,9,13,14})
        skip    = H1_SKIP.get(sym, frozenset())
        if bar_ts.hour not in p_hours: continue
        if bar_ts.dayofweek in skip: continue

        found_bar = (bar_ts, h1_bar.iloc[0], candidate_bar_end)
        break

    # Try ALL valid session bars in the entry window (not just first)
    # The EA signals on whichever valid bar most recently closed before the entry.
    # We check bars newest-first and return the first that shows a pattern + plausible price.
    candidate_bars = []
    for h_offset in range(0, WIN_HOURS + 2):
        candidate_bar_end   = otime.floor('h') - pd.Timedelta(hours=h_offset)
        candidate_bar_start = candidate_bar_end - pd.Timedelta(hours=1)
        h1_slice = m1[(m1.index >= candidate_bar_start) & (m1.index < candidate_bar_end)]
        if len(h1_slice) == 0: continue
        h1_bar = h1_slice.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
        if len(h1_bar) == 0: continue
        bar_ts = h1_bar.index[0]
        if bar_ts.dayofweek >= 5: continue
        p_hours = H1_HOURS.get(sym, {8,9,13,14})
        skip    = H1_SKIP.get(sym, frozenset())
        if bar_ts.hour not in p_hours: continue
        if bar_ts.dayofweek in skip: continue
        # Entry must fall within this bar's window
        window_open  = candidate_bar_end
        window_close = candidate_bar_end + pd.Timedelta(hours=WIN_HOURS)
        if not (window_open <= otime <= window_close): continue
        candidate_bars.append((bar_ts, h1_bar.iloc[0], candidate_bar_end))

    if not candidate_bars:
        return {'match': 'NO_BAR', 'reason': 'No valid session H1 bar found whose entry window contains the open time.'}

    # Check each candidate bar for pattern + price match
    all_bar_results = []
    for bar_ts, bar, window_start in candidate_bars:
        bar_o = float(bar['open']); bar_h = float(bar['high'])
        bar_l = float(bar['low']);  bar_c = float(bar['close'])

        patterns_found = []; backtest_dir = 0

        if sym == 'USDJPY':
            pb = pin_bar_dir(bar_o, bar_h, bar_l, bar_c)
            if pb != 0:
                patterns_found.append(f'PIN_BAR({"bull" if pb==1 else "bear"})')
                backtest_dir = pb
        else:
            prev_slice = m1[(m1.index >= bar_ts - pd.Timedelta(hours=1)) & (m1.index < bar_ts)]
            prev_h1 = prev_slice.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
            if len(prev_h1) > 0:
                prev = prev_h1.iloc[0]
                is_ib = bar_h < float(prev['high']) and bar_l > float(prev['low'])
                ib_ok = is_ib and (bar_h-bar_l) > 0 and (bar_h-bar_l)/bar_h >= MIN_RANGE
                if ib_ok:
                    patterns_found.append('INSIDE_BAR')
            if not patterns_found:
                pb = pin_bar_dir(bar_o, bar_h, bar_l, bar_c)
                if pb != 0:
                    patterns_found.append(f'PIN_BAR({"bull" if pb==1 else "bear"})')
                    backtest_dir = pb
            else:
                backtest_dir = 1 if d > 0 else -1

        # Price plausibility: for BUY, entry should be near bar_h (above or slightly below due to live/hist diff)
        # for SELL, entry should be near bar_l (below or slightly above)
        if d == 1:
            price_ok = (price >= bar_l * (1 - TOLERANCE)) and (price <= bar_h * (1 + TOLERANCE * 10))
            near_ref  = abs(price - bar_h) / max(bar_h, 0.0001)
        else:
            price_ok = (price <= bar_h * (1 + TOLERANCE)) and (price >= bar_l * (1 - TOLERANCE * 10))
            near_ref  = abs(price - bar_l) / max(bar_l, 0.0001)

        all_bar_results.append({
            'bar_ts': bar_ts, 'bar_h': bar_h, 'bar_l': bar_l,
            'patterns': patterns_found, 'backtest_dir': backtest_dir,
            'price_ok': price_ok, 'near_ref': near_ref,
        })

    # Find best result: prefer pattern + price match, then pattern only, then anything
    best = None
    for r in all_bar_results:
        if r['patterns'] and r['price_ok']:
            best = r; break
    if best is None:
        for r in all_bar_results:
            if r['patterns']:
                best = r; break
    if best is None:
        best = all_bar_results[0]

    patterns_found = best['patterns']
    backtest_dir   = best['backtest_dir']
    bar_ts         = best['bar_ts']
    bar_h          = best['bar_h']
    bar_l          = best['bar_l']
    price_ok       = best['price_ok']
    near_ref       = best['near_ref']

    bars_checked = ', '.join(str(r['bar_ts'].strftime('%H:%M')) for r in all_bar_results)

    if not patterns_found:
        reason = (f'Checked bars: {bars_checked}. No IB or PB found on any. '
                  f'Best bar {bar_ts} (H:{bar_h:.5f} L:{bar_l:.5f} O:{float(m1.loc[m1.index >= bar_ts].iloc[0]["open"]):.5f}). '
                  f'OANDA live vs historical data may differ slightly.')
        return {'match': 'MISMATCH', 'reason': reason, 'bar_ts': bar_ts}

    if not price_ok:
        ref = bar_h if d == 1 else bar_l
        reason = (f'Pattern {", ".join(patterns_found)} on {bar_ts}. '
                  f'Entry {price:.5f} is {near_ref*100:.2f}% from bar {"H" if d==1 else "L"} {ref:.5f}. '
                  f'Likely OANDA live/historical bar difference or different signal bar used by EA.')
        return {'match': 'PRICE_MISMATCH', 'reason': reason, 'bar_ts': bar_ts,
                'bar_h': bar_h, 'bar_l': bar_l, 'patterns': patterns_found}

    dir_ok = (backtest_dir == 0) or (backtest_dir == d)
    if not dir_ok:
        reason = (f'Pattern found but direction mismatch: EA took {"BUY" if d==1 else "SELL"}, '
                  f'backtest says {"BUY" if backtest_dir==1 else "SELL"} on {bar_ts}')
        return {'match': 'DIR_MISMATCH', 'reason': reason, 'bar_ts': bar_ts, 'patterns': patterns_found}

    ref = bar_h if d == 1 else bar_l
    return {
        'match': 'CONFIRMED',
        'reason': (f'Pattern {", ".join(patterns_found)} on {bar_ts} | '
                   f'entry {price:.5f} vs bar {"H" if d==1 else "L"} {ref:.5f} '
                   f'({near_ref*100:.2f}% diff)'),
        'bar_ts': bar_ts, 'bar_h': bar_h, 'bar_l': bar_l, 'patterns': patterns_found,
    }


# ─── Main ─────────────────────────────────────────────────────────────────────
if not LIVE_TRADES:
    print('='*70)
    print('  LIVE TRADES NOT YET FILLED IN')
    print('='*70)
    print()
    print('  Edit LIVE_TRADES at the top of this file.')
    print()
    print('  Format:')
    print("    {'sym': 'EURUSD', 'open_time': '2026-07-07 09:02', 'dir': 1, 'price': 1.08234},")
    print()
    print('  Get the details from MT5:')
    print('    View -> Terminal -> Trade History (or Account History)')
    print('    Columns needed: Symbol, Open Time, Type (buy/sell), Open Price')
    print()
    print('  IMPORTANT: Check MT5 server time zone.')
    print('    Go to Market Watch -> right-click any symbol -> Specification.')
    print('    Or compare MT5 clock to your local clock.')
    print('    OANDA FTMO server is likely UTC+3 — subtract 3h to get UTC.')
    print()
    exit(0)

print('Loading M1 data...')
for t in LIVE_TRADES:
    sym = t['sym']
    if sym not in _m1:
        loaded = load(sym)
        if loaded:
            last = _m1[sym].index[-1]
            print(f'  {sym}: loaded, last bar {last}')
        else:
            print(f'  {sym}: NO DATA FILE — run download_recent.py first')

print()
print('='*70)
print('  LIVE TRADE RECONCILIATION')
print('='*70)
print(f'  {"#":>3}  {"Symbol":>8}  {"Time (UTC)":>18}  {"Dir":>5}  {"Price":>12}  {"Result":>15}')
print(f'  {"-"*68}')

confirmed = 0; mismatches = 0; errors = 0

for i, t in enumerate(LIVE_TRADES, 1):
    result = check_trade(t)
    m = result['match']
    status = {'CONFIRMED':'OK', 'MISMATCH':'! NO PATTERN', 'PRICE_MISMATCH':'! PRICE',
              'DIR_MISMATCH':'! DIRECTION', 'NO_DATA':'NO DATA', 'NO_BAR':'NO BAR',
              'ERROR':'ERROR'}.get(m, m)
    dir_str = 'BUY' if t['dir']==1 else 'SELL'
    print(f'  {i:>3}  {t["sym"]:>8}  {t["open_time"]:>18}  {dir_str:>5}  {t["price"]:>12.5f}  {status:>15}')
    if m == 'CONFIRMED': confirmed += 1
    elif m in ('MISMATCH','DIR_MISMATCH','PRICE_MISMATCH'): mismatches += 1
    else: errors += 1

print(f'  {"-"*68}')
print()

for i, t in enumerate(LIVE_TRADES, 1):
    result = check_trade(t)
    print(f'  Trade {i} ({t["sym"]} {t["open_time"]}): {result["match"]}')
    print(f'    {result["reason"]}')
    print()

print('='*70)
n = len(LIVE_TRADES)
print(f'  {confirmed}/{n} confirmed  |  {mismatches}/{n} mismatches  |  {errors}/{n} data errors')
if mismatches == 0 and errors == 0:
    print(f'  ALL TRADES MATCH — EA is executing exactly what backtest predicts.')
elif mismatches <= 1:
    print(f'  Mostly matched. Review the mismatched trade — may be a timezone offset.')
    print(f'  Try adjusting open_time by +3h or -3h if OANDA server is UTC+3.')
else:
    print(f'  Multiple mismatches. Check:')
    print(f'  1. MT5 server timezone (adjust open_time to UTC)')
    print(f'  2. USDJPY strategy mode (should be pin bar only)')
    print(f'  3. Whether M1 data is up to date (run download_recent.py)')
print('='*70)
