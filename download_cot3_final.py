"""
download_cot3_final.py

Final version — exact, verified contract names for all 7 instruments,
across the two correct CFTC datasets:

  TFF (Traders in Financial Futures, dataset gpe5-46if) — currencies and
  equity indices, "Leveraged Money" = speculator category:
    EURUSD, GBPUSD, USDJPY, SP500, NAS100, US30

  Disaggregated (dataset 72hh-3qpy) — commodities, "Money Manager" =
  speculator category:
    GOLD

  NOT covered: DAX (Eurex-listed, not CFTC-regulated).

Every contract name below was verified against the live API tonight,
not guessed — this replaces the earlier keyword-matching version where
several keywords matched multiple different contracts (e.g. "S&P 500"
matched 9 different contracts) and would have silently picked whichever
came first.

For SP500/NAS100, uses the "Consolidated" contract specifically — CFTC's
own stitched-together series combining old floor-traded and newer
e-mini contracts into one continuous history (842 weeks, the longest
and cleanest option among the matches).

Run in Codespace: python -u download_cot3_final.py
"""
import pandas as pd
import urllib.request
import urllib.parse

TFF_URL   = 'https://publicreporting.cftc.gov/resource/gpe5-46if.csv'
DISAGG_URL = 'https://publicreporting.cftc.gov/resource/72hh-3qpy.csv'

TFF_MARKETS = {
    'EURUSD': 'EURO FX - CHICAGO MERCANTILE EXCHANGE',
    'GBPUSD': 'BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE',
    'USDJPY': 'JAPANESE YEN - CHICAGO MERCANTILE EXCHANGE',
    'SP500':  'S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE',
    'NAS100': 'NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE',
    'US30':   'DOW JONES INDUSTRIAL AVG- x $5 - CHICAGO BOARD OF TRADE',
}
DISAGG_MARKETS = {
    'GOLD': 'GOLD - COMMODITY EXCHANGE INC.',
}


def fetch(base_url, market_name, long_col, short_col, oi_col, limit=5000):
    params = {
        '$where': f"market_and_exchange_names = '{market_name}'",
        '$limit': str(limit),
        '$order': 'report_date_as_yyyy_mm_dd ASC',
        '$select': f'report_date_as_yyyy_mm_dd,market_and_exchange_names,{long_col},{short_col},{oi_col}',
    }
    url = base_url + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read().decode('utf-8')
    tmp = '_tmp_cot3.csv'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(data)
    df = pd.read_csv(tmp)
    df.columns = ['date', 'market', 'long', 'short', 'oi']
    return df


def process(instrument, base_url, market_name, long_col, short_col, oi_col):
    print(f'\nFetching {instrument}: "{market_name}"...')
    try:
        df = fetch(base_url, market_name, long_col, short_col, oi_col)
    except Exception as e:
        print(f'  FAILED — {e}')
        return None

    if df.empty:
        print(f'  NO ROWS — exact match failed. Contract name may have changed.')
        return None

    unique_markets = df['market'].unique()
    if len(unique_markets) > 1 or unique_markets[0] != market_name:
        print(f'  WARNING: unexpected market name(s) returned: {list(unique_markets)}')
        return None

    df['date'] = pd.to_datetime(df['date'])
    df['net_long'] = df['long'] - df['short']
    df['instrument'] = instrument
    df = df[['date', 'instrument', 'net_long', 'oi']].rename(columns={'oi': 'open_interest'})
    df = df.sort_values('date').reset_index(drop=True)

    gaps = df['date'].diff().dt.days.dropna()
    bad_gaps = gaps[(gaps < 5) | (gaps > 10)]
    if len(bad_gaps) > 0:
        print(f'  WARNING: {len(bad_gaps)} irregular week-to-week gaps (expected ~7 days).')

    print(f'  OK — {len(df)} rows, {df["date"].min().date()} to {df["date"].max().date()}')
    return df


all_frames = []
for inst, market in TFF_MARKETS.items():
    df = process(inst, TFF_URL, market, 'lev_money_positions_long', 'lev_money_positions_short', 'open_interest_all')
    if df is not None: all_frames.append(df)

for inst, market in DISAGG_MARKETS.items():
    df = process(inst, DISAGG_URL, market, 'm_money_positions_long_all', 'm_money_positions_short_all', 'open_interest_all')
    if df is not None: all_frames.append(df)

if not all_frames:
    print('\nERROR: no instruments loaded successfully.')
else:
    cot = pd.concat(all_frames).sort_values(['instrument', 'date'])

    frames = []
    for inst, grp in cot.groupby('instrument'):
        grp = grp.sort_values('date').reset_index(drop=True)
        roll_mean = grp['net_long'].rolling(52, min_periods=10).mean()
        roll_std  = grp['net_long'].rolling(52, min_periods=10).std().replace(0, pd.NA)
        grp['z52'] = (grp['net_long'] - roll_mean) / roll_std
        frames.append(grp)
    cot = pd.concat(frames).sort_values(['instrument', 'date'])

    cot.to_csv('COT_weekly_final.csv', index=False)
    print(f'\nSaved COT_weekly_final.csv ({len(cot):,} rows)')
    print('\nFinal coverage:')
    for inst, grp in cot.groupby('instrument'):
        print(f'  {inst:<8} {grp["date"].min().date()} to {grp["date"].max().date()}  ({len(grp)} weeks)')
    missing = set(TFF_MARKETS) | set(DISAGG_MARKETS)
    missing -= set(cot['instrument'].unique())
    if missing:
        print(f'\nMISSING (failed to load): {missing}')
