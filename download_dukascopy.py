"""
download_dukascopy.py  -  Fetch M1 history from Dukascopy CDN
=============================================================
Two download methods:
  FX / Gold  : daily BID_candles_min_1.bi5  (1 file/day, fast)
  Indices    : hourly h_ticks.bi5 resampled to M1 (24 files/day, slower)

Resumable: saves each day immediately. Restart anytime — picks up from
last saved date. Empty/header-only files are treated as not started.

Run:  python download_dukascopy.py
"""
import requests, struct, lzma, gzip, datetime, os, time, csv
import pandas as pd, numpy as np
from datetime import timezone

INSTRUMENTS = [
    # (name, duka_sym, out_file, price_scale, kind)
    ('EURUSD', 'EURUSD',    'EURUSD_M1_duka.csv',  100_000, 'fx'),
    ('GBPUSD', 'GBPUSD',    'GBPUSD_M1_duka.csv',  100_000, 'fx'),
    ('DAX',    'DEUIDXEUR',     'GER40_M1_duka.csv',   1_000,   'idx'),
    ('UK100',  'GBRIDXGBP',    'UK100_M1_duka.csv',   1_000,   'idx'),
    ('NAS100', 'USATECHIDXUSD','US100_M1_duka.csv',   1_000,   'idx'),
    ('SP500',  'USA500IDXUSD', 'US500_M1_duka.csv',   1_000,   'idx'),
    ('GOLD',   'XAUUSD',    'XAUUSD_M1_duka.csv',  100_000, 'fx'),
]

EXPECTED = {
    'EURUSD':(0.9,1.5), 'GBPUSD':(1.0,1.8), 'GOLD':(1000,2700),
    'DAX':(8000,22000),  'UK100':(5000,9000),
    'NAS100':(5000,22000), 'SP500':(2000,6000),
}

START = datetime.date(2018, 1, 1)
END   = datetime.date(2026, 7, 14)

CDN_FX   = 'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5'
CDN_TICK = 'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5'

def fetch_day_fx(sym, scale, date):
    """Download one day of M1 candles for forex/gold. Returns list of rows."""
    url = CDN_FX.format(sym=sym, y=date.year, m=date.month-1, d=date.day)
    try:
        r = requests.get(url, timeout=20)
        if r.status_code != 200 or len(r.content) < 10: return []
        raw = lzma.decompress(r.content)
    except Exception: return []
    midnight = int(datetime.datetime(date.year, date.month, date.day, tzinfo=timezone.utc).timestamp())
    rows = []
    for i in range(len(raw) // 24):
        ms, o, h, l, c, vol = struct.unpack('>IIIIIf', raw[i*24:(i+1)*24])
        if o == 0: continue
        rows.append((midnight + ms//1000, o/scale, h/scale, l/scale, c/scale, max(1,int(vol))))
    return rows

def fetch_day_ticks(sym, scale, date):
    """Download 24 hourly tick files for index instruments, resample to M1."""
    midnight = int(datetime.datetime(date.year, date.month, date.day, tzinfo=timezone.utc).timestamp())
    all_ts, all_mid = [], []
    for h in range(24):
        url = CDN_TICK.format(sym=sym, y=date.year, m=date.month-1, d=date.day, h=h)
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200 or len(r.content) < 20:
                time.sleep(0.02); continue
            data = gzip.decompress(r.content)
            n = len(data) // 20
            if n == 0: time.sleep(0.02); continue
            ticks = np.frombuffer(data[:n*20], dtype='>u4').reshape(n, 5)
            ms  = ticks[:,0].astype(float)
            ask = ticks[:,1].astype(float) / scale
            bid = ticks[:,2].astype(float) / scale
            mid = (ask + bid) / 2.0
            ts  = midnight + h*3600 + ms/1000.0
            all_ts.extend(ts.tolist())
            all_mid.extend(mid.tolist())
        except Exception:
            pass
        time.sleep(0.02)

    if not all_ts: return []

    # Resample to M1
    df = pd.DataFrame({'ts': all_ts, 'mid': all_mid})
    df['min'] = (df['ts'] // 60 * 60).astype(int)
    m1 = df.groupby('min')['mid'].agg(open='first', high='max', low='min', close='last')
    m1['tick_volume'] = df.groupby('min').size()
    m1 = m1.reset_index().rename(columns={'min':'time'})
    return list(m1.itertuples(index=False, name=None))

def file_has_data(path):
    """Return True if file exists and has more than just a header row."""
    if not os.path.exists(path): return False
    try:
        df = pd.read_csv(path, nrows=2)
        return len(df) >= 1
    except Exception:
        return False

def get_resume_date(path):
    """Find the last saved date in a CSV so we can resume from next day."""
    try:
        df = pd.read_csv(path)
        if len(df) == 0: return START
        last_ts = int(df['time'].max())
        last_dt = datetime.datetime.fromtimestamp(last_ts, tz=timezone.utc)
        return last_dt.date() + datetime.timedelta(days=1)
    except Exception:
        return START

# ── Main download loop ─────────────────────────────────────────────────────────
total = len(INSTRUMENTS)
for idx, (name, sym, out_file, scale, kind) in enumerate(INSTRUMENTS, 1):
    print(f'\n[{idx}/{total}] {name} ({sym}) -> {out_file}', flush=True)

    if file_has_data(out_file):
        resume_from = get_resume_date(out_file)
        if resume_from > END:
            sz = os.path.getsize(out_file) // 1024
            print(f'  Complete ({sz:,} KB) -- skipping', flush=True)
            continue
        existing = sum(1 for _ in open(out_file)) - 1  # subtract header
        print(f'  Resuming from {resume_from} ({existing:,} rows saved)', flush=True)
    else:
        # File missing or empty — start fresh
        if os.path.exists(out_file): os.remove(out_file)
        resume_from = START
        existing = 0

    fetch_fn = fetch_day_fx if kind == 'fx' else fetch_day_ticks

    write_header = (existing == 0)
    f_out = open(out_file, 'a', newline='')
    writer = csv.writer(f_out)
    if write_header:
        writer.writerow(['time','open','high','low','close','tick_volume'])

    total_days = (END - START).days
    d = resume_from
    done_days = (resume_from - START).days
    total_bars = existing
    errors = 0
    last_pct = int(done_days / total_days * 100 // 10) * 10

    while d <= END:
        if d.weekday() < 5:
            rows = fetch_fn(sym, scale, d)
            if rows:
                writer.writerows(rows)
                total_bars += len(rows)
            else:
                errors += 1
            f_out.flush()
        d += datetime.timedelta(days=1)
        done_days += 1

        pct = done_days / total_days * 100
        if pct - last_pct >= 10:
            last_pct = int(pct // 10) * 10
            print(f'  {pct:4.0f}%  bars={total_bars:>8,}  errors={errors}  date={d}', flush=True)

    f_out.close()

    if total_bars == 0:
        print(f'  ERROR: 0 bars for {name} ({sym}). Symbol may be wrong.', flush=True)
        print(f'  DAX alternatives: GER30, DE40EUR  |  NAS: USNAS100  |  SP500: SPX500', flush=True)
        continue

    # Quick price validation
    try:
        df_v = pd.read_csv(out_file, nrows=200)
        lo, hi = EXPECTED.get(name, (0, 1e9))
        sample = df_v['open'].dropna().iloc[0]
        status = 'OK' if lo <= sample <= hi else f'WARNING price {sample:.2f} outside {lo}-{hi}'
        sz = os.path.getsize(out_file) // 1024
        print(f'  {status}  {total_bars:,} bars  {sz:,} KB', flush=True)
    except Exception as e:
        print(f'  Saved {total_bars:,} bars (validation error: {e})', flush=True)

print('\nAll downloads complete.', flush=True)
