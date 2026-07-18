"""
download_histdata.py  -  Download M1 history from HistData.com
==============================================================
Gets EURUSD, GBPUSD, XAUUSD M1 data going back to 2018.
Each year is one ~30MB zip, downloads in seconds in a Codespace.
Merges all years into a single CSV matching the M1 format the
backtest scripts already use (Unix timestamp, OHLCV).

Run: python download_histdata.py
"""
import os, zipfile, io, requests, time
import pandas as pd

SYMBOLS = {
    'EURUSD': ('EURUSD', 'EURUSD_M1_full.csv'),
    'GBPUSD': ('GBPUSD', 'GBPUSD_M1_full.csv'),
    'XAUUSD': ('XAUUSD', 'XAUUSD_M1_full.csv'),
}
YEARS   = list(range(2018, 2026))
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer':    'https://www.histdata.com/',
}

def download_year(pair, year):
    """Download one year of M1 data and return a DataFrame."""
    # Step 1: get the token from the page
    page_url = f'https://www.histdata.com/download-free-forex-historical-data/?/metatrader/1-minute-bar-quotes/{pair}/{year}'
    r = requests.get(page_url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        print(f'    page fetch failed ({r.status_code})')
        return None

    # Extract hidden form fields
    from html.parser import HTMLParser
    class FormParser(HTMLParser):
        def __init__(self):
            super().__init__(); self.fields = {}
        def handle_starttag(self, tag, attrs):
            if tag == 'input':
                d = dict(attrs)
                if d.get('type') == 'hidden' and d.get('name'):
                    self.fields[d['name']] = d.get('value','')
    fp = FormParser(); fp.feed(r.text)
    fields = fp.fields
    if not fields:
        print(f'    no form fields found — HistData may have changed structure')
        return None

    # Step 2: POST to download
    post_url = 'https://www.histdata.com/get.php'
    r2 = requests.post(post_url, data=fields, headers={**HEADERS,'Referer': page_url}, timeout=60, stream=True)
    if r2.status_code != 200 or 'zip' not in r2.headers.get('Content-Type',''):
        print(f'    download failed ({r2.status_code})')
        return None

    content = r2.content
    try:
        z = zipfile.ZipFile(io.BytesIO(content))
        # HistData MT4 format: datetime,open,high,low,close,volume
        # datetime format: YYYYMMDD HHMMSS
        csv_name = [n for n in z.namelist() if n.endswith('.csv') or n.endswith('.CSV')]
        if not csv_name:
            print(f'    no CSV in zip')
            return None
        raw = z.read(csv_name[0]).decode('utf-8', errors='ignore')
        df = pd.read_csv(io.StringIO(raw), header=None,
                         names=['datetime','open','high','low','close','volume'])
        df['time'] = pd.to_datetime(df['datetime'].astype(str), format='%Y%m%d %H%M%S', utc=True)
        df = df[['time','open','high','low','close','volume']].rename(columns={'volume':'tick_volume'})
        df = df.set_index('time').sort_index()
        return df
    except Exception as e:
        print(f'    parse error: {e}')
        return None

for sym, (pair, outfile) in SYMBOLS.items():
    print(f'\n{"─"*50}')
    print(f'  {sym} — downloading {len(YEARS)} years...')
    frames = []
    for yr in YEARS:
        print(f'    {yr}...', end=' ', flush=True)
        df = download_year(pair, yr)
        if df is not None:
            print(f'{len(df):,} bars')
            frames.append(df)
        else:
            print('skipped')
        time.sleep(1)  # be polite to the server

    if not frames:
        print(f'  No data downloaded for {sym}')
        continue

    combined = pd.concat(frames).sort_index()
    combined = combined[~combined.index.duplicated(keep='first')]

    # Convert to Unix timestamp format (matches H1 CSVs and existing M1 CSVs)
    out = combined.reset_index()
    out['time'] = out['time'].astype('int64') // 10**9
    out.to_csv(outfile, index=False)
    print(f'  Saved {len(out):,} bars → {outfile}')
    print(f'  Range: {combined.index[0]} to {combined.index[-1]}')

print('\nDone. Files ready for backtest_m1_trail_sweep.py')
print('Update CSVSYMS_M1 to point to the _full.csv files.')
