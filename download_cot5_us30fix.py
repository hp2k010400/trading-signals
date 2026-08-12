"""
download_cot5_us30fix.py

Final fix for US30: "DOW JONES INDUSTRIAL AVERAGE" turned out to be an
older, DIFFERENT, discontinued contract (2006-2014), not a later name
for the same one — it overlapped entirely with the existing data and
added nothing past 2022. The actual continuation is "DJIA Consolidated
- CHICAGO BOARD OF TRADE", which matches SP500/NAS100's Consolidated
span exactly (2010-06-15 to 2026-07-28, 842 weeks) — same methodology,
clean single source. Replacing US30 entirely with this rather than
patching fragments together.

Run in Codespace: python -u download_cot5_us30fix.py
"""
import pandas as pd
import urllib.request
import urllib.parse

TFF_URL = 'https://publicreporting.cftc.gov/resource/gpe5-46if.csv'
MARKET_NAME = 'DJIA Consolidated - CHICAGO BOARD OF TRADE'

params = {
    '$where': f"market_and_exchange_names = '{MARKET_NAME}'",
    '$limit': '5000',
    '$order': 'report_date_as_yyyy_mm_dd ASC',
    '$select': 'report_date_as_yyyy_mm_dd,market_and_exchange_names,'
                'lev_money_positions_long,lev_money_positions_short,open_interest_all',
}
url = TFF_URL + '?' + urllib.parse.urlencode(params)
with urllib.request.urlopen(url, timeout=60) as resp:
    data = resp.read().decode('utf-8')
with open('_tmp_cot5.csv', 'w', encoding='utf-8') as f:
    f.write(data)
df = pd.read_csv('_tmp_cot5.csv')
df.columns = ['date', 'market', 'long', 'short', 'oi']
df['date'] = pd.to_datetime(df['date'])

if df.empty or df['market'].nunique() != 1 or df['market'].iloc[0] != MARKET_NAME:
    print(f'FAILED — unexpected result: {df["market"].unique() if not df.empty else "empty"}')
else:
    df['net_long'] = df['long'] - df['short']
    df['instrument'] = 'US30'
    df = df[['date', 'instrument', 'net_long', 'oi']].rename(columns={'oi': 'open_interest'}).sort_values('date')

    roll_mean = df['net_long'].rolling(52, min_periods=10).mean()
    roll_std  = df['net_long'].rolling(52, min_periods=10).std().replace(0, pd.NA)
    df['z52'] = (df['net_long'] - roll_mean) / roll_std

    existing = pd.read_csv('COT_weekly_final.csv', parse_dates=['date'])
    existing = existing[existing['instrument'] != 'US30']
    existing = pd.concat([existing, df]).sort_values(['instrument', 'date'])
    existing.to_csv('COT_weekly_final.csv', index=False)
    print(f'US30 replaced: {len(df)} rows, {df["date"].min().date()} to {df["date"].max().date()}')

print('\nFinal coverage:')
final = pd.read_csv('COT_weekly_final.csv', parse_dates=['date'])
for inst, grp in final.groupby('instrument'):
    print(f'  {inst:<8} {grp["date"].min().date()} to {grp["date"].max().date()}  ({len(grp)} weeks)')
