"""
alpha03_cross_asset_leadlag_ftmo.py

Phenomenon #3 from ALPHA_CANDIDATES.md. Descriptive measurement: does
today's USDINDEX or GOLD return predict TOMORROW's return in the rest
of the universe? A relationship type (A predicts B a step later) never
once tested across ~20 strategies before tonight's pivot -- everything
prior was single-instrument or paired-instrument same-day mechanics.

BACKGROUND: cross-quantilogram research finds directional predictability
from broad risk/safe-haven signals (originally studied via VIX) into
gold, USD, and other assets. We don't have VIX, but USDINDEX (a direct
USD basket) and GOLD (the classic safe-haven) are real, economically
motivated proxies for the same "risk sentiment" signal, and we already
collected both.

METHOD: for each day, compute LEADER_ret = today's return in USDINDEX
(or GOLD). Regress/correlate this against every OTHER instrument's
NEXT day's return (lag = 1 trading day, no lookahead: leader's return
is fully known by the time it's used to look at the follower's
already-future day). Report the correlation and a simple conditional
split (follower's next-day return when leader's return was in the top
vs bottom quintile that day) -- descriptive only, no trading rule.

Run in Codespace: python -u alpha03_cross_asset_leadlag_ftmo.py
"""
import pandas as pd
import numpy as np
import os, gc, warnings
warnings.filterwarnings('ignore')

BROKER_UTC_OFFSET_HOURS = 3
LEADERS = ['USDINDEX', 'GOLD']

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


def load_daily_ret(symbol):
    fn = FILES[symbol]
    if not os.path.exists(fn):
        return None
    df = pd.read_csv(fn, on_bad_lines='skip',
                      dtype={'open': 'float32', 'high': 'float32', 'low': 'float32', 'close': 'float32'})
    df['time'] = pd.to_datetime(df['time'], unit='s', utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    df = df.set_index('time').sort_index()
    df = df.dropna()
    daily = df.resample('1D').agg({'close':'last'}).dropna()
    del df
    daily = daily[daily['close'] > 0]
    daily['ret1'] = np.log(daily['close'] / daily['close'].shift(1))
    return daily[['ret1']].dropna()


print('Loading daily returns for all instruments...')
rets = {}
for symbol in FILES:
    d = load_daily_ret(symbol)
    if d is None:
        continue
    rets[symbol] = d['ret1']
    gc.collect()
loaded = sorted(rets.keys())
print(f'Loaded {len(loaded)} instruments: {loaded}\n')

ret_wide = pd.DataFrame(rets)


def measure(sub):
    if len(sub) == 0:
        return dict(N=0, mean=0.0, sharpe=0.0, wr=0.0)
    mean = sub.mean()
    sharpe = mean / sub.std() * np.sqrt(252) if sub.std() > 0 else 0.0
    wr = (sub > 0).mean() * 100
    return dict(N=len(sub), mean=mean, sharpe=sharpe, wr=wr)


for leader in LEADERS:
    if leader not in ret_wide.columns:
        print(f'\nLeader {leader} not available -- skipped.')
        continue
    print(f'\n{"#"*100}\n  LEADER: {leader}\n{"#"*100}')
    leader_ret = ret_wide[leader]
    # discovery/validation/final-OOS split by calendar time
    dates = leader_ret.dropna().index.sort_values()
    n = len(dates)
    disc_end = dates[int(n * 0.50)]
    val_end = dates[int(n * 0.75)]

    for follower in loaded:
        if follower == leader:
            continue
        follower_ret = ret_wide[follower]
        # next-day follower return, aligned to today's leader return -- lag=1, no lookahead
        aligned = pd.DataFrame({'leader_today': leader_ret, 'follower_tomorrow': follower_ret.shift(-1)}).dropna()
        if len(aligned) < 60:
            continue

        corr = aligned['leader_today'].corr(aligned['follower_tomorrow'])

        # conditional split: follower's next-day return when leader was in top vs bottom quintile
        q80 = aligned['leader_today'].quantile(0.8)
        q20 = aligned['leader_today'].quantile(0.2)
        top_follower = aligned.loc[aligned['leader_today'] >= q80, 'follower_tomorrow']
        bottom_follower = aligned.loc[aligned['leader_today'] <= q20, 'follower_tomorrow']

        m_top = measure(top_follower)
        m_bot = measure(bottom_follower)
        print(f'\n  {leader} -> {follower}  (N={len(aligned)}, corr={corr:+.4f})')
        print(f'    After {leader} TOP quintile day:     N={m_top["N"]:>4}  {follower} next-day mean={m_top["mean"]*10000:>+7.2f}bp  %pos={m_top["wr"]:>5.1f}%')
        print(f'    After {leader} BOTTOM quintile day:  N={m_bot["N"]:>4}  {follower} next-day mean={m_bot["mean"]*10000:>+7.2f}bp  %pos={m_bot["wr"]:>5.1f}%')

print('\nDone. No trading rule applied yet -- this is a measurement of the raw phenomenon only.')
