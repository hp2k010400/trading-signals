"""
download_twelvedata.py  -  Fetch M1 index history via Twelve Data API
=====================================================================
Free account: 800 credits/day, no card needed.
Sign up: https://twelvedata.com
API key: Dashboard -> API Keys

Run: python download_twelvedata.py
"""
import requests, datetime, os, csv, time
import pandas as pd
from datetime import timezone

API_KEY = 'PASTE_YOUR_KEY_HERE'
BASE    = 'https://api.twelvedata.com'

INSTRUMENTS = [
    # (name, symbol, exchange, out_file)
    ('DAX',   'DAX',    'XETR', 'GER40_M1_td.csv'),
    ('UK100', 'UK100',  'LSE',  'UK100_M1_td.csv'),
    ('NAS100','NDX',    'NASDAQ','US100_M1_td.csv'),
    ('SP500', 'SPX',    'NYSE', 'US500_M1_td.csv'),
]

START = datetime.datetime(2020, 1, 1, tzinfo=timezone.utc)  # TD free goes ~5 years back
END   = datetime.datetime(2026, 7, 14, tzinfo=timezone.utc)

def fetch_chunk(symbol, exchange, start_dt, end_dt):
    r = requests.get(
        f'{BASE}/time_series',
        params={
            'symbol':     symbol,
            'exchange':   exchange,
            'interval':   '1min',
            'start_date': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'end_date':   end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'outputsize': 5000,
            'order':      'ASC',
            'apikey':     API_KEY,
        },
        timeout=30
    )
    if r.status_code != 200:
        return None, f'HTTP {r.status_code}'
    j = r.json()
    if j.get('status') == 'error':
        return None, j.get('message','unknown error')
    values = j.get('values', [])
    return values, ''

def parse(v):
    dt = datetime.datetime.strptime(v['datetime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    ts = int(dt.timestamp())
    return (ts, float(v['open']), float(v['high']), float(v['low']), float(v['close']), int(float(v.get('volume',1) or 1)))

def file_has_data(path):
    if not os.path.exists(path): return False
    try: return len(pd.read_csv(path, nrows=2)) >= 1
    except: return False

def get_resume_dt(path):
    try:
        df = pd.read_csv(path)
        if len(df) == 0: return START
        last_ts = int(df['time'].max())
        return datetime.datetime.fromtimestamp(last_ts, tz=timezone.utc) + datetime.timedelta(minutes=1)
    except: return START

# ── Check API key ───────────────────────────────────────────────────────────────
print('Checking API key...')
r = requests.get(f'{BASE}/api_usage', params={'apikey': API_KEY}, timeout=10)
if r.status_code == 200:
    j = r.json()
    used  = j.get('current_usage', '?')
    limit = j.get('daily_limit', '?')
    print(f'API key OK  —  {used}/{limit} credits used today\n')
else:
    print(f'API check returned {r.status_code} — continuing anyway\n')

# ── Download ────────────────────────────────────────────────────────────────────
for name, symbol, exchange, out_file in INSTRUMENTS:
    print(f'{name} ({symbol}) -> {out_file}')

    if file_has_data(out_file):
        resume_dt = get_resume_dt(out_file)
        if resume_dt >= END:
            print(f'  Complete -- skipping\n'); continue
        existing = sum(1 for _ in open(out_file)) - 1
        print(f'  Resuming from {resume_dt.date()} ({existing:,} bars)')
    else:
        if os.path.exists(out_file): os.remove(out_file)
        resume_dt = START
        existing  = 0

    f_out  = open(out_file, 'a', newline='')
    writer = csv.writer(f_out)
    if existing == 0:
        writer.writerow(['time','open','high','low','close','tick_volume'])

    cur_dt   = resume_dt
    total    = existing
    errors   = 0
    credits  = 0
    last_pct = -1

    while cur_dt < END:
        chunk_end = min(cur_dt + datetime.timedelta(days=3), END)
        values, err = fetch_chunk(symbol, exchange, cur_dt, chunk_end)
        credits += 1

        if values is None:
            print(f'  Error: {err}')
            errors += 1
            if errors > 5: print('  Too many errors — stopping'); break
            time.sleep(5); continue

        if not values:
            cur_dt = chunk_end
            time.sleep(0.3)
            continue

        rows = [parse(v) for v in values]
        writer.writerows(rows)
        f_out.flush()
        total += len(rows)

        last_ts = datetime.datetime.strptime(values[-1]['datetime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        cur_dt  = last_ts + datetime.timedelta(minutes=1)

        pct = (cur_dt - START).total_seconds() / (END - START).total_seconds() * 100
        if int(pct / 10) > last_pct:
            last_pct = int(pct / 10)
            print(f'  {pct:4.0f}%  bars={total:>8,}  credits_used={credits}  date={cur_dt.date()}', flush=True)

        time.sleep(0.25)  # 4 requests/sec, well under limits

    f_out.close()
    if total == 0:
        print(f'  0 bars — check symbol/exchange for {name}')
    else:
        df_v = pd.read_csv(out_file, nrows=3)
        print(f'  Done: {total:,} bars  sample open={df_v["open"].iloc[0]}')
    print()

print('All done.')
