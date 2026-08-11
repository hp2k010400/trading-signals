"""
news_breakout_indices_ftmo.py

Isolation test of news_breakout_ftmo.py's real finding: every equity
index was profitable (DAX PF 1.99, UK100 PF 2.19, US30 PF 1.25, NAS100
PF 1.14, SP500 PF 1.05) while every FX pair and Gold was losing (PF
0.40-0.92) in the blended run. That's not noise -- indices show
sustained post-news momentum (institutional repositioning takes hours),
while FX is efficient/fast enough that our ATR-based straddle often
chases a move that's already priced in.

This restricts the exact same mechanism to ONLY the instruments that
showed a real signal (DAX, NAS100, SP500, US30, UK100, NATGAS), so the
walk-forward windows reflect the isolated edge instead of being dragged
by the FX/Gold losers. The blended full-period per-instrument numbers
don't tell us whether the index edge was consistent over time or
front/back-loaded -- this does.

Same mechanism, same currency mapping, same confirmed UTC+3 (price)
and UTC+3 (calendar) offsets as news_breakout_ftmo.py.

Run in Codespace: python -u news_breakout_indices_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
CALENDAR_UTC_OFFSET_HOURS = 3

BREAKOUT_ATR_MULT = 0.5
ATR_STOP_MULT = 1.0
RR = 1.5
COST_MULT = 1.5
WATCH_MINUTES = 30
MAX_HOLD_HOURS = 4
ATR_PERIOD = 14
WALK_FORWARD_MONTHS = 6
MIN_STOP_DIST_PCT = 0.0005   # stop distance must be >= 0.05% of price, else skip (degenerate ATR guard)

CALENDAR_FILE = 'HighImpactCalendar.csv'

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'NATGAS':'NATGAS_cash_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'WTIOIL':  'WTIOIL_M1_ftmo.csv',
    'BRENTOIL':'BRENTOIL_M1_ftmo.csv',
    'SILVER':  'SILVER_M1_ftmo.csv',
    'COPPER':  'COPPER_M1_ftmo.csv',
    'PLATINUM':'PLATINUM_M1_ftmo.csv',
    'PALLADIUM':'PALLADIUM_M1_ftmo.csv',
    'USDINDEX':'USDINDEX_M1_ftmo.csv',
}
COST_POINTS = {
    'DAX':1.33, 'NAS100':1.5, 'SP500':0.6, 'US30':2.0, 'UK100':1.8, 'NATGAS':0.008,
    # UNCALIBRATED ESTIMATES -- same caveat as the lesser-traded FX crosses,
    # never pulled real spreads from live Market Watch for these instruments
    'FRA40':1.5, 'JP225':8.0, 'AUS200':2.0, 'EU50':1.2, 'US2000':0.4, 'HK50':10.0,
    'WTIOIL':0.04, 'BRENTOIL':0.04, 'SILVER':0.025, 'COPPER':0.008,
    'PLATINUM':0.5, 'PALLADIUM':2.0, 'USDINDEX':0.02,
}
# US macro news moves global equities regardless of which country they're
# listed in (real, well-established mechanism, not a stretch) -- so every
# index reacts to USD releases in addition to its own home currency's.
# Oil/Silver/Copper/Platinum/Palladium are USD-priced commodities, and the
# US Dollar Index is a direct USD basket -- all react to USD macro too.
CURRENCY_MAP = {
    'USD': ['NAS100','SP500','US30','US2000','DAX','UK100','FRA40','EU50','JP225','AUS200','HK50',
             'WTIOIL','BRENTOIL','SILVER','COPPER','PLATINUM','PALLADIUM','USDINDEX'],
    'EUR': ['DAX','FRA40','EU50'],
    'GBP': ['UK100'],
    'JPY': ['JP225'],
    'AUD': ['AUS200'],
}

def load_price(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None, None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    h1 = df.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    prev_close = h1['close'].shift(1)
    tr = pd.concat([h1['high']-h1['low'], (h1['high']-prev_close).abs(), (h1['low']-prev_close).abs()], axis=1).max(axis=1)
    h1['atr'] = tr.rolling(ATR_PERIOD).mean().shift(1)
    h1 = h1.dropna()
    return df, h1


def is_gas_storage(name):
    n = str(name).upper()
    return ('NATURAL GAS' in n) or ('GAS STORAGE' in n)


def is_crude_oil(name):
    n = str(name).upper()
    return ('CRUDE OIL' in n) or ('CRUDE INVENTORIES' in n) or ('OIL INVENTORIES' in n)


def load_calendar():
    if not os.path.exists(CALENDAR_FILE):
        return None
    df = pd.read_csv(CALENDAR_FILE, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=CALENDAR_UTC_OFFSET_HOURS)
    n_before = len(df)
    # MT5's calendar stores multiple "revisions" of the same real-world event
    # (preliminary/revised/final figures) as separate rows, often with the
    # same or near-identical timestamp. Treating each as an independent trade
    # fires the "same" event multiple times and blows up compounded monthly
    # P&L (confirmed: one month showed +30,460%, impossible from real edge).
    df = df.drop_duplicates(subset=['currency', 'event_name', 'time'])
    n_after = len(df)
    if n_after < n_before:
        print(f'Dropped {n_before - n_after} duplicate calendar rows (same currency/event/time).')
    return df.sort_values('time').reset_index(drop=True)


def find_trade_for_event(symbol, m1, h1, event_time):
    m1_index = m1.index
    h1_index = h1.index

    h1_pos = h1_index.searchsorted(event_time) - 1
    if h1_pos < 0 or h1_pos >= len(h1):
        return None
    atr = h1.iloc[h1_pos]['atr']
    if pd.isna(atr) or atr <= 0:
        return None

    m1_pos = m1_index.searchsorted(event_time)
    if m1_pos <= 0 or m1_pos >= len(m1):
        return None
    ref_price = float(m1['close'].iloc[m1_pos - 1])

    trigger_up = ref_price + BREAKOUT_ATR_MULT * atr
    trigger_down = ref_price - BREAKOUT_ATR_MULT * atr

    watch_end = min(m1_pos + WATCH_MINUTES, len(m1))
    watch = m1.iloc[m1_pos:watch_end]
    if len(watch) == 0:
        return None

    direction = 0
    entry_price = None
    entry_pos = None
    highs = watch['high'].values; lows = watch['low'].values
    for k in range(len(watch)):
        hit_up = highs[k] >= trigger_up
        hit_down = lows[k] <= trigger_down
        if hit_up and hit_down:
            return None
        if hit_up:
            direction = 1; entry_price = trigger_up; entry_pos = m1_pos + k; break
        if hit_down:
            direction = -1; entry_price = trigger_down; entry_pos = m1_pos + k; break

    if direction == 0:
        return None

    stop_dist = ATR_STOP_MULT * atr
    # Guard against a near-zero ATR (data gap / illiquid bar / bad tick)
    # producing a degenerate stop distance -- dividing cost or the fallback
    # R calc by something tiny blows up into an absurd trade. Require the
    # stop to be at least a meaningful fraction of price.
    if stop_dist < ref_price * MIN_STOP_DIST_PCT:
        return None
    stop_price = entry_price - stop_dist if direction == 1 else entry_price + stop_dist
    tp_price = entry_price + stop_dist * RR if direction == 1 else entry_price - stop_dist * RR

    window_end = min(entry_pos + 1 + MAX_HOLD_HOURS * 60, len(m1))
    future = m1.iloc[entry_pos + 1: window_end]
    r_gross = None
    if len(future) > 0:
        fh = future['high'].values; fl = future['low'].values; fc = future['close'].values
        for k in range(len(future)):
            if direction == 1:
                if fh[k] >= tp_price: r_gross = RR; break
                if fl[k] <= stop_price: r_gross = -1.0; break
            else:
                if fl[k] <= tp_price: r_gross = RR; break
                if fh[k] >= stop_price: r_gross = -1.0; break
        if r_gross is None:
            final_close = fc[-1]
            r_gross = ((final_close - entry_price) / stop_dist if direction == 1
                       else (entry_price - final_close) / stop_dist)
            # A trade that never touched stop or target intrabar (checked
            # every bar's high/low above) should, by definition, resolve
            # within roughly [-1, RR]. Anything further out can only come
            # from a corrupted/inconsistent OHLC row (close far from that
            # bar's own high/low) -- clip rather than let a single bad row
            # blow up the whole backtest.
            r_gross = max(-2.0, min(RR + 0.5, r_gross))
    else:
        r_gross = -1.0

    cost_r = COST_POINTS[symbol] / stop_dist * COST_MULT
    return {'symbol': symbol, 'entry_time': m1_index[entry_pos], 'r_net': r_gross - cost_r}


def compute_stats(r_values):
    if len(r_values) == 0:
        return 0, 0.0, 0.0, 0.0
    wins = r_values[r_values > 0]
    losses = r_values[r_values <= 0]
    pf = round(wins.sum() / abs(losses.sum()), 3) if len(losses) and losses.sum() != 0 else 0.0
    wr = round(len(wins) / len(r_values) * 100, 2)
    return len(r_values), wr, pf, r_values.sum()


def print_row(label, n, wr, pf, tot, width=26):
    flag = ' <- LOSING' if tot < 0 else ''
    print(f'  {label+flag:<{width+10}}  N={n:>6}  WR={wr:>5.1f}%  PF={pf:>5.2f}  R={tot:>+9.2f}')


RISK_PCT = 0.30
START_BAL = 70000.0
# Walk-forward showed 2018-2021 uniformly strong (PF 1.4-3.7) but 2022
# onward mixed/weak (5 of 9 half-year windows losing or barely breakeven).
# That's an important question: is the edge decaying, or was 2019-2021 just
# an exceptionally volatile era (COVID crash/recovery, stimulus, meme-stock
# mania) this vol-breakout mechanism happened to love, unlikely to repeat?
# This isolates performance on ONLY the recent/current-regime years.
RECENT_CUTOFF = pd.Timestamp('2022-01-01', tz='UTC')

cal = load_calendar()
if cal is None:
    raise SystemExit(f'{CALENDAR_FILE} not found -- upload it first.')
print(f'Loaded {len(cal)} calendar events.\n')

cal_gas = cal[cal['event_name'].apply(is_gas_storage)]
cal_oil = cal[cal['event_name'].apply(is_crude_oil)]
cal_macro = cal[~cal['event_name'].apply(is_gas_storage) & ~cal['event_name'].apply(is_crude_oil)]

events_for_symbol = {s: [] for s in FILES}
events_for_symbol['NATGAS'] = list(cal_gas['time'])
events_for_symbol['WTIOIL'] = list(cal_oil['time'])
events_for_symbol['BRENTOIL'] = list(cal_oil['time'])
for currency, symbols in CURRENCY_MAP.items():
    times = list(cal_macro[cal_macro['currency'] == currency]['time'])
    for s in symbols:
        events_for_symbol[s].extend(times)

all_trades = []
loaded = []
for symbol in FILES:
    ev_times = events_for_symbol.get(symbol, [])
    if not ev_times or not os.path.exists(FILES[symbol]):
        continue
    print(f'Processing {symbol}: {len(ev_times)} candidate events...')
    m1, h1 = load_price(symbol)
    if m1 is None:
        continue
    loaded.append(symbol)
    for t in ev_times:
        trade = find_trade_for_event(symbol, m1, h1, t)
        if trade is not None:
            trade['event_time'] = t   # which calendar event triggered this, for cluster risk-sizing
            all_trades.append(trade)
    del m1, h1
    gc.collect()

print(f'\nLoaded {len(loaded)} instruments: {loaded}')

df = pd.DataFrame(all_trades)
if len(df) > 0:
    df = df.sort_values('entry_time').reset_index(drop=True)
print(f'Total trades: {len(df)}')
if len(df) < 80:
    print('WARNING: fewer than 80 trades -- treat every number below as unreliable.')

if len(df) > 0:
    biggest = df.reindex(df['r_net'].abs().sort_values(ascending=False).index).head(10)
    print('\nLargest |r_net| trades (sanity-check for data anomalies -- a legitimate\n'
          'trade should be roughly in [-1, RR], so anything far outside that is suspect):')
    for _, row in biggest.iterrows():
        print(f'  {row["entry_time"]}  {row["symbol"]:<8}  r_net={row["r_net"]:>+10.3f}')

def report(label, sub_df, loaded_instruments):
    print(f'\n{"="*90}')
    print(f'  {label}  (N={len(sub_df)})')
    print(f'{"="*90}')
    if len(sub_df) == 0:
        print('  No trades in this period.')
        return
    if len(sub_df) < 80:
        print('  WARNING: fewer than 80 trades -- treat every number below as unreliable.')

    n, wr, pf, tot = compute_stats(sub_df['r_net'].values)
    print_row('OVERALL', n, wr, pf, tot)

    print(f'\n  WALK-FORWARD VALIDATION ({WALK_FORWARD_MONTHS}-month non-overlapping windows)')
    periods = sub_df['entry_time'].dt.to_period('M')
    all_periods = sorted(periods.unique())
    n_losing = 0
    n_total = 0
    for i in range(0, len(all_periods), WALK_FORWARD_MONTHS):
        window_periods = all_periods[i:i+WALK_FORWARD_MONTHS]
        window_rv = sub_df[periods.isin(window_periods)]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(window_rv)
        n_total += 1
        if tot2 < 0:
            n_losing += 1
        print(f'  {window_periods[0]} -> {window_periods[-1]}   N={n2:>5}  WR={wr2:>5.1f}%  PF={pf2:>5.2f}'
              + (' <- LOSING' if tot2 < 0 else ''))
    print(f'\n  Losing windows: {n_losing}/{n_total}')

    print(f'\n  Per-instrument:')
    for symbol in loaded_instruments:
        rv = sub_df[sub_df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        print_row(f'  {symbol}', n2, wr2, pf2, tot2)

    # Monthly P&L: NOT compounded trade-to-trade within the month (many
    # trades fire within the same minute -- correlated indices reacting to
    # one shared news event -- so sequential re-sizing off a continuously
    # updated balance is unrealistic and mathematically explosive, confirmed
    # earlier). Risk is also split across correlated same-event trades: a
    # single release can fire trades in up to 11+ instruments simultaneously,
    # and giving each the FULL per-trade risk overstates real exposure in
    # both directions (confirmed: pre-fix worst month was -98.26%, an
    # FTMO-account-ending month, and best was +2322%, both from clustering
    # not genuine edge).
    cluster_size = sub_df.groupby('event_time')['symbol'].transform('count')
    risk_frac_pct = RISK_PCT / cluster_size

    print(f'\n  MONTHLY P&L (each month fresh from £{START_BAL:,.0f}, {RISK_PCT}% risk PER EVENT split')
    print(f'  across however many correlated instruments react to it, additive not compounded)')
    rows = []
    for period, g in sub_df.groupby(periods):
        rf = risk_frac_pct.loc[g.index]
        pnl = START_BAL * (g['r_net'] * rf / 100.0).sum()
        rows.append({'month': str(period), 'trades': len(g), 'pnl_gbp': pnl, 'pnl_pct': pnl / START_BAL * 100})
    monthly = pd.DataFrame(rows).sort_values('month').reset_index(drop=True)
    print(f'  Months with activity: {len(monthly)}')
    print(f'  Best month:   {monthly.loc[monthly["pnl_gbp"].idxmax(), "month"]}  £{monthly["pnl_gbp"].max():>+9,.0f}  ({monthly["pnl_pct"].max():+.2f}%)')
    print(f'  Worst month:  {monthly.loc[monthly["pnl_gbp"].idxmin(), "month"]}  £{monthly["pnl_gbp"].min():>+9,.0f}  ({monthly["pnl_pct"].min():+.2f}%)')
    print(f'  Median month: £{monthly["pnl_gbp"].median():>+9,.0f}  ({monthly["pnl_pct"].median():+.2f}%)')
    print(f'  Mean month:   £{monthly["pnl_gbp"].mean():>+9,.0f}  ({monthly["pnl_pct"].mean():+.2f}%)')
    pct_profitable = (monthly['pnl_gbp'] > 0).mean() * 100
    print(f'  Profitable months: {pct_profitable:.1f}% ({(monthly["pnl_gbp"]>0).sum()}/{len(monthly)})')


if len(df) > 0:
    biggest = df.reindex(df['r_net'].abs().sort_values(ascending=False).index).head(10)
    print('\nLargest |r_net| trades (sanity-check for data anomalies -- a legitimate\n'
          'trade should be roughly in [-1, RR], so anything far outside that is suspect):')
    for _, row in biggest.iterrows():
        print(f'  {row["entry_time"]}  {row["symbol"]:<8}  r_net={row["r_net"]:>+10.3f}')

    report('FULL HISTORY', df, loaded)

    recent_df = df[df['entry_time'] >= RECENT_CUTOFF].reset_index(drop=True)
    report(f'RECENT ONLY ({RECENT_CUTOFF.date()} onward -- excludes the 2019-2021 outlier era)',
           recent_df, loaded)

    # Genuine out-of-sample test: pick "winning" instruments using ONLY the
    # SELECTION window, then test that fixed selection on the HOLDOUT window
    # it never saw. Naively eyeballing "which instruments are green in the
    # recent numbers" and calling that the strategy is exactly the kind of
    # curve-fitting this whole session has been trying to avoid -- this
    # forces the selection to be blind to the data it's judged on.
    SELECTION_START = pd.Timestamp('2022-01-01', tz='UTC')
    HOLDOUT_START = pd.Timestamp('2025-01-01', tz='UTC')
    MIN_SELECTION_TRADES = 200
    SELECTION_PF_THRESHOLD = 1.0

    sel_df = df[(df['entry_time'] >= SELECTION_START) & (df['entry_time'] < HOLDOUT_START)]
    selected = []
    print(f'\n{"="*90}')
    print(f'  INSTRUMENT SELECTION on {SELECTION_START.date()} -> {HOLDOUT_START.date()} '
          f'(PF >= {SELECTION_PF_THRESHOLD}, N >= {MIN_SELECTION_TRADES})')
    print(f'{"="*90}')
    for symbol in loaded:
        rv = sel_df[sel_df['symbol'] == symbol]['r_net'].values
        n2, wr2, pf2, tot2 = compute_stats(rv)
        keep = n2 >= MIN_SELECTION_TRADES and pf2 >= SELECTION_PF_THRESHOLD
        if keep:
            selected.append(symbol)
        print_row(f'  {symbol}{" [SELECTED]" if keep else ""}', n2, wr2, pf2, tot2)
    print(f'\n  Selected {len(selected)} instruments: {selected}')

    holdout_df = df[(df['entry_time'] >= HOLDOUT_START) & (df['symbol'].isin(selected))].reset_index(drop=True)
    report(f'BLIND HOLDOUT ({HOLDOUT_START.date()} onward, selected instruments only, '
           f'never seen during selection)', holdout_df, selected)

print('\nDone.')
