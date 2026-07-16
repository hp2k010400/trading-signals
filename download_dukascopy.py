"""
download_dukascopy.py  -  Fetch M1 history from Dukascopy CDN
=============================================================
Free historical M1 data for all 7 instruments, 2018-2026.
Price scaling: FX x100000, Indices x1000 (auto-validated).

Run:  python download_dukascopy.py
Time: ~30-60 minutes depending on connection speed.

Output files:
  EURUSD_M1_duka.csv, GBPUSD_M1_duka.csv, GER40_M1_duka.csv,
  UK100_M1_duka.csv, US100_M1_duka.csv, US500_M1_duka.csv, XAUUSD_M1_duka.csv
"""
import requests, struct, lzma, datetime, pandas as pd, os, time, sys
from datetime import timezone

# (local_name, dukascopy_symbol, output_file, price_scale)
# FX:      prices stored as integer x100000  (EURUSD 1.0500 -> 105000)
# Indices: prices stored as integer x1000    (DAX 12000   -> 12000000)
# XAUUSD:  same as FX x100000               (Gold 1800   -> 180000000)
INSTRUMENTS = [
    ('EURUSD', 'EURUSD',    'EURUSD_M1_duka.csv',  100_000),
    ('GBPUSD', 'GBPUSD',    'GBPUSD_M1_duka.csv',  100_000),
    ('DAX',    'DE30EUR',   'GER40_M1_duka.csv',   1_000),
    ('UK100',  'UK100GBP',  'UK100_M1_duka.csv',   1_000),
    ('NAS100', 'NAS100USD', 'US100_M1_duka.csv',   1_000),
    ('SP500',  'SPX500USD', 'US500_M1_duka.csv',   1_000),
    ('GOLD',   'XAUUSD',    'XAUUSD_M1_duka.csv',  100_000),
]

CDN = 'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5'
START = datetime.date(2018, 1, 1)
END   = datetime.date(2026, 7, 14)

# Expected price ranges for validation
EXPECTED = {
    'EURUSD': (0.9, 1.5),   'GBPUSD': (1.0, 1.8),
    'DAX':    (8000, 22000), 'UK100':  (5000, 9000),
    'NAS100': (5000, 22000), 'SP500':  (2000, 6000),
    'GOLD':   (1000, 2700),
}

def fetch_day(duka_sym, scale, date):
    url = CDN.format(sym=duka_sym, y=date.year, m=date.month - 1, d=date.day)
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200 or len(r.content) < 10:
            return []
        raw = lzma.decompress(r.content)
    except Exception:
        return []

    midnight_ts = int(datetime.datetime(
        date.year, date.month, date.day, tzinfo=timezone.utc).timestamp())
    n = len(raw) // 24
    rows = []
    for i in range(n):
        chunk = raw[i*24:(i+1)*24]
        ms, o, h, l, c, vol = struct.unpack('>IIIIIf', chunk)
        if o == 0: continue
        t = midnight_ts + ms // 1000
        rows.append((t, o/scale, h/scale, l/scale, c/scale, max(1, int(vol))))
    return rows

def validate(local_sym, df):
    lo, hi = EXPECTED[local_sym]
    sample_open = df['open'].dropna().iloc[0] if len(df) > 0 else 0
    if not (lo <= sample_open <= hi):
        print(f'  WARNING: sample open {sample_open:.2f} outside expected range {lo}-{hi}')
        print(f'  The price scale may be wrong for this instrument.')
        return False
    return True

total_instruments = len(INSTRUMENTS)
for idx, (local_sym, duka_sym, out_file, scale) in enumerate(INSTRUMENTS, 1):
    print(f'\n[{idx}/{total_instruments}] {local_sym} ({duka_sym}) -> {out_file}')

    if os.path.exists(out_file):
        df_check = pd.read_csv(out_file, nrows=5)
        print(f'  Already exists ({os.path.getsize(out_file)//1024:,} KB) -- skipping')
        continue

    all_rows = []
    d = START
    total_days = (END - START).days
    done = 0
    errors = 0
    last_print = 0

    while d <= END:
        if d.weekday() < 5:  # Mon-Fri only
            rows = fetch_day(duka_sym, scale, d)
            if rows:
                all_rows.extend(rows)
            else:
                errors += 1
        d += datetime.timedelta(days=1)
        done += 1

        pct = done / total_days * 100
        if pct - last_print >= 10:
            last_print = int(pct // 10) * 10
            print(f'  {pct:4.0f}%  bars={len(all_rows):>8,}  errors={errors}', flush=True)

        time.sleep(0.02)

    if not all_rows:
        print(f'  ERROR: No data returned. Check that "{duka_sym}" is the correct Dukascopy symbol.')
        print(f'  Common alternatives: GER30 (old DAX), DE40EUR (new DAX), USNAS100 (NAS)')
        continue

    df = pd.DataFrame(all_rows, columns=['time','open','high','low','close','tick_volume'])
    df = df.sort_values('time').drop_duplicates('time').reset_index(drop=True)

    ok = validate(local_sym, df)
    df.to_csv(out_file, index=False)
    status = 'OK' if ok else 'CHECK PRICES'
    print(f'  {status}  {len(df):,} bars saved  price range: {df.open.min():.2f}-{df.open.max():.2f}')

print('\n\nAll downloads complete.')
print('Run backtest_v4_m1.py to get the accurate M1 backtest results.')
