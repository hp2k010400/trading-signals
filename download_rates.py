"""
download_rates.py

Pulls central bank policy rate history from FRED for the FX carry test.
Carry only applies cleanly to the 3 FX pairs in our instrument set —
EURUSD, GBPUSD, USDJPY — not the indices or gold, since those don't have
an interest-rate-differential carry mechanism in the same sense.

SERIES IDs BELOW ARE BEST-CONFIDENCE, NOT VERIFIED — I could not reach
FRED directly to confirm them (blocked, 403). FEDFUNDS is very likely
correct (one of FRED's most standard series). The others are plausible
but unconfirmed. This script deliberately does NOT silently continue if
a series fails — pandas_datareader raises a clear error for an invalid
FRED series ID, so a wrong code here fails loud, not silent. If any of
these error out, search fred.stlouisfed.org directly for the correct
series (search "ECB deposit rate", "Bank of England bank rate", "Japan
policy rate") and paste back the working ID.

Run in Codespace: pip install pandas-datareader && python -u download_rates.py
"""
import pandas_datareader.data as web
import pandas as pd
import datetime

START = datetime.datetime(2017, 1, 1)
END   = datetime.datetime(2026, 8, 2)

SERIES = {
    'USD': 'FEDFUNDS',          # US Federal Funds Rate — high confidence
    'EUR': 'ECBDFR',            # ECB Deposit Facility Rate — medium confidence
    'GBP': 'IR3TIB01GBM156N',   # OECD 3-month interbank rate, UK — medium confidence
    'JPY': 'IR3TIB01JPM156N',   # OECD 3-month interbank rate, Japan — medium confidence
}

results = {}
for ccy, series_id in SERIES.items():
    print(f'Fetching {ccy} ({series_id})...', end=' ')
    try:
        df = web.DataReader(series_id, 'fred', START, END)
        df.to_csv(f'rate_{ccy}.csv')
        print(f'OK — {len(df)} rows, {df.index.min().date()} -> {df.index.max().date()}, '
              f'latest value: {df.iloc[-1, 0]}')
        results[ccy] = 'OK'
    except Exception as e:
        print(f'FAILED — {e}')
        results[ccy] = 'FAILED'

print('\nSummary:')
for ccy, status in results.items():
    print(f'  {ccy}: {status}')

failed = [c for c, s in results.items() if s == 'FAILED']
if failed:
    print(f'\n{len(failed)} series failed: {failed}')
    print('Search fred.stlouisfed.org directly for the correct series ID for these and report back.')
else:
    print('\nAll 4 rate series downloaded. Ready to build the carry signal next.')
