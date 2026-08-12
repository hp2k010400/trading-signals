"""
alpha04_leadlag_descriptive_ftmo.py

Phase 3 of the alpha04 protocol (cross-timezone equity index lead-lag).
DESCRIPTIVE ONLY -- no strategy, no stop/target, no filters. Measures
whether one region's regular-session return predicts the NEXT region's
open-window return, at multiple horizons, for the specific market pairs
identified as genuine closed-to-open (or explicitly-labeled overlap)
handoffs in ALPHA04_MARKET_CLOCK.md:

  1. SP500 session  -> AUS200 open response   (clean: true dead-zone gap)
  2. SP500 session  -> JP225  open response   (clean: true dead-zone gap)
  3. SP500 session  -> HK50   open response   (contaminated: AUS200/JP225
                                                already reacted by the time
                                                HK50 opens)
  4. JP225 session  -> DAX    open response   (clean-ish: Asia fully closed
                                                before Europe opens)
  5. DAX pre-US-open partial return -> SP500 open response
                                               (OVERLAP, not a closed-market
                                                handoff -- US opens ~2-3h
                                                before Europe closes. Labeled
                                                as a different question:
                                                "does Europe's move into the
                                                US open predict the US open
                                                reaction")

One representative instrument is used per region as the leader/follower
proxy (SP500 for US, JP225/Nikkei for Asia, DAX for Europe) -- the same
convention as the broad-index proxies used throughout the cited
literature -- rather than pooling all regional instruments together,
so the reported numbers are traceable to a specific, real series rather
than an averaged composite. AUS200/HK50 are tested as followers in
cases 1-3 to see whether the effect (if any) generalises across Asia,
not just Japan.

For each case and each horizon, reports: N, correlation(leader return,
follower response), and the top-quintile-minus-bottom-quintile spread
(bp) -- same style as alpha03's descriptive script. Also breaks the
primary 'full follower session' horizon down by Discovery/Validation/
Final-OOS period (same 50th/75th percentile-of-date split convention
used throughout this research programme) to check for stability before
any strategy is built.

Run in Codespace: python -u alpha04_leadlag_descriptive_ftmo.py
"""
import pandas as pd
import numpy as np
import datetime as dt
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

FILES = {
    'AUS200': 'AUS200_M1_ftmo.csv',
    'JP225':  'JP225_M1_ftmo.csv',
    'HK50':   'HK50_M1_ftmo.csv',
    'DAX':    'GER40_M1_ftmo.csv',
    'SP500':  'US500_M1_ftmo.csv',
}

# Regular session windows in BROKER time-of-day (hour, minute), per
# ALPHA04_MARKET_CLOCK.md. Approximate / DST-naive -- expect some noise
# around DST transition weeks, noted there as an accepted limitation.
SESSIONS = {
    'AUS200': (dt.time(3, 0), dt.time(9, 0)),
    'JP225':  (dt.time(3, 0), dt.time(9, 0)),
    'HK50':   (dt.time(4, 30), dt.time(11, 0)),
    'DAX':    (dt.time(10, 0), dt.time(19, 30)),
    'SP500':  (dt.time(16, 30), dt.time(23, 59)),  # US session; end used only
                                                     # as a cap, real close
                                                     # detected from data
}

HORIZONS_MIN = [5, 15, 30, 60, 120, 240]


def load_price(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    return df.dropna()


def build_sessions(m1, start_time, end_time):
    """One row per trading day: open_ts/open_price/close_ts/close_price
    for the regular session window. Handles sessions that cross midnight
    (end_time <= start_time)."""
    idx = m1.index
    close_vals = m1['close']
    wraps = end_time <= start_time
    dates = pd.Series(idx.normalize().unique())
    rows = []
    for d in dates:
        day_start = d + pd.Timedelta(hours=start_time.hour, minutes=start_time.minute)
        day_end = d + pd.Timedelta(days=1 if wraps else 0, hours=end_time.hour, minutes=end_time.minute)
        open_pos = idx.searchsorted(day_start)
        close_pos = idx.searchsorted(day_end) - 1
        if open_pos >= len(idx) or close_pos < 0 or open_pos >= close_pos:
            continue
        if (idx[open_pos] - day_start) > pd.Timedelta(hours=2):
            continue  # weekend/holiday gap grabbed the wrong bar
        rows.append({'open_ts': idx[open_pos], 'open_price': float(close_vals.iloc[open_pos]),
                     'close_ts': idx[close_pos], 'close_price': float(close_vals.iloc[close_pos])})
    return pd.DataFrame(rows)


def ts_utc(x):
    """numpy datetime64 (tz-naive) -> tz-aware pandas Timestamp (UTC),
    needed because .values strips tz info from a DatetimeIndex/Series."""
    return pd.Timestamp(x).tz_localize('UTC')


def horizon_response(m1, open_ts, minutes, session_close_ts=None):
    idx = m1.index
    pos = idx.searchsorted(open_ts)
    if pos >= len(idx):
        return np.nan
    if minutes == 'session':
        if session_close_ts is None:
            return np.nan
        end_pos = idx.searchsorted(session_close_ts)
    else:
        end_pos = idx.searchsorted(open_ts + pd.Timedelta(minutes=minutes)) - 1
    if end_pos <= pos or end_pos >= len(idx):
        return np.nan
    o = float(m1['close'].iloc[pos])
    c = float(m1['close'].iloc[end_pos])
    if o <= 0:
        return np.nan
    return np.log(c / o)


def pair_leader_to_follower(leader_close_ts, follower_open_ts_arr, max_gap_days=4):
    """For each leader session close, find the first follower session open
    at or after it. Rejects pairs with an implausibly large gap (data hole)."""
    pos = np.searchsorted(follower_open_ts_arr, leader_close_ts)
    out = np.full(len(leader_close_ts), -1, dtype=np.int64)
    for i, p in enumerate(pos):
        if p < len(follower_open_ts_arr):
            gap = (follower_open_ts_arr[p] - leader_close_ts[i]) / np.timedelta64(1, 'D')
            if 0 <= gap <= max_gap_days:
                out[i] = p
    return out


def report_case(name, leader_ret, follower_resp_by_h, note=''):
    print(f'\n{"="*100}\n  {name}{"  [" + note + "]" if note else ""}\n{"="*100}')
    for h, resp in follower_resp_by_h.items():
        mask = ~(np.isnan(leader_ret) | np.isnan(resp))
        lr = leader_ret[mask]
        fr = resp[mask]
        n = len(lr)
        if n < 30:
            print(f'  h={str(h):>8}  N={n:>6}  (too few observations)')
            continue
        corr = np.corrcoef(lr, fr)[0, 1]
        order = np.argsort(lr)
        q = max(1, n // 5)
        bottom = fr[order[:q]].mean() * 10000
        top = fr[order[-q:]].mean() * 10000
        print(f'  h={str(h):>8}  N={n:>6}  corr={corr:>+7.4f}  bottom20%={bottom:>+7.2f}bp  '
              f'top20%={top:>+7.2f}bp  spread={top-bottom:>+7.2f}bp')


def by_period(leader_ret, follower_resp_session, leader_close_ts_valid):
    dates = pd.Series(leader_close_ts_valid).sort_values()
    n = len(dates)
    if n < 60:
        print('  (too few observations for period breakdown)')
        return
    disc_end = dates.iloc[int(n * 0.50)]
    val_end = dates.iloc[int(n * 0.75)]
    ts = pd.Series(leader_close_ts_valid)
    for label, mask in [
        ('DISCOVERY', ts < disc_end),
        ('VALIDATION', (ts >= disc_end) & (ts < val_end)),
        ('FINAL OOS', ts >= val_end),
    ]:
        m = mask.values & ~(np.isnan(leader_ret) | np.isnan(follower_resp_session))
        lr = leader_ret[m]
        fr = follower_resp_session[m]
        if len(lr) < 20:
            print(f'  {label:<12} N={len(lr):>6}  (too few)')
            continue
        corr = np.corrcoef(lr, fr)[0, 1]
        order = np.argsort(lr)
        q = max(1, len(lr) // 5)
        bottom = fr[order[:q]].mean() * 10000
        top = fr[order[-q:]].mean() * 10000
        print(f'  {label:<12} N={len(lr):>6}  corr={corr:>+7.4f}  spread(top-bottom)={top-bottom:>+7.2f}bp')


print('Loading price data...')
data = {}
for sym in FILES:
    r = load_price(sym)
    if r is not None:
        data[sym] = r
        print(f'  {sym}: {len(r)} bars, {r.index[0].date()} -> {r.index[-1].date()}')
    else:
        print(f'  {sym}: FILE NOT FOUND, skipped')

if 'SP500' not in data:
    raise SystemExit('SP500 (US proxy) required, not found.')

sp500_sessions = build_sessions(data['SP500'], *SESSIONS['SP500'])
print(f'\nSP500 sessions built: {len(sp500_sessions)}')

# ============================================================
# CASES 1-3: SP500 session -> AUS200 / JP225 / HK50 open response
# ============================================================
for follower in ['AUS200', 'JP225', 'HK50']:
    if follower not in data:
        continue
    fol_sessions = build_sessions(data[follower], *SESSIONS[follower])
    follower_open_arr = fol_sessions['open_ts'].values
    pos = pair_leader_to_follower(sp500_sessions['close_ts'].values, follower_open_arr)
    valid = pos >= 0
    leader_ret = np.log(sp500_sessions['close_price'].values[valid] / sp500_sessions['open_price'].values[valid])
    fol_idx = pos[valid]
    follower_open_ts = fol_sessions['open_ts'].values[fol_idx]
    follower_close_ts = fol_sessions['close_ts'].values[fol_idx]

    resp_by_h = {}
    for h in HORIZONS_MIN:
        resp = np.array([horizon_response(data[follower], ts_utc(t), h) for t in follower_open_ts])
        resp_by_h[h] = resp
    resp_session = np.array([horizon_response(data[follower], ts_utc(o), 'session', ts_utc(c))
                              for o, c in zip(follower_open_ts, follower_close_ts)])
    resp_by_h['session'] = resp_session

    note = 'clean handoff' if follower in ('AUS200', 'JP225') else 'CONTAMINATED: AUS200/JP225 already reacted'
    report_case(f'SP500 session -> {follower} open', leader_ret, resp_by_h, note)
    print('  By period (session horizon):')
    by_period(leader_ret, resp_session, sp500_sessions['close_ts'].values[valid])

# ============================================================
# CASE 4: JP225 session -> DAX open response
# ============================================================
if 'JP225' in data and 'DAX' in data:
    jp_sessions = build_sessions(data['JP225'], *SESSIONS['JP225'])
    dax_sessions = build_sessions(data['DAX'], *SESSIONS['DAX'])
    dax_open_arr = dax_sessions['open_ts'].values
    pos = pair_leader_to_follower(jp_sessions['close_ts'].values, dax_open_arr)
    valid = pos >= 0
    leader_ret = np.log(jp_sessions['close_price'].values[valid] / jp_sessions['open_price'].values[valid])
    fol_idx = pos[valid]
    dax_open_ts = dax_sessions['open_ts'].values[fol_idx]
    dax_close_ts = dax_sessions['close_ts'].values[fol_idx]

    resp_by_h = {}
    for h in HORIZONS_MIN:
        resp = np.array([horizon_response(data['DAX'], ts_utc(t), h) for t in dax_open_ts])
        resp_by_h[h] = resp
    resp_session = np.array([horizon_response(data['DAX'], ts_utc(o), 'session', ts_utc(c))
                              for o, c in zip(dax_open_ts, dax_close_ts)])
    resp_by_h['session'] = resp_session

    report_case('JP225 session -> DAX open', leader_ret, resp_by_h, 'clean-ish: Asia fully closed before Europe opens')
    print('  By period (session horizon):')
    by_period(leader_ret, resp_session, jp_sessions['close_ts'].values[valid])

# ============================================================
# CASE 5: DAX pre-US-open partial return -> SP500 open response
#   NOT a closed-market handoff -- SP500 opens while DAX is still trading.
#   Leader signal = DAX's return from ITS OWN open up to the moment SP500 opens.
# ============================================================
if 'DAX' in data and 'SP500' in data:
    dax_sessions_full = build_sessions(data['DAX'], *SESSIONS['DAX'])
    sp_open_arr = sp500_sessions['open_ts'].values
    # pair each DAX session open to the SP500 open that falls within that DAX session
    pos = pair_leader_to_follower(dax_sessions_full['open_ts'].values, sp_open_arr, max_gap_days=1)
    valid = pos >= 0
    dax_open_ts_v = dax_sessions_full['open_ts'].values[valid]
    dax_open_price_v = dax_sessions_full['open_price'].values[valid]
    fol_idx = pos[valid]
    sp_open_ts = sp500_sessions['open_ts'].values[fol_idx]
    sp_close_ts = sp500_sessions['close_ts'].values[fol_idx]

    # DAX return from its own open to the moment SP500 opens
    idx_dax = data['DAX'].index
    leader_ret = []
    for ot, sot in zip(dax_open_ts_v, sp_open_ts):
        p1 = idx_dax.searchsorted(ts_utc(ot))
        p2 = idx_dax.searchsorted(ts_utc(sot)) - 1
        if p1 >= len(idx_dax) or p2 <= p1 or p2 >= len(idx_dax):
            leader_ret.append(np.nan)
            continue
        o = float(data['DAX']['close'].iloc[p1])
        c = float(data['DAX']['close'].iloc[p2])
        leader_ret.append(np.log(c / o) if o > 0 else np.nan)
    leader_ret = np.array(leader_ret)

    resp_by_h = {}
    for h in HORIZONS_MIN:
        resp = np.array([horizon_response(data['SP500'], ts_utc(t), h) for t in sp_open_ts])
        resp_by_h[h] = resp
    resp_session = np.array([horizon_response(data['SP500'], ts_utc(o), 'session', ts_utc(c))
                              for o, c in zip(sp_open_ts, sp_close_ts)])
    resp_by_h['session'] = resp_session

    report_case('DAX pre-US-open return -> SP500 open', leader_ret, resp_by_h,
                'OVERLAP, not a handoff: US opens while DAX still trading')
    print('  By period (session horizon):')
    by_period(leader_ret, resp_session, sp_open_ts)

print('\nDone.')
