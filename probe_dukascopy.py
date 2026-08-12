"""
probe_dukascopy.py  -  Test which Dukascopy CDN symbols return data
Run: python probe_dukascopy.py
"""
import requests, lzma, gzip, struct, numpy as np

CDN_FX   = 'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5'
CDN_TICK = 'https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5'

# Test date: 2023-06-07 (Wednesday, known trading day)
Y, M, D, H = 2023, 5, 7, 10   # month is 0-indexed for CDN

# Symbol candidates to probe
CANDIDATES = [
    # DAX variants
    'DE30EUR', 'GER30EUR', 'GER30', 'GER40EUR', 'GER40', 'GRXEUR',
    'DAX', 'DAX30', 'GER30GBP',
    # UK100 variants
    'UK100GBP', 'UK100', 'UKXGBP', 'UKX',
    # NAS100 variants
    'NAS100USD', 'NAS100', 'NASUSDUSD', 'NDX', 'USNAS100',
    # SP500 variants
    'SPX500USD', 'SPX500', 'SPX', 'US500',
]

def try_candles(sym):
    url = CDN_FX.format(sym=sym, y=Y, m=M, d=D)
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return f'HTTP {r.status_code}'
        if len(r.content) < 10: return f'empty ({len(r.content)} bytes)'
        raw = lzma.decompress(r.content)
        n = len(raw) // 24
        if n == 0: return 'decompressed but 0 bars'
        ms, o, h, l, c, vol = struct.unpack('>IIIIIf', raw[:24])
        return f'OK  {n} bars  open={o}'
    except lzma.LZMAError:
        return f'not LZMA ({len(r.content)} bytes content-type={r.headers.get("Content-Type","?")})'
    except Exception as e:
        return f'ERROR {e}'

def try_ticks(sym):
    url = CDN_TICK.format(sym=sym, y=Y, m=M, d=D, h=H)
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200: return f'HTTP {r.status_code}'
        if len(r.content) < 20: return f'empty ({len(r.content)} bytes)'
        data = gzip.decompress(r.content)
        n = len(data) // 20
        if n == 0: return 'decompressed but 0 ticks'
        ticks = np.frombuffer(data[:20], dtype='>u4')
        return f'OK  {n} ticks  ask={ticks[1]}'
    except gzip.BadGzipFile:
        return f'not gzip ({len(r.content)} bytes)'
    except Exception as e:
        return f'ERROR {e}'

print(f'Probing Dukascopy CDN — date 2023-06-07 hour {H}:00\n')
print(f'{"Symbol":<16}  {"Candles":<45}  Ticks')
print('─' * 100)

for sym in CANDIDATES:
    c = try_candles(sym)
    t = try_ticks(sym)
    marker = '  ◄ WORKS' if c.startswith('OK') or t.startswith('OK') else ''
    print(f'{sym:<16}  {c:<45}  {t}{marker}')

print('\nDone.')
