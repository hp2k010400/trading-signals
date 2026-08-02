"""
download_oanda.py  -  Fetch M1 index history via OANDA v20 API
==============================================================
Requires a free OANDA practice account.
Sign up: https://www.oanda.com/register/
API key: My Account -> Manage API Access -> Generate Token

Run: python download_oanda.py
"""
import requests, datetime, os, csv, time
from datetime import timezone

API_KEY = 'ea055ce39e9b0153cca72462e497a7a2-a8c2549149b12e3ba71e5d9d500641da'

BASE    = 'https://api-fxtrade.oanda.com'
HEADERS = {'Authorization': f'Bearer {API_KEY}'}

INSTRUMENTS = [
    # (name, oanda_instrument, out_file) — full 9-instrument research universe.
    # Names/out_files match download_recent.py exactly so top-ups stay consistent.
    ('DAX',    'DE30_EUR',   'GER40_M1_oanda.csv'),
    ('UK100',  'UK100_GBP',  'UK100_M1_oanda.csv'),
    ('NAS100', 'NAS100_USD', 'US100_M1_oanda.csv'),
    ('SP500',  'SPX500_USD', 'US500_M1_oanda.csv'),
    ('US30',   'US30_USD',   'US30_M1_oanda.csv'),
    ('EURUSD', 'EUR_USD',    'EURUSD_M1_oanda.csv'),
    ('GBPUSD', 'GBP_USD',    'GBPUSD_M1_oanda.csv'),
    ('USDJPY', 'USD_JPY',    'USDJPY_M1_oanda.csv'),
    ('GOLD',   'XAU_USD',    'XAUUSD_M1_oanda.csv'),
    ('NATGAS', 'NATGAS_USD', 'NATGAS_M1_oanda.csv'),
]

START = datetime.datetime(2018, 1, 1, tzinfo=timezone.utc)
END   = datetime.datetime(2026, 7, 14, tzinfo=timezone.utc)

def fetch_chunk(instrument, from_dt):
    r = requests.get(
        f'{BASE}/v3/instruments/{instrument}/candles',
        headers=HEADERS,
        params={'granularity':'M1','from':from_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),'count':5000,'price':'M'},
        timeout=30
    )
    if r.status_code != 200:
        return None, r.status_code, r.text[:200]
    candles = r.json().get('candles', [])
    return candles, 200, ''

def parse(c):
    ts = int(datetime.datetime.strptime(c['time'][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
    m  = c['mid']
    return (ts, float(m['o']), float(m['h']), float(m['l']), float(m['c']), int(c.get('volume',1)))

def file_has_data(path):
    if not os.path.exists(path): return False
    try:
        import pandas as pd
        return len(pd.read_csv(path, nrows=2)) >= 1
    except: return False

def get_resume_dt(path):
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if len(df) == 0: return START
        last_ts = int(df['time'].max())
        return datetime.datetime.fromtimestamp(last_ts, tz=timezone.utc) + datetime.timedelta(minutes=1)
    except: return START

# ── Verify API key works ────────────────────────────────────────────────────────
print('Checking API connection...')
r = requests.get(f'{BASE}/v3/accounts', headers=HEADERS, timeout=10)
if r.status_code == 401:
    print('ERROR: Invalid API key. Check PASTE_YOUR_KEY_HERE in this script.')
    exit(1)
elif r.status_code != 200:
    print(f'ERROR: API returned {r.status_code}: {r.text[:200]}')
    exit(1)
print('API key OK\n')

# ── Download each instrument ───────────────────────────────────────────────────
for name, instrument, out_file in INSTRUMENTS:
    print(f'{name} ({instrument}) -> {out_file}')

    if file_has_data(out_file):
        resume_dt  = get_resume_dt(out_file)
        if resume_dt >= END:
            print(f'  Complete -- skipping\n'); continue
        existing = sum(1 for _ in open(out_file)) - 1
        print(f'  Resuming from {resume_dt} ({existing:,} bars)')
    else:
        if os.path.exists(out_file): os.remove(out_file)
        resume_dt = START
        existing  = 0

    f_out  = open(out_file, 'a', newline='')
    writer = csv.writer(f_out)
    if existing == 0:
        writer.writerow(['time','open','high','low','close','tick_volume'])

    cur_dt    = resume_dt
    total     = existing
    errors    = 0
    last_pct  = -1

    while cur_dt < END:
        candles, status, err_text = fetch_chunk(instrument, cur_dt)

        if candles is None:
            print(f'  HTTP {status}: {err_text}')
            if status == 400 and 'INVALID_INSTRUMENT' in err_text:
                print(f'  Instrument {instrument} not found. Trying DE40_EUR...')
                instrument = instrument.replace('DE30', 'DE40')
            errors += 1
            time.sleep(2)
            continue

        if not candles:
            break  # no more data

        rows = [parse(c) for c in candles if c.get('complete', True)]
        if rows:
            writer.writerows(rows)
            f_out.flush()
            total += len(rows)

        last_candle_ts = datetime.datetime.strptime(candles[-1]['time'][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        cur_dt = last_candle_ts + datetime.timedelta(minutes=1)

        pct = (cur_dt - START).total_seconds() / (END - START).total_seconds() * 100
        if int(pct / 10) > last_pct:
            last_pct = int(pct / 10)
            print(f'  {pct:4.0f}%  bars={total:>8,}  errors={errors}  date={cur_dt.date()}', flush=True)

        time.sleep(0.1)  # stay well under rate limit

    f_out.close()

    if total == 0:
        print(f'  ERROR: 0 bars — OANDA may not have M1 history for {instrument}')
    else:
        try:
            import pandas as pd
            df = pd.read_csv(out_file, nrows=5)
            print(f'  Done: {total:,} bars  sample open={df["open"].iloc[0]}')
        except: print(f'  Done: {total:,} bars')
    print()

print('All done.')
