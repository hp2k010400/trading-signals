"""
download_cot4_patch.py

Fixes a gap found in download_cot3_final.py: GBPUSD and US30 both cut
off at exactly 2022-02-01 (817 weeks), while every other instrument
runs to 2026-07-28 (1051 weeks). That's too precise to be a real data
gap — CFTC almost certainly renamed both contracts around early 2022,
and the exact-match query only found the OLD name.

Confirmed by arithmetic: the ambiguous search earlier tonight found a
second GBP contract, "BRITISH POUND - CHICAGO MERCANTILE EXCHANGE"
(234 rows) alongside "BRITISH POUND STERLING" (817 rows).
817 + 234 = 1051 — exactly matching the full span everything else has.
Same likely story for US30 ("DOW JONES INDUSTRIAL AVERAGE", 244 rows).

This fetches both name variants for GBPUSD and US30, concatenates them
(checking for date overlap/duplication at the boundary — if the two
names' date ranges overlap, that's a sign this hypothesis is wrong and
needs a different explanation, not a silent merge), and rebuilds
COT_weekly_final.csv with the corrected full-length series.

Run in Codespace: python -u download_cot4_patch.py
"""
import pandas as pd
import urllib.request
import urllib.parse

TFF_URL = 'https://publicreporting.cftc.gov/resource/gpe5-46if.csv'

# instrument -> list of market names to fetch and concatenate, oldest first
PATCH_MARKETS = {
    'GBPUSD': [
        'BRITISH POUND STERLING - CHICAGO MERCANTILE EXCHANGE',
        'BRITISH POUND - CHICAGO MERCANTILE EXCHANGE',
    ],
    'US30': [
        'DOW JONES INDUSTRIAL AVG- x $5 - CHICAGO BOARD OF TRADE',
        'DOW JONES INDUSTRIAL AVERAGE - CHICAGO BOARD OF TRADE',
    ],
}


def fetch_one(market_name, limit=5000):
    params = {
        '$where': f"market_and_exchange_names = '{market_name}'",
        '$limit': str(limit),
        '$order': 'report_date_as_yyyy_mm_dd ASC',
        '$select': 'report_date_as_yyyy_mm_dd,market_and_exchange_names,'
                    'lev_money_positions_long,lev_money_positions_short,open_interest_all',
    }
    url = TFF_URL + '?' + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read().decode('utf-8')
    tmp = '_tmp_cot4.csv'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(data)
    df = pd.read_csv(tmp)
    if df.empty: return df
    df.columns = ['date', 'market', 'long', 'short', 'oi']
    df['date'] = pd.to_datetime(df['date'])
    return df


for instrument, names in PATCH_MARKETS.items():
    print(f'\n{instrument}:')
    parts = []
    for name in names:
        df = fetch_one(name)
        if df.empty:
            print(f'  "{name}": NO ROWS')
            continue
        print(f'  "{name}": {len(df)} rows, {df["date"].min().date()} to {df["date"].max().date()}')
        parts.append(df)

    if len(parts) < 2:
        print(f'  Only found {len(parts)} variant(s) — cannot patch, leaving as-is.')
        continue

    combined = pd.concat(parts).drop_duplicates(subset='date').sort_values('date')

    # check for overlap between the two name variants — if they overlap heavily,
    # this rename hypothesis is wrong and needs a different explanation
    ranges = [(p['date'].min(), p['date'].max()) for p in parts]
    overlap_days = (min(r[1] for r in ranges) - max(r[0] for r in ranges)).days
    if overlap_days > 14:
        print(f'  WARNING: variants overlap by {overlap_days} days — rename hypothesis may be '
              f'wrong, inspect before trusting the merge.')
    else:
        print(f'  Clean handoff between variants (overlap: {overlap_days} days) — looks like a genuine rename.')

    combined['net_long'] = combined['long'] - combined['short']
    combined['instrument'] = instrument
    combined = combined[['date', 'instrument', 'net_long', 'oi']].rename(columns={'oi': 'open_interest'})
    print(f'  Combined: {len(combined)} rows, {combined["date"].min().date()} to {combined["date"].max().date()}')

    roll_mean = combined['net_long'].rolling(52, min_periods=10).mean()
    roll_std  = combined['net_long'].rolling(52, min_periods=10).std().replace(0, pd.NA)
    combined['z52'] = (combined['net_long'] - roll_mean) / roll_std

    # patch into the existing COT_weekly_final.csv
    existing = pd.read_csv('COT_weekly_final.csv', parse_dates=['date'])
    existing = existing[existing['instrument'] != instrument]
    existing = pd.concat([existing, combined]).sort_values(['instrument', 'date'])
    existing.to_csv('COT_weekly_final.csv', index=False)
    print(f'  Patched into COT_weekly_final.csv')

print('\nDone. Re-check coverage:')
final = pd.read_csv('COT_weekly_final.csv', parse_dates=['date'])
for inst, grp in final.groupby('instrument'):
    print(f'  {inst:<8} {grp["date"].min().date()} to {grp["date"].max().date()}  ({len(grp)} weeks)')
