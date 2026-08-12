"""
alpha01_overnight_intraday_ftmo.py

Phenomenon #1 from ALPHA_CANDIDATES.md. Per the research directive's
explicit instruction: this is NOT "find parameters that maximise PF."
This is "does overnight vs intraday return decomposition show a real,
measurable, unconditional split in our data" -- a descriptive
measurement, not a strategy, tested first before any trading rule is
built on top of it.

BACKGROUND: Cooper/Cliff/Gulen (2008), Kelly/Clark (2011), Bondarenko/
Muravyev (2023), NY Fed Staff Report 917 all find the equity risk
premium has historically accrued almost entirely overnight (close to
next open), not intraday (open to close). A 2026 paper ("The
Disappearing Overnight Drift") finds this weakening in recent data --
an honest headwind stated up front, not discovered after the fact.

METHOD:
  For every instrument, every day:
    overnight_ret = log(today_open / yesterday_close)
    intraday_ret  = log(today_close / today_open)
  Report, per instrument and pooled:
    - mean, total, Sharpe-like ratio of each component separately
    - what fraction of total (close-to-close) return each component
      contributed
    - split into DISCOVERY (earliest 50% of history), VALIDATION
      (next 25%), FINAL OOS (most recent 25%, reported but not used
      to decide anything) -- per Phase 6's discovery/validation/OOS
      split requirement.

No trading rule, no stop, no target, no cost model yet -- this
measures the phenomenon's existence and stability first. If it's real
and stable across all three periods, a tradeable version gets built
next. If it's not, that's reported honestly.

Run in Codespace: python -u alpha01_overnight_intraday_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
    'US30':  'US30_M1_ftmo.csv',
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'GOLD':  'XAUUSD_M1_ftmo.csv',
    'NATGAS':'NATGAS_cash_M1_ftmo.csv',
    'UK100': 'UK100_cash_M1_ftmo.csv',
    'AUDNZD':'AUDNZD_M1_ftmo.csv',
    'AUDCAD':'AUDCAD_M1_ftmo.csv',
    'AUDCHF':'AUDCHF_M1_ftmo.csv',
    'USDCHF':'USDCHF_M1_ftmo.csv',
    'USDCAD':'USDCAD_M1_ftmo.csv',
    'FRA40': 'FRA40_M1_ftmo.csv',
    'JP225': 'JP225_M1_ftmo.csv',
    'AUS200':'AUS200_M1_ftmo.csv',
    'EU50':  'EU50_M1_ftmo.csv',
    'US2000':'US2000_M1_ftmo.csv',
    'HK50':  'HK50_M1_ftmo.csv',
    'WTIOIL':  'WTIOIL_M1_ftmo.csv',
    'BRENTOIL':'BRENTOIL_M1_ftmo.csv',
    'SILVER':  'SILVER_M1_ftmo.csv',
    'COPPER':  'COPPER_M1_ftmo.csv',
    'PLATINUM':'PLATINUM_M1_ftmo.csv',
    'PALLADIUM':'PALLADIUM_M1_ftmo.csv',
    'USDINDEX':'USDINDEX_M1_ftmo.csv',
}
ASSET_CLASS = {
    'DAX':'Index','NAS100':'Index','SP500':'Index','US30':'Index','UK100':'Index',
    'FRA40':'Index','JP225':'Index','AUS200':'Index','EU50':'Index','US2000':'Index','HK50':'Index',
    'EURUSD':'FX','GBPUSD':'FX','USDJPY':'FX','AUDNZD':'FX','AUDCAD':'FX','AUDCHF':'FX','USDCHF':'FX','USDCAD':'FX','USDINDEX':'FX',
    'GOLD':'Metal','SILVER':'Metal','PLATINUM':'Metal','PALLADIUM':'Metal',
    'NATGAS':'Energy','WTIOIL':'Energy','BRENTOIL':'Energy','COPPER':'Metal',
}


def load_daily(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    daily = df.resample('1D').agg({'open':'first','close':'last'}).dropna()
    del df
    daily = daily[daily['open'] > 0]
    daily['prev_close'] = daily['close'].shift(1)
    daily['overnight_ret'] = np.log(daily['open'] / daily['prev_close'])
    daily['intraday_ret'] = np.log(daily['close'] / daily['open'])
    daily['close_to_close_ret'] = np.log(daily['close'] / daily['prev_close'])
    return daily.dropna()


def measure(label, sub):
    """Descriptive stats for one component of return over one slice of data."""
    if len(sub) == 0:
        return dict(N=0, mean=0.0, total=0.0, sharpe=0.0, wr=0.0)
    mean = sub.mean()
    total = sub.sum()
    sharpe = mean / sub.std() * np.sqrt(252) if sub.std() > 0 else 0.0   # annualized
    wr = (sub > 0).mean() * 100
    return dict(N=len(sub), mean=mean, total=total, sharpe=sharpe, wr=wr)


def print_measure(label, m, width=14):
    print(f'  {label:<{width}}  N={m["N"]:>6}  mean={m["mean"]*10000:>+8.2f}bp  '
          f'total={m["total"]:>+8.4f}  annSharpe={m["sharpe"]:>+7.3f}  %positive={m["wr"]:>5.1f}%')


print('Loading daily bars, decomposing overnight vs intraday returns...')
per_symbol = {}
for symbol in FILES:
    d = load_daily(symbol)
    if d is None:
        continue
    per_symbol[symbol] = d
    gc.collect()
loaded = sorted(per_symbol.keys())
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

pooled_rows = []
for symbol, d in per_symbol.items():
    dd = d.copy()
    dd['symbol'] = symbol
    dd['asset_class'] = ASSET_CLASS[symbol]
    pooled_rows.append(dd)
pooled = pd.concat(pooled_rows).sort_index()

# Discovery / Validation / Final OOS split by CALENDAR TIME across the whole pooled
# sample (50% / 25% / 25%), per Phase 6.
dates = pooled.index.unique().sort_values()
n = len(dates)
disc_end = dates[int(n * 0.50)]
val_end = dates[int(n * 0.75)]
print(f'Discovery period:  {dates[0].date()} -> {disc_end.date()}')
print(f'Validation period: {disc_end.date()} -> {val_end.date()}')
print(f'Final OOS period:  {val_end.date()} -> {dates[-1].date()}  (reported, not used to decide anything)\n')

periods = {
    'DISCOVERY': pooled[pooled.index < disc_end],
    'VALIDATION': pooled[(pooled.index >= disc_end) & (pooled.index < val_end)],
    'FINAL OOS': pooled[pooled.index >= val_end],
}

for period_name, pdf in periods.items():
    print(f'\n{"="*95}\n  {period_name}  (N days pooled across instruments = {len(pdf)})\n{"="*95}')
    m_on = measure('overnight', pdf['overnight_ret'])
    m_id = measure('intraday', pdf['intraday_ret'])
    m_cc = measure('close-to-close', pdf['close_to_close_ret'])
    print_measure('Overnight', m_on)
    print_measure('Intraday', m_id)
    print_measure('Close-close', m_cc)
    total_cc = m_cc['total']
    if total_cc != 0:
        print(f'  Overnight share of total close-to-close return: {m_on["total"]/total_cc*100:+.1f}%')
        print(f'  Intraday share of total close-to-close return:  {m_id["total"]/total_cc*100:+.1f}%')

print(f'\n{"="*95}\n  BY ASSET CLASS (full history, all periods pooled)\n{"="*95}')
for ac in sorted(pooled['asset_class'].unique()):
    sub = pooled[pooled['asset_class'] == ac]
    print(f'\n  -- {ac} --')
    print_measure('Overnight', measure('overnight', sub['overnight_ret']))
    print_measure('Intraday', measure('intraday', sub['intraday_ret']))

print(f'\n{"="*95}\n  BY INSTRUMENT (full history)\n{"="*95}')
for symbol in loaded:
    sub = pooled[pooled['symbol'] == symbol]
    m_on = measure('overnight', sub['overnight_ret'])
    m_id = measure('intraday', sub['intraday_ret'])
    print(f'  {symbol:<10}  overnight: N={m_on["N"]:>5} total={m_on["total"]:>+8.4f} Sharpe={m_on["sharpe"]:>+6.3f}   '
          f'intraday: N={m_id["N"]:>5} total={m_id["total"]:>+8.4f} Sharpe={m_id["sharpe"]:>+6.3f}')

print('\nDone. No trading rule applied yet -- this is a measurement of the raw phenomenon only.')
