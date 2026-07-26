"""
download_recent.py  —  Top up all 9 strategy M1 CSVs to today.

Resumes from last bar in each CSV, so safe to re-run if interrupted.
Uses same OANDA API key as download_oanda.py.

Run: python -u download_recent.py
"""
import requests, datetime, os, csv, time
from datetime import timezone

API_KEY = 'ea055ce39e9b0153cca72462e497a7a2-a8c2549149b12e3ba71e5d9d500641da'
BASE    = 'https://api-fxtrade.oanda.com'
HEADERS = {'Authorization': f'Bearer {API_KEY}'}

# All 9 strategy instruments
INSTRUMENTS = [
    ('GER40',  'DE30_EUR',   'GER40_M1_oanda.csv'),
    ('NAS100', 'NAS100_USD', 'US100_M1_oanda.csv'),
    ('SP500',  'SPX500_USD', 'US500_M1_oanda.csv'),
    ('US30',   'US30_USD',   'US30_M1_oanda.csv'),
    ('EURUSD', 'EUR_USD',    'EURUSD_M1_oanda.csv'),
    ('GBPUSD', 'GBP_USD',    'GBPUSD_M1_oanda.csv'),
    ('USDJPY', 'USD_JPY',    'USDJPY_M1_oanda.csv'),
    ('GOLD',   'XAU_USD',    'XAUUSD_M1_oanda.csv'),
    ('NATGAS', 'NATGAS_USD', 'NATGAS_M1_oanda.csv'),
]

DOWNLOAD_START = datetime.datetime(2018, 1, 1, tzinfo=timezone.utc)
END = datetime.datetime.now(timezone.utc) - datetime.timedelta(minutes=5)

def get_resume_dt(path):
    import pandas as pd
    try:
        df = pd.read_csv(path)
        if len(df) == 0: return DOWNLOAD_START
        last_ts = int(df['time'].max())
        return datetime.datetime.fromtimestamp(last_ts, tz=timezone.utc) + datetime.timedelta(minutes=1)
    except:
        return DOWNLOAD_START

def fetch_chunk(instrument, from_dt):
    r = requests.get(
        f'{BASE}/v3/instruments/{instrument}/candles',
        headers=HEADERS,
        params={'granularity':'M1','from':from_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),'count':5000,'price':'M'},
        timeout=30
    )
    if r.status_code != 200:
        return None, r.status_code, r.text[:200]
    return r.json().get('candles', []), 200, ''

def parse(c):
    ts = int(datetime.datetime.strptime(c['time'][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
    m  = c['mid']
    return (ts, float(m['o']), float(m['h']), float(m['l']), float(m['c']), int(c.get('volume',1)))

print('Checking API...')
r = requests.get(f'{BASE}/v3/accounts', headers=HEADERS, timeout=10)
if r.status_code != 200:
    print(f'API error {r.status_code}: {r.text[:200]}'); exit(1)
print('OK\n')

for name, oanda_id, out_file in INSTRUMENTS:
    if not os.path.exists(out_file):
        print(f'{name}: file not found — skipping (run download_oanda.py first for full history)')
        continue

    resume_dt = get_resume_dt(out_file)
    if resume_dt >= END:
        print(f'{name}: already up to date ({resume_dt.date()})')
        continue

    days_to_fetch = (END - resume_dt).days
    print(f'{name}: resuming from {resume_dt.date()} (~{days_to_fetch} days)')

    cur_dt  = resume_dt
    added   = 0
    errors  = 0
    tried_alt = False

    with open(out_file, 'a', newline='') as f:
        writer = csv.writer(f)
        while cur_dt < END:
            candles, status, err = fetch_chunk(oanda_id, cur_dt)
            if candles is None:
                if status == 400 and 'INVALID_INSTRUMENT' in err and not tried_alt:
                    alt = oanda_id.replace('DE30', 'DE40')
                    print(f'  Trying {alt}...')
                    oanda_id = alt; tried_alt = True; continue
                errors += 1
                if errors > 5: print(f'  Too many errors, skipping {name}'); break
                time.sleep(2); continue

            if not candles: break
            rows = [parse(c) for c in candles if c.get('complete', True)]
            if rows:
                writer.writerows(rows)
                f.flush()
                added += len(rows)

            last = datetime.datetime.strptime(candles[-1]['time'][:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
            cur_dt = last + datetime.timedelta(minutes=1)
            time.sleep(0.1)

    print(f'  Added {added:,} bars up to {cur_dt.date()}\n')

print('Done. All CSVs updated.')
print('Now run: python -u check_live_trades.py')
