"""
edge30_discontinuity_calendar.py

Builds the objective, metadata-only calendar of OI reporting
discontinuities (Option A, frozen construction rule) and identifies
which EDGE30 signal observations must be excluded because their
21-trading-day OI-change measurement window spans one of these dates.

Rule (frozen before any performance is examined):
  - Discontinuity date for a contract = the first date in the total-OI
    index AFTER that contract's own last reported date (i.e. the date
    on which the total sum stops including a contract that had real,
    valid, non-extrapolated data through its own last report).
  - This is derived purely from each contract's own reporting history
    (objective metadata), not from OI magnitude, not from price/return
    outcomes.
  - Any EDGE30 signal whose OI-change window [date - 21 trading days,
    date] contains one or more discontinuity dates is EXCLUDED as a
    data-quality matter, not a performance filter.

No OI values are interpolated, decayed, extrapolated, or removed from
valid pre-expiry observations. The underlying total-OI series (already
built and saved as es_total_oi_daily.csv) is used completely unchanged.
"""
import pandas as pd
import numpy as np
import re
import warnings
warnings.filterwarnings('ignore')

OUTRIGHT_PATTERN = re.compile(r'^ES[FGHJKMNQUVXZ]\d{1,2}$')
OI_CHANGE_DAYS = 21

print('Loading raw per-contract OI data (same source as the frozen total-OI series)...')
df = pd.read_csv('databento_es_all_contracts_statistics.csv', usecols=['ts_event', 'instrument_id', 'quantity', 'stat_type', 'symbol'])
oi = df[df['stat_type'] == 9].copy()
oi = oi[oi['symbol'].apply(lambda s: bool(OUTRIGHT_PATTERN.match(str(s))))]
oi['ts_event'] = pd.to_datetime(oi['ts_event'], utc=True)
oi['date'] = oi['ts_event'].dt.normalize()

# Objective metadata: each contract's own last reported date
last_obs = oi.groupby('instrument_id').agg(last_date=('date', 'max'), symbol=('symbol', 'last'),
                                            last_oi=('quantity', 'last')).reset_index()
last_obs = last_obs.sort_values('last_date').reset_index(drop=True)
print(f'  {len(last_obs)} outright contracts identified')

total_oi = pd.read_csv('es_total_oi_daily.csv', parse_dates=['date'])
total_oi['date'] = pd.to_datetime(total_oi['date'], utc=True)
total_dates = total_oi['date'].sort_values().reset_index(drop=True)

# Discontinuity date = first total-OI-series date strictly after the contract's own last report
discontinuities = []
for _, r in last_obs.iterrows():
    later = total_dates[total_dates > r['last_date']]
    if len(later) == 0:
        continue
    disc_date = later.iloc[0]
    discontinuities.append({'instrument_id': r['instrument_id'], 'symbol': r['symbol'],
                             'last_report_date': r['last_date'], 'discontinuity_date': disc_date,
                             'oi_at_last_report': r['last_oi']})

disc_df = pd.DataFrame(discontinuities).sort_values('discontinuity_date').reset_index(drop=True)
disc_df = disc_df.drop_duplicates(subset=['discontinuity_date'])  # multiple thin contracts can share a date
print(f'  {len(disc_df)} distinct discontinuity dates identified (objective, metadata-only)')

# Sanity check: are these on the expected quarterly expiry calendar (3rd-Friday-adjacent, Mar/Jun/Sep/Dec)?
disc_df['month'] = disc_df['discontinuity_date'].dt.month
disc_df['expected_quarterly'] = disc_df['month'].isin([3, 6, 9, 12])
print(f'\n  Discontinuities landing in the expected quarterly expiry months (Mar/Jun/Sep/Dec): '
      f'{disc_df["expected_quarterly"].sum()} / {len(disc_df)}')
n_year = disc_df['discontinuity_date'].dt.year.nunique()
print(f'  Average per year: {len(disc_df) / n_year:.1f}  (expect ~4/year for a quarterly-expiry contract)')

disc_df.to_csv('edge30_discontinuity_calendar.csv', index=False)
print('\nSaved edge30_discontinuity_calendar.csv')
print('\nFull calendar (only discontinuities with meaningful residual OI at last report, >100k contracts, shown):')
print(disc_df[disc_df['oi_at_last_report'] > 100000][['discontinuity_date', 'symbol', 'last_report_date', 'oi_at_last_report']].to_string(index=False))
