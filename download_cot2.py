"""
download_cot2.py

Replaces download_cot.py — that script's dates were found to be corrupted:
a systematic -7-year shift (2017 data appearing as 2010, 2018 as 2011,
etc.), affecting 575 of 1400 rows (41%), traced to its fragile 5-format
date-guessing logic on the legacy CFTC ZIP files. Worse, that bug could
just as easily shift 2024-2026 data INTO the 2017-2019 range, where it
would look completely normal and go undetected — not something worth
patching, worth replacing.

This pulls the same "Traders in Financial Futures" report via the CFTC's
Socrata API instead, which returns report_date_as_yyyy_mm_dd as an
unambiguous ISO date string — no format-guessing, nothing to get wrong.
Confirmed working and returning correct contracts earlier tonight.

Uses "Leveraged Money" positions (this report's modern equivalent of the
old "Non-Commercial"/speculator category).

Covers: EURUSD, GBPUSD, USDJPY, GOLD, SP500, NAS100, US30.
NOT covered: DAX (Eurex-listed, not CFTC-regulated).

Prints every unique market name matched per keyword — if a keyword
matches the wrong contract or more than one, that's visible immediately,
not a silent wrong-data bug like last time.

Run in Codespace: python -u download_cot2.py
"""
import pandas as pd
import urllib.request
import urllib.parse

BASE = 'https://publicreporting.cftc.gov/resource/gpe5-46if.csv'

KEYWORDS = {
    'EURUSD': 'EURO FX -',
    'GBPUSD': 'BRITISH POUND',
    'USDJPY': 'JAPANESE YEN',
    'GOLD':   'GOLD -',
    'SP500':  'S&P 500',
    'NAS100': 'NASDAQ',
    'US30':   'DOW JONES',
}

def fetch(keyword, limit=100000):
    where = f"market_and_exchange_names like '%{keyword}%'"
    params = {
        '$where': where,
        '$limit': str(limit),
        '$order': 'report_date_as_yyyy_mm_dd ASC',
        '$select': 'report_date_as_yyyy_mm_dd,market_and_exchange_names,'
                    'lev_money_positions_long,lev_money_positions_short,open_interest_all',
    }
    url = BASE + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read().decode('utf-8')
    tmp = '_tmp_cot2.csv'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(data)
    return pd.read_csv(tmp)


all_frames = []
for instrument, keyword in KEYWORDS.items():
    print(f'\nFetching {instrument} (keyword: "{keyword}")...')
    try:
        df = fetch(keyword)
    except Exception as e:
        print(f'  FAILED — {e}')
        continue

    if df.empty:
        print(f'  NO ROWS returned for keyword "{keyword}" — check the keyword.')
        continue

    unique_markets = df['market_and_exchange_names'].unique()
    print(f'  {len(df)} rows, unique market names matched:')
    for m in unique_markets:
        n = (df['market_and_exchange_names'] == m).sum()
        print(f'    "{m}"  ({n} rows)')

    if len(unique_markets) > 1:
        print(f'  WARNING: more than one distinct contract matched "{keyword}" — '
              f'narrow the keyword before trusting this.')
        continue

    df['date'] = pd.to_datetime(df['report_date_as_yyyy_mm_dd'])
    df['net_long'] = df['lev_money_positions_long'] - df['lev_money_positions_short']
    df['instrument'] = instrument
    df = df[['date', 'instrument', 'net_long', 'open_interest_all']].sort_values('date')

    # sanity check: dates should be strictly increasing weekly, no impossible jumps
    gaps = df['date'].diff().dt.days.dropna()
    bad_gaps = gaps[(gaps < 5) | (gaps > 10)]
    if len(bad_gaps) > 0:
        print(f'  WARNING: {len(bad_gaps)} irregular week-to-week gaps found (expected ~7 days) — '
              f'inspect before trusting.')

    all_frames.append(df)
    print(f'  OK — {df["date"].min().date()} to {df["date"].max().date()}, {len(df)} weeks')

if not all_frames:
    print('\nERROR: no instruments loaded successfully.')
else:
    cot = pd.concat(all_frames).sort_values(['instrument', 'date'])

    # 52-week rolling z-score, no lookahead beyond the trailing window itself
    frames = []
    for inst, grp in cot.groupby('instrument'):
        grp = grp.sort_values('date').reset_index(drop=True)
        roll_mean = grp['net_long'].rolling(52, min_periods=10).mean()
        roll_std  = grp['net_long'].rolling(52, min_periods=10).std().replace(0, pd.NA)
        grp['z52'] = (grp['net_long'] - roll_mean) / roll_std
        frames.append(grp)
    cot = pd.concat(frames).sort_values(['instrument', 'date'])

    cot.to_csv('COT_weekly_v2.csv', index=False)
    print(f'\nSaved COT_weekly_v2.csv ({len(cot):,} rows)')
    print('\nFinal coverage:')
    for inst, grp in cot.groupby('instrument'):
        print(f'  {inst:<8} {grp["date"].min().date()} to {grp["date"].max().date()}  ({len(grp)} weeks)')
