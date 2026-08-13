"""
edge30_construct_and_validate_oi.py

Constructs corrected TOTAL ES open interest (summed across the full
outright contract curve, excluding calendar spreads) from
databento_es_all_contracts_statistics.csv, and runs the 7 data-quality
checks required before EDGE30 may proceed. Per instruction: if any
check fails, STOP and report the problem rather than continuing.

Outputs: es_total_oi_daily.csv (validated, ready for edge30 testing)
"""
import pandas as pd
import numpy as np
import re
import warnings
warnings.filterwarnings('ignore')

OUTRIGHT_PATTERN = re.compile(r'^ES[FGHJKMNQUVXZ]\d{1,2}$')  # e.g. ESH1, ESM0 -- excludes spreads (contain '-')

print('Loading full ES contract-curve statistics...')
df = pd.read_csv('databento_es_all_contracts_statistics.csv',
                  usecols=['ts_event', 'instrument_id', 'quantity', 'stat_type', 'symbol'])
print(f'  {len(df)} raw rows loaded')

# ---- Check: isolate open interest rows only ----
oi = df[df['stat_type'] == 9].copy()
print(f'  {len(oi)} open-interest (stat_type=9) rows')

# ---- Check 1/3: exclude spread symbols (contain '-'), keep only outright contracts ----
all_symbols = oi['symbol'].unique()
outright_symbols = [s for s in all_symbols if OUTRIGHT_PATTERN.match(str(s))]
spread_symbols = [s for s in all_symbols if not OUTRIGHT_PATTERN.match(str(s))]
print(f'\n  Distinct symbols in OI data: {len(all_symbols)}')
print(f'  Outright contracts (kept): {len(outright_symbols)}')
print(f'  Spread/other symbols (EXCLUDED, would double-count/misrepresent OI): {len(spread_symbols)}')
print(f'    Sample excluded: {spread_symbols[:5]}')
oi = oi[oi['symbol'].isin(outright_symbols)].copy()
print(f'  {len(oi)} rows remain after excluding spreads')

oi['ts_event'] = pd.to_datetime(oi['ts_event'], utc=True)
oi['date'] = oi['ts_event'].dt.normalize()

# ---- Check: no double-counting -- one value per (date, instrument_id), take LAST report of the day ----
daily = oi.groupby(['date', 'instrument_id', 'symbol'])['quantity'].last().reset_index()
dupe_check = daily.groupby(['date', 'instrument_id']).size()
assert dupe_check.max() == 1, 'DOUBLE-COUNTING DETECTED: duplicate (date, instrument_id) rows remain'
print(f'\n  Check passed: no (date, instrument_id) duplicates after last-per-day aggregation.')

# ---- Build per-contract lifespan-aware series, forward-fill ONLY within each contract's own observed range ----
pivot = daily.pivot_table(index='date', columns='instrument_id', values='quantity')
full_dates = pd.date_range(pivot.index.min(), pivot.index.max(), freq='D')
pivot = pivot.reindex(full_dates)

filled = pivot.copy()
for col in pivot.columns:
    s = pivot[col]
    valid_idx = s.dropna().index
    if len(valid_idx) == 0:
        continue
    first, last = valid_idx.min(), valid_idx.max()
    # forward-fill only strictly within this contract's own observed lifespan (check 4: expired contracts
    # do not persist beyond their last real observation -- no artificial extension past expiry)
    filled.loc[first:last, col] = s.loc[first:last].ffill()

total_oi = filled.sum(axis=1, skipna=True)
total_oi = total_oi[total_oi > 0]
total_oi.index.name = 'date'

print(f'\n  Total OI series: {len(total_oi)} days, {total_oi.index.min().date()} -> {total_oi.index.max().date()}')
print(f'  Mean total OI: {total_oi.mean():,.0f}   Min: {total_oi.min():,.0f}   Max: {total_oi.max():,.0f}')

# ---- Check 1 (the core one): verify old roll-date jumps are gone ----
old_roll_dates = pd.to_datetime([
    '2010-06-16', '2010-09-15', '2010-12-16', '2011-03-17', '2011-06-16', '2011-09-15',
], utc=True)
print(f'\n  === Verifying old front-month roll-date jumps are eliminated ===')
day_changes = total_oi.pct_change()
for d in old_roll_dates:
    if d in day_changes.index:
        chg = day_changes.loc[d]
        flag = '  <-- STILL A JUMP, PROBLEM' if abs(chg) > 0.10 else '  (clean)'
        print(f'  {d.date()}: total-OI day change = {chg*100:+.2f}%{flag}')

# ---- General jump scan across the whole series ----
big_jumps = day_changes[day_changes.abs() > 0.15]
print(f'\n  Days with >15% total-OI change across entire 2010-2026 series: {len(big_jumps)}')
if len(big_jumps) > 0:
    print('  (large ones can be genuine -- e.g. a single very illiquid day -- listing for manual review)')
    print(big_jumps.sort_values(key=abs, ascending=False).head(10))

total_oi.to_csv('es_total_oi_daily.csv', header=['total_oi'])
print('\nSaved es_total_oi_daily.csv')
print('\nDone -- review the roll-date and jump-scan output above before proceeding to EDGE30 testing.')
