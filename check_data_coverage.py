"""
check_data_coverage.py

Quick diagnostic: for every FTMO M1 CSV we have, print the real date
range and bar count, broker-UTC-corrected. Answers "how much data do
we actually have for X" directly instead of guessing from strategy
walk-forward output.

Run in Codespace: python -u check_data_coverage.py
"""
import pandas as pd
import os, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

FILES = {
    'GER40 (DAX)':  'GER40_M1_ftmo.csv',
    'US100 (NAS)':  'US100_M1_ftmo.csv',
    'US500 (SP)':   'US500_M1_ftmo.csv',
    'US30':         'US30_M1_ftmo.csv',
    'EURUSD':       'EURUSD_M1_ftmo.csv',
    'GBPUSD':       'GBPUSD_M1_ftmo.csv',
    'USDJPY':       'USDJPY_M1_ftmo.csv',
    'GOLD (XAUUSD)':'XAUUSD_M1_ftmo.csv',
    'NATGAS':       'NATGAS_cash_M1_ftmo.csv',
    'UK100':        'UK100_cash_M1_ftmo.csv',
    'AUDNZD':       'AUDNZD_M1_ftmo.csv',
    'AUDCAD':       'AUDCAD_M1_ftmo.csv',
    'AUDCHF':       'AUDCHF_M1_ftmo.csv',
    'USDCHF':       'USDCHF_M1_ftmo.csv',
    'USDCAD':       'USDCAD_M1_ftmo.csv',
}

print(f'{"Instrument":<16} {"File":<28} {"First date":<12} {"Last date":<12} {"Span (days)":<12} {"Bars":>10}')
print('-' * 96)
for name, fn in FILES.items():
    if not os.path.exists(fn):
        print(f'{name:<16} {fn:<28} MISSING')
        continue
    df = pd.read_csv(fn, on_bad_lines='skip')
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.dropna(subset=['time']).sort_values('time')
    if len(df) == 0:
        print(f'{name:<16} {fn:<28} EMPTY')
        continue
    first = df['time'].iloc[0]
    last = df['time'].iloc[-1]
    span_days = (last - first).days
    print(f'{name:<16} {fn:<28} {str(first.date()):<12} {str(last.date()):<12} {span_days:<12} {len(df):>10}')

print('\nDone.')
