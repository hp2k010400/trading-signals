"""
download_cot.py  -  Download CFTC COT data for our instruments
==============================================================
CFTC splits COT data across two report types:
  fut_fin_txt    = Financial Traders report → EUR, GBP, SP500, NAS100
  fut_disagg_txt = Disaggregated report     → GOLD

Output: COT_weekly.csv  (date, instrument, net_long, z52)
Run: python download_cot.py
"""
import requests, zipfile, io, pandas as pd, numpy as np, os
YEARS = range(2017, 2027)

# (url_template, {code: instrument_name})
SOURCES = [
    (
        'https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip',
        {'099741': 'EUR', '096742': 'GBP', '13874A': 'SP500', '209742': 'NAS100'},
    ),
    (
        'https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip',
        {'088691': 'GOLD'},
    ),
]

def fetch(url):
    try:
        r = requests.get(url, timeout=60)
        if r.status_code != 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        return pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
    except Exception:
        return None

def find_col(cols, *patterns):
    lo = {c: c.lower() for c in cols}
    for pat in patterns:
        tokens = pat if isinstance(pat, (list, tuple)) else [pat]
        for orig, lc in lo.items():
            if all(t in lc for t in tokens):
                return orig
    return None

def parse_date_series(s, col_name=''):
    for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%m/%d/%Y', '%m/%d/%y', '%d/%m/%Y'):
        try:
            out = pd.to_datetime(s, format=fmt, errors='coerce')
            in_range = ((out >= '2010-01-01') & (out <= '2030-01-01')).sum()
            if out.notna().mean() > 0.8 and in_range / max(len(out), 1) > 0.8:
                return out
        except Exception:
            pass
    sample = list(s.dropna().iloc[:3])
    print(f'      [debug] col="{col_name}" raw sample: {sample}')
    return pd.to_datetime(s, errors='coerce')

def extract(df, market_codes):
    df.columns = [c.strip() for c in df.columns]
    cols = list(df.columns)

    date_col  = find_col(cols, ['as_of_date_in_form_yyyy'], ['as_of_date'])
    code_col  = find_col(cols, ['cftc_contract_market_code'],
                               ['cftc', 'contract', 'market', 'code'])
    long_col  = find_col(cols, ['noncomm_positions_long_all'],
                               ['m_money_positions_long_all'],
                               ['lev_money_positions_long_all'],
                               ['noncomm', 'long_all'],
                               ['m_money', 'long_all'],
                               ['lev_money', 'long_all'])
    short_col = find_col(cols, ['noncomm_positions_short_all'],
                               ['m_money_positions_short_all'],
                               ['lev_money_positions_short_all'],
                               ['noncomm', 'short_all'],
                               ['m_money', 'short_all'],
                               ['lev_money', 'short_all'])

    missing = [n for n, c in [('date', date_col), ('code', code_col),
                               ('nc_long', long_col), ('nc_short', short_col)]
               if c is None]
    if missing:
        relevant = [c for c in cols if any(x in c.lower()
                    for x in ('date','code','cftc','long','short','money','comm'))]
        print(f'      skip — could not map {missing}. Sample cols: {relevant[:10]}')
        return pd.DataFrame()

    out = df[[date_col, code_col, long_col, short_col]].copy()
    out.columns = ['date', 'code', 'nc_long', 'nc_short']
    out['code']    = out['code'].astype(str).str.strip()
    out            = out[out['code'].isin(market_codes)].copy()
    if out.empty:
        return pd.DataFrame()
    out['instrument'] = out['code'].map(market_codes)
    out['date']    = parse_date_series(out['date'].astype(str), date_col)
    out = out[(out['date'] >= '2010-01-01') & (out['date'] <= '2027-01-01')]
    out['nc_long'] = pd.to_numeric(out['nc_long'],  errors='coerce')
    out['nc_short']= pd.to_numeric(out['nc_short'], errors='coerce')
    out['net_long']= out['nc_long'] - out['nc_short']
    return out[['date', 'instrument', 'net_long']].dropna()

all_frames = []
for url_tpl, market_codes in SOURCES:
    label = 'fin' if 'fin_txt' in url_tpl else 'disagg'
    print(f'\n--- {label} ({", ".join(market_codes.values())}) ---')
    for yr in YEARS:
        url = url_tpl.format(year=yr)
        print(f'  {yr}... ', end='', flush=True)
        raw = fetch(url)
        if raw is None:
            print('skip')
            continue
        chunk = extract(raw, market_codes)
        if len(chunk):
            print(f'OK  {len(chunk)} rows  ({chunk["instrument"].unique().tolist()})')
            all_frames.append(chunk)
        else:
            print('no matches')

if not all_frames:
    print('\nERROR: No data. Check connection or CFTC site.')
    exit(1)

cot = pd.concat(all_frames).sort_values('date').drop_duplicates(['date', 'instrument'])

frames = []
for inst, grp in cot.groupby('instrument'):
    grp = grp.sort_values('date').reset_index(drop=True)
    roll_mean = grp['net_long'].rolling(52, min_periods=10).mean()
    roll_std  = grp['net_long'].rolling(52, min_periods=10).std().replace(0, np.nan)
    grp['z52'] = (grp['net_long'] - roll_mean) / roll_std
    frames.append(grp)
cot = pd.concat(frames).sort_values(['instrument', 'date'])

cot.to_csv('COT_weekly.csv', index=False)
print(f'\nSaved COT_weekly.csv  ({len(cot):,} rows)')
print('\nInstrument coverage:')
for inst, grp in cot.groupby('instrument'):
    print('  {:<8} {} to {}  ({} weeks)'.format(
        inst, grp['date'].min().date(), grp['date'].max().date(), len(grp)))
print('\nRun backtest_v4_cot.py to test the COT filter.')
