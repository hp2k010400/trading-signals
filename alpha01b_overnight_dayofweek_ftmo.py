"""
alpha01b_overnight_dayofweek_ftmo.py

Follow-up diagnostic on alpha01's finding: every FX pair showed a
strongly negative overnight Sharpe (-1.2 to -2.6), unusually
consistent across 8 independent instruments. Before treating that as
a genuine directional signal, this checks the most likely mechanical
explanation: FX broker rollover swap costs, often reflected directly
in the price feed around 21:00-22:00 UTC (inside our measured
"overnight" window), with TRIPLE swap charged on Wednesday rollover
to cover the weekend.

If the negative overnight effect is a swap-cost artifact, it should
spike sharply on the Wed->Thu transition specifically. If it's a
genuine signal, it should be roughly uniform across weekdays.

This is diagnostic, not a new phenomenon candidate -- it exists to
correctly interpret alpha01's FX finding before any strategy gets
built on it.

Run in Codespace: python -u alpha01b_overnight_dayofweek_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3

FX_FILES = {
    'EURUSD':'EURUSD_M1_ftmo.csv',
    'GBPUSD':'GBPUSD_M1_ftmo.csv',
    'USDJPY':'USDJPY_M1_ftmo.csv',
    'AUDNZD':'AUDNZD_M1_ftmo.csv',
    'AUDCAD':'AUDCAD_M1_ftmo.csv',
    'AUDCHF':'AUDCHF_M1_ftmo.csv',
    'USDCHF':'USDCHF_M1_ftmo.csv',
    'USDCAD':'USDCAD_M1_ftmo.csv',
}
# Non-FX comparison group -- indices generally do NOT carry FX-style swap
# rollover in the same way, useful as a control
INDEX_FILES = {
    'DAX':   'GER40_M1_ftmo.csv',
    'NAS100':'US100_M1_ftmo.csv',
    'SP500': 'US500_M1_ftmo.csv',
}


def load_daily(symbol, fn):
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
    daily['dow'] = daily.index.dayofweek   # 0=Mon .. 6=Sun; the "overnight" here is the
                                             # gap BEFORE this row's open, i.e. dow=3 (Thu)
                                             # row's overnight_ret is the Wed(close)->Thu(open) gap
    return daily.dropna(subset=['overnight_ret'])


def measure(sub):
    if len(sub) == 0:
        return dict(N=0, mean=0.0, sharpe=0.0, wr=0.0)
    mean = sub.mean()
    sharpe = mean / sub.std() if sub.std() > 0 else 0.0
    wr = (sub > 0).mean() * 100
    return dict(N=len(sub), mean=mean, sharpe=sharpe, wr=wr)


DOW_NAMES = {0: 'Mon(prev=Fri wknd)', 1: 'Tue(prev=Mon)', 2: 'Wed(prev=Tue)',
             3: 'Thu(prev=Wed *3xswap*)', 4: 'Fri(prev=Thu)'}


def report_group(label, files):
    print(f'\n{"#"*100}\n  {label}\n{"#"*100}')
    all_daily = []
    for symbol, fn in files.items():
        d = load_daily(symbol, fn)
        if d is None:
            continue
        d = d.copy()
        d['symbol'] = symbol
        all_daily.append(d)
    if not all_daily:
        print('  No data available.')
        return
    pooled = pd.concat(all_daily)

    print(f'\n  Pooled overnight return by day-of-week (row\'s dow = the day the market OPENED,')
    print(f'  i.e. this is the gap ending on that day\'s open):')
    for dow in sorted(pooled['dow'].unique()):
        if dow > 4:
            continue   # skip weekend rows if any slipped through
        sub = pooled[pooled['dow'] == dow]['overnight_ret']
        m = measure(sub)
        name = DOW_NAMES.get(dow, str(dow))
        flag = '  <<<< TRIPLE SWAP DAY IF THIS SPIKES' if dow == 3 else ''
        print(f'    {name:<26}  N={m["N"]:>5}  mean={m["mean"]*10000:>+8.2f}bp  sharpe={m["sharpe"]:>+7.4f}  %positive={m["wr"]:>5.1f}%{flag}')

    print(f'\n  Per-instrument, Wed->Thu (triple swap) vs all other weekday gaps:')
    for symbol, fn in files.items():
        d = load_daily(symbol, fn)
        if d is None:
            continue
        wed_thu = measure(d[d['dow'] == 3]['overnight_ret'])
        other = measure(d[d['dow'] != 3]['overnight_ret'])
        print(f'    {symbol:<10}  Wed->Thu: mean={wed_thu["mean"]*10000:>+7.2f}bp (N={wed_thu["N"]:>4})   '
              f'other days: mean={other["mean"]*10000:>+7.2f}bp (N={other["N"]:>4})   '
              f'ratio={wed_thu["mean"]/other["mean"] if other["mean"] != 0 else float("nan"):>+6.2f}x')


report_group('FX PAIRS', FX_FILES)
report_group('EQUITY INDICES (control group)', INDEX_FILES)

print('\nDone. Interpretation: if FX Wed->Thu mean is ~3x (or more) more negative than other')
print('weekday gaps, this is very likely a swap/rollover cost artifact, not a directional')
print('signal to trade. If all weekdays look similar, that argues for a genuine effect.')
