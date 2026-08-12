"""
monte_carlo.py
FTMO Phase 1 Monte Carlo — H1 Inside Bar (all instruments, power hours)
Bootstrap resampling from empirical OOS distribution (2022-2026)

Answers:
  1. Probability of passing FTMO Phase 1 at each risk % level
  2. Optimal risk per trade
  3. Daily limit breach probability
  4. Equity curve percentiles over 30 days
  5. Kelly criterion vs our sizing

Run: python monte_carlo.py
"""
import pandas as pd, numpy as np, os, warnings
warnings.filterwarnings('ignore')

# ── FTMO Phase 1 parameters ───────────────────────────────────────────────────
ACCOUNT     = 70_000
FTMO_TARGET =  7_000   # +10%
FTMO_TOTAL  = -7_000   # -10% total loss → fail
FTMO_DAILY  = -3_500   # -5% daily loss  → fail
MIN_DAYS    = 4        # must trade at least 4 days before passing
MAX_DAYS    = 30       # challenge window
N_SIMS      = 10_000
RISK_LEVELS = [0.0025, 0.005, 0.0075, 0.01]   # 0.25%, 0.5%, 0.75%, 1.0%
TP_R        = 3.0

# ── Instrument config ─────────────────────────────────────────────────────────
FILES = {
    'DAX':   'GER40_M1_oanda.csv',
    'UK100': 'UK100_M1_oanda.csv',
    'NAS100':'US100_M1_oanda.csv',
    'SP500': 'US500_M1_oanda.csv',
    'EURUSD':'EURUSD_M1_oanda.csv',
    'GBPUSD':'GBPUSD_M1_oanda.csv',
    'GOLD':  'XAUUSD_M1_oanda.csv',
}
COST = {'DAX':0.07,'UK100':0.07,'NAS100':0.06,'SP500':0.06,
        'EURUSD':0.08,'GBPUSD':0.08,'GOLD':0.08}
H1_HOURS = {
    'DAX':    {8,9,10,13,14}, 'UK100':  {8,9,10,13,14},
    'EURUSD': {8,9,13,14,15}, 'GBPUSD': {8,9,13,14,15},
    'GOLD':   {8,9,13,14,15}, 'NAS100': {13,14,15,16},
    'SP500':  {13,14,15,16},
}
H1_SKIP = {
    'DAX':frozenset({4}),'UK100':frozenset({4}),
    'EURUSD':frozenset({4}),'GBPUSD':frozenset({4}),'GOLD':frozenset({4}),
    'NAS100':frozenset({0,4}),'SP500':frozenset({0,4}),
}
_m1 = {}

def load(k):
    fn = FILES.get(k,'')
    if not fn or not os.path.exists(fn): _m1[k]=None; return
    df = pd.read_csv(fn)
    df['time'] = pd.to_datetime(df['time'],unit='s',utc=True)
    df = df.set_index('time').sort_index()
    for c in ['open','high','low','close']: df[c]=pd.to_numeric(df[c],errors='coerce')
    _m1[k] = df.dropna()

def vsim(k, ep, d, entry, sl, tp_r, max_bars=480):
    m1=_m1[k]; sl_d=abs(entry-sl)
    if sl_d<=0: return -1.0
    end=min(ep+1+max_bars,len(m1))
    hi=m1['high'].values[ep+1:end]; lo=m1['low'].values[ep+1:end]
    if len(hi)==0: return -1.0
    tp=entry+sl_d*tp_r if d==1 else entry-sl_d*tp_r
    if d==1:
        sl_i=int(np.argmax(lo<=sl)) if np.any(lo<=sl) else max_bars
        tp_i=int(np.argmax(hi>=tp)) if np.any(hi>=tp) else max_bars
    else:
        sl_i=int(np.argmax(hi>=sl)) if np.any(hi>=sl) else max_bars
        tp_i=int(np.argmax(lo<=tp)) if np.any(lo<=tp) else max_bars
    if tp_i<=sl_i: return tp_r
    if sl_i<max_bars: return -1.0
    lp=m1['close'].values[end-1]
    return ((lp-entry) if d==1 else (entry-lp))/sl_d

def collect_oos(key):
    """Collect H1 inside bar trades 2022-2026, return list of (date, R) pairs."""
    m1=_m1[key]; cost=COST[key]*1.5; mi=m1.index
    skip=H1_SKIP.get(key,frozenset({4}))
    p_hours=H1_HOURS.get(key,{8,9,13,14})
    s=pd.Timestamp(2022,1,1,tz='UTC'); e=pd.Timestamp(2026,1,1,tz='UTC')
    m1w=m1[(m1.index>=s)&(m1.index<e)]
    if len(m1w)<100: return []
    h1=m1w.resample('1h').agg({'open':'first','high':'max','low':'min','close':'last'}).dropna()
    h1=h1[(h1['open']>0)]
    hl=list(h1.index); out=[]; day_count={}
    for i in range(1,len(hl)):
        ts=hl[i]
        if ts.dayofweek in skip: continue
        if ts.hour not in p_hours: continue
        date_k=ts.date()
        if day_count.get(date_k,0)>=3: continue
        curr=h1.iloc[i]; prev=h1.iloc[i-1]
        if not(curr['high']<prev['high'] and curr['low']>prev['low']): continue
        ib_h=float(curr['high']); ib_l=float(curr['low'])
        if (ib_h-ib_l)<=0 or (ib_h-ib_l)/ib_h<0.00015: continue
        entry_start=ts+pd.Timedelta(hours=1)
        window=m1[(mi>=entry_start)&(mi<entry_start+pd.Timedelta(hours=3))]
        if len(window)==0: continue
        for j in range(len(window)):
            b=window.iloc[j]
            if b['high']>ib_h: d=1; entry=ib_h; sl=ib_l
            elif b['low']<ib_l: d=-1; entry=ib_l; sl=ib_h
            else: continue
            ep=mi.searchsorted(window.index[j])
            if ep>=len(m1): break
            day_count[date_k]=day_count.get(date_k,0)+1
            r=vsim(key,ep,d,entry,sl,TP_R)-cost
            out.append((date_k, r))
            break
    return out

# ── 1. Load & collect ─────────────────────────────────────────────────────────
print('Loading M1 data...')
for k in FILES: load(k)
loaded=[k for k in FILES if _m1.get(k) is not None]
print(f'Loaded: {", ".join(loaded)}\n')

print('Collecting OOS trades (2022–2026)...')
daily_buckets = {}
all_r = []
for k in loaded:
    for dt, r in collect_oos(k):
        daily_buckets.setdefault(dt, []).append(r)
        all_r.append(r)

all_r = np.asarray(all_r, float)
day_r_list = [np.asarray(v) for v in daily_buckets.values()]
n_oos_days = len(day_r_list)
wins = all_r[all_r>0]; losses = all_r[all_r<=0]
pf = round(wins.sum()/abs(losses.sum()),2) if len(losses) else 0
wr = round(len(wins)/len(all_r)*100,1) if len(all_r) else 0
ppd = len(all_r)/n_oos_days if n_oos_days else 0

print(f'  OOS trades:    {len(all_r):,}')
print(f'  Trading days:  {n_oos_days}')
print(f'  Trades/day:    {ppd:.2f}')
print(f'  Win rate:      {wr:.1f}%')
print(f'  PF:            {pf:.2f}')
print(f'  Expectancy:    {all_r.mean():.4f}R\n')

# ── 2. Monte Carlo ─────────────────────────────────────────────────────────────
def run_mc(risk_frac, n_sims=N_SIMS, seed=42):
    rng = np.random.default_rng(seed)
    risk_gbp = ACCOUNT * risk_frac
    n_days = len(day_r_list)
    passed=0; fail_dd=0; fail_daily=0; timeout=0
    final_eq=[]; days_to_pass=[]; curves=[]

    for sim in range(n_sims):
        equity=0.0; day_num=0; done=False; curve=[0.0]
        while day_num < MAX_DAYS and not done:
            day_trades = day_r_list[rng.integers(0, n_days)]
            day_pnl=0.0
            for r in day_trades:
                pnl_this = r * risk_gbp
                day_pnl += pnl_this
                equity  += pnl_this
                if equity <= FTMO_TOTAL:
                    fail_dd+=1; done=True; break
                if day_pnl <= FTMO_DAILY:
                    fail_daily+=1; done=True; break
                if equity >= FTMO_TARGET and day_num+1 >= MIN_DAYS:
                    passed+=1; days_to_pass.append(day_num+1); done=True; break
            curve.append(equity)
            day_num+=1
        if not done: timeout+=1
        final_eq.append(equity)
        if sim < 500: curves.append(curve)

    return {
        'risk_frac':risk_frac, 'risk_gbp':risk_gbp,
        'passed':passed, 'fail_dd':fail_dd, 'fail_daily':fail_daily, 'timeout':timeout,
        'final_eq':np.asarray(final_eq), 'days_to_pass':np.asarray(days_to_pass),
        'curves':curves,
    }

print('Running Monte Carlo...')
results = {}
for rf in RISK_LEVELS:
    print(f'  {rf*100:.2f}% risk...', end=' ', flush=True)
    results[rf] = run_mc(rf)
    print(f"pass {results[rf]['passed']/N_SIMS*100:.1f}%")

# ── 3. Summary table ──────────────────────────────────────────────────────────
print(f'\n{"═"*76}')
print('  FTMO PHASE 1 MONTE CARLO — H1 Inside Bar OOS (2022-2026)')
print(f'  {N_SIMS:,} simulations × {MAX_DAYS} days | 0.5% risk = £{ACCOUNT*0.005:.0f}/trade')
print(f'{"═"*76}')
print(f'\n  {"Risk%":>6}  {"£/tr":>6}  {"PASS%":>7}  {"FailDD%":>8}  '
      f'{"FailDay%":>9}  {"Timeout%":>9}  {"Median":>8}  {"p5":>8}  {"p95":>8}')
print('  '+'─'*72)
best_pass = max(r['passed'] for r in results.values())
for rf, r in results.items():
    fe=r['final_eq']; n=N_SIMS
    pp=r['passed']/n*100; fd=r['fail_dd']/n*100
    fday=r['fail_daily']/n*100; to=r['timeout']/n*100
    med=np.median(fe); p5=np.percentile(fe,5); p95=np.percentile(fe,95)
    star=' ◄ BEST' if r['passed']==best_pass else ''
    print(f'  {rf*100:>5.2f}%  £{r["risk_gbp"]:>5.0f}  {pp:>6.1f}%  {fd:>7.1f}%  '
          f'{fday:>8.1f}%  {to:>8.1f}%  £{med:>6,.0f}  £{p5:>6,.0f}  £{p95:>6,.0f}{star}')

# ── 4. Deep dive on best risk ─────────────────────────────────────────────────
best_rf = max(results, key=lambda x: results[x]['passed'])
best = results[best_rf]
dtp = best['days_to_pass']

print(f'\n\n{"═"*76}')
print(f'  DEEP DIVE — {best_rf*100:.2f}% risk per trade (£{best["risk_gbp"]:.0f})')
print(f'{"═"*76}')
print(f'  Pass:               {best["passed"]:,} / {N_SIMS:,}  ({best["passed"]/N_SIMS*100:.1f}%)')
print(f'  Fail total DD:      {best["fail_dd"]:,}  ({best["fail_dd"]/N_SIMS*100:.1f}%)')
print(f'  Fail daily limit:   {best["fail_daily"]:,}  ({best["fail_daily"]/N_SIMS*100:.1f}%)')
print(f'  Timeout (30 days):  {best["timeout"]:,}  ({best["timeout"]/N_SIMS*100:.1f}%)')
if len(dtp):
    print(f'\n  Days to pass (passing runs only):')
    print(f'    Fastest 10%:  {np.percentile(dtp,10):.0f} days')
    print(f'    Median:       {np.median(dtp):.0f} days')
    print(f'    Slowest 10%:  {np.percentile(dtp,90):.0f} days')

fe = best['final_eq']
print(f'\n  Final P&L percentiles:')
for pct in [5,10,25,50,75,90,95]:
    v=np.percentile(fe,pct)
    bar=('█'*min(int(abs(v)/200),30)) if v>0 else ('▒'*min(int(abs(v)/200),30))
    sign='+' if v>0 else ''
    print(f'    p{pct:<3}: £{v:>8,.0f}  {sign}{v/ACCOUNT*100:>5.1f}%  {bar}')

# ── 5. Equity fan chart ───────────────────────────────────────────────────────
ec = best['curves']
if ec:
    max_len = max(len(c) for c in ec)
    padded  = [c+[c[-1]]*(max_len-len(c)) for c in ec]
    arr     = np.array(padded)
    print(f'\n  Equity curve percentiles (£P&L from start):')
    print(f'  {"Day":>4}  {"p5":>8}  {"p25":>8}  {"Median":>8}  {"p75":>8}  {"p95":>8}')
    print('  '+'─'*52)
    step = max(1, min(MAX_DAYS//8, 5))
    for d in list(range(0, min(max_len, MAX_DAYS+1), step)):
        col=arr[:,d]
        p5,p25,p50,p75,p95=np.percentile(col,[5,25,50,75,95])
        hit=' ◄ median at target' if p50>=FTMO_TARGET else ''
        print(f'  {d:>4}  £{p5:>6,.0f}  £{p25:>6,.0f}  £{p50:>6,.0f}  '
              f'£{p75:>6,.0f}  £{p95:>6,.0f}{hit}')

# ── 6. Daily breach probability ───────────────────────────────────────────────
print(f'\n\n{"═"*76}')
print('  DAILY LIMIT BREACH PROBABILITY (single-day simulation, 50k days)')
print(f'{"═"*76}')
rng2 = np.random.default_rng(99)
n_day_sims = 50_000
day_indices = np.arange(len(day_r_list))
print(f'  {"Risk%":>6}  {"£/tr":>6}  {"P(breach)":>10}  {"Worst day":>11}  '
      f'{"p1 day":>10}  {"p5 day":>10}  {"p50 day":>10}')
print('  '+'─'*68)
for rf in RISK_LEVELS:
    risk_gbp=ACCOUNT*rf
    daily_pnls=np.array([
        sum(r*risk_gbp for r in day_r_list[rng2.integers(0,len(day_r_list))])
        for _ in range(n_day_sims)
    ])
    breach=daily_pnls[daily_pnls<=FTMO_DAILY]
    bp=len(breach)/n_day_sims*100
    print(f'  {rf*100:>5.2f}%  £{risk_gbp:>5.0f}  {bp:>9.3f}%  '
          f'£{daily_pnls.min():>9,.0f}  £{np.percentile(daily_pnls,1):>8,.0f}  '
          f'£{np.percentile(daily_pnls,5):>8,.0f}  £{np.median(daily_pnls):>8,.0f}')

# ── 7. Kelly ─────────────────────────────────────────────────────────────────
print(f'\n\n{"═"*76}')
print('  KELLY CRITERION')
print(f'{"═"*76}')
p   = len(all_r[all_r>0])/len(all_r)
avg_w = all_r[all_r>0].mean(); avg_l = abs(all_r[all_r<=0].mean())
b   = avg_w / avg_l
kf  = (b*p-(1-p))/b
kh  = kf/2
print(f'  Win rate:        {p*100:.1f}%')
print(f'  Avg win (R):     {avg_w:.3f}R')
print(f'  Avg loss (R):    {avg_l:.3f}R')
print(f'  Payoff ratio b:  {b:.3f}')
print(f'  Full Kelly:      {kf*100:.2f}% per trade')
print(f'  Half Kelly:      {kh*100:.2f}% per trade  ← recommended ceiling')
print(f'  Our best risk:   {best_rf*100:.2f}% per trade')
if best_rf <= kh:
    print(f'  ✓ Our sizing is BELOW half Kelly — conservative and correct')
else:
    print(f'  ⚠ Our sizing is ABOVE half Kelly — consider reducing risk')

# ── 8. Expected cost to funded ────────────────────────────────────────────────
print(f'\n\n{"═"*76}')
print('  EXPECTED COST TO FUNDED ACCOUNT')
print(f'{"═"*76}')
CHALLENGE_COST = 489  # £ per attempt
for rf, r in results.items():
    pp = r['passed']/N_SIMS
    if pp > 0:
        avg_attempts = 1/pp
        expected_cost = avg_attempts * CHALLENGE_COST
        p1_then_p2 = pp * pp  # rough Phase 2 pass rate same as Phase 1
        print(f'  {rf*100:.2f}% risk:  pass rate {pp*100:.1f}%  '
              f'→ avg {avg_attempts:.1f} attempts  '
              f'→ expected £{expected_cost:,.0f} to funded')

# ── 9. Verdict ────────────────────────────────────────────────────────────────
print(f'\n\n{"═"*76}')
print('  VERDICT')
print(f'{"═"*76}')
best_pp = best['passed']/N_SIMS*100
if best_pp >= 70:
    grade = '✓ HIGH CONFIDENCE — build the EA, attempt FTMO'
elif best_pp >= 50:
    grade = '~ SOLID — worth attempting, expect variance across runs'
elif best_pp >= 30:
    grade = '⚠ MARGINAL — more live validation before paying £489'
else:
    grade = '✗ NOT READY — do not attempt FTMO yet'
print(f'  Best pass rate:  {best_pp:.1f}% at {best_rf*100:.2f}% risk per trade')
print(f'  Assessment:      {grade}')
print(f'{"═"*76}\nDone.')
