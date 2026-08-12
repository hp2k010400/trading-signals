"""
download_new.py — Download new instruments from OANDA M1
NatGas | Oil | Silver | GBPJPY | EURJPY | AUDJPY

Run: python download_new.py
"""
import requests, datetime, os, csv, time
from datetime import timezone

API_KEY = 'ea055ce39e9b0153cca72462e497a7a2-a8c2549149b12e3ba71e5d9d500641da'
BASE    = 'https://api-fxtrade.oanda.com'
HEADERS = {'Authorization': f'Bearer {API_KEY}'}

INSTRUMENTS = [
    ('NATGAS', 'NATGAS_USD', 'NATGAS_M1_oanda.csv'),
    ('OIL',    'WTICO_USD',  'OIL_M1_oanda.csv'),
    ('SILVER', 'XAG_USD',    'XAGUSD_M1_oanda.csv'),
    ('GBPJPY', 'GBP_JPY',    'GBPJPY_M1_oanda.csv'),
    ('EURJPY', 'EUR_JPY',    'EURJPY_M1_oanda.csv'),
    ('AUDJPY', 'AUD_JPY',    'AUDJPY_M1_oanda.csv'),
]

START = datetime.datetime(2018, 1, 1, tzinfo=timezone.utc)
END   = datetime.datetime(2026, 7, 19, tzinfo=timezone.utc)

def fetch(instrument, from_dt):
    r = requests.get(f'{BASE}/v3/instruments/{instrument}/candles', headers=HEADERS,
        params={'granularity':'M1','from':from_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'count':5000,'price':'M'}, timeout=30)
    if r.status_code != 200: return None, r.status_code, r.text[:200]
    return r.json().get('candles',[]), 200, ''

def parse(c):
    ts = int(datetime.datetime.strptime(c['time'][:19],'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
    m  = c['mid']
    return (ts, float(m['o']), float(m['h']), float(m['l']), float(m['c']), int(c.get('volume',1)))

def resume_dt(path):
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if len(df)==0: return START
        return datetime.datetime.fromtimestamp(int(df['time'].max()),tz=timezone.utc)+datetime.timedelta(minutes=1)
    except: return START

print('Checking API...')
r = requests.get(f'{BASE}/v3/accounts', headers=HEADERS, timeout=10)
if r.status_code != 200: print(f'API error {r.status_code}'); exit(1)
print('API OK\n')

for name, instrument, out_file in INSTRUMENTS:
    print(f'{name} ({instrument}) -> {out_file}')
    existing = 0
    if os.path.exists(out_file):
        try:
            import pandas as pd
            existing = len(pd.read_csv(out_file))
        except: pass
    if existing > 100:
        cur_dt = resume_dt(out_file)
        if cur_dt >= END: print(f'  Complete — skipping\n'); continue
        print(f'  Resuming from {cur_dt} ({existing:,} bars)')
        f_out = open(out_file,'a',newline='')
        writer = csv.writer(f_out)
    else:
        if os.path.exists(out_file): os.remove(out_file)
        cur_dt = START; existing = 0
        f_out = open(out_file,'w',newline='')
        writer = csv.writer(f_out)
        writer.writerow(['time','open','high','low','close','tick_volume'])

    total = existing; errors = 0; last_pct = -1
    while cur_dt < END:
        candles, status, err = fetch(instrument, cur_dt)
        if candles is None:
            print(f'  HTTP {status}: {err}')
            errors += 1
            if errors > 5: print('  Too many errors, skipping instrument'); break
            time.sleep(3); continue
        if not candles: break
        rows = [parse(c) for c in candles if c.get('complete',True)]
        if rows: writer.writerows(rows); f_out.flush(); total += len(rows)
        last_ts = datetime.datetime.strptime(candles[-1]['time'][:19],'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        cur_dt = last_ts + datetime.timedelta(minutes=1)
        pct = (cur_dt-START).total_seconds()/(END-START).total_seconds()*100
        if int(pct/10) > last_pct:
            last_pct = int(pct/10)
            print(f'  {pct:4.0f}%  bars={total:>8,}  errors={errors}  date={cur_dt.date()}',flush=True)
        time.sleep(0.1)
    f_out.close()
    if total == 0: print(f'  WARNING: 0 bars — {instrument} may not be available on this account')
    else: print(f'  Done: {total:,} bars')
    print()

print('All done.')
