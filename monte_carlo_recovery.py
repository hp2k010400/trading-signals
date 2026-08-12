"""
monte_carlo_recovery.py
FTMO 70k Challenge - Recovery probability (no time limit).

FTMO standard challenge has NO deadline - you trade until you either
hit the profit target or breach a loss limit. So we model:
  P(balance reaches 77,000 before dropping to 63,000)

Starting state:  65,076 (after bug losses)
Target:          77,000 (+10% on opening 70k)
Floor:           63,000 (-10% on opening 70k = account blown)
Daily loss cap:  3,500  (5% of opening 70k) - checked each day

System stats from OOS backtest 2022-2026 (IB + PB, 9 instruments):
  Win rate:        44%
  TP:              3R
  Trades/day:      4.87 (Poisson)
  Risk per trade:  0.5% of current balance (compounds up/down)
"""

import numpy as np

# -- PARAMETERS ---------------------------------------------------------------
BALANCE_START    = 63_562.0
TARGET           = 77_000.0
FLOOR            = 63_000.0
DAILY_LOSS_LIMIT = 3_500.0

WIN_RATE         = 0.44
TP_R             = 3.0
RISK_PCT         = 0.0025  # reduced to 0.25% to widen buffer
AVG_TRADES_DAY   = 4.87

N_SIMS           = 100_000
MAX_DAYS         = 365        # safety cap (should never hit with positive EV)

RNG = np.random.default_rng(42)

# -- SIMULATOR (no time limit) ------------------------------------------------
def simulate(start_balance):
    """Run until target hit or floor breached. Returns ('pass'/'blown', days_taken)."""
    balance = start_balance
    days = 0
    while True:
        days += 1
        if days > MAX_DAYS:
            return 'timeout', days   # shouldn't happen with positive EV
        n_trades = int(RNG.poisson(AVG_TRADES_DAY))
        day_pnl  = 0.0
        for _ in range(n_trades):
            risk    = balance * RISK_PCT
            outcome = TP_R * risk if RNG.random() < WIN_RATE else -risk
            balance += outcome
            day_pnl += outcome
            if balance <= FLOOR:
                return 'blown', days
            if balance >= TARGET:
                return 'pass', days
        if day_pnl <= -DAILY_LOSS_LIMIT:
            return 'blown', days

# -- RUN SIMS -----------------------------------------------------------------
print('Running simulations (this takes ~30 seconds)...')

results_now   = [simulate(BALANCE_START) for _ in range(N_SIMS)]
results_clean = [simulate(70_000.0)      for _ in range(N_SIMS)]

outcomes_now   = np.array([r[0] for r in results_now])
days_now       = np.array([r[1] for r in results_now], dtype=float)
outcomes_clean = np.array([r[0] for r in results_clean])
days_clean     = np.array([r[1] for r in results_clean], dtype=float)

# -- RESULTS ------------------------------------------------------------------
pass_now    = np.sum(outcomes_now == 'pass')
blown_now   = np.sum(outcomes_now == 'blown')
timeout_now = np.sum(outcomes_now == 'timeout')

pass_clean  = np.sum(outcomes_clean == 'pass')
blown_clean = np.sum(outcomes_clean == 'blown')

pct_pass_now   = pass_now  / N_SIMS * 100
pct_blown_now  = blown_now / N_SIMS * 100
pct_pass_clean = pass_clean / N_SIMS * 100

# Days stats for passing sims only
pass_days_now   = days_now[outcomes_now == 'pass']
pass_days_clean = days_clean[outcomes_clean == 'pass']

print()
print('=' * 68)
print('  FTMO 70k Recovery Monte Carlo  (no time limit)')
print('=' * 68)
print(f'  Simulations: {N_SIMS:,}')
print()
print(f'  {"":30}  {"Current (64.4k)":>14}  {"Clean (70k)":>12}')
print('  ' + '-' * 60)
print(f'  {"Pass probability":30}  {pct_pass_now:>13.1f}%  {pct_pass_clean:>11.1f}%')
print(f'  {"Blow probability":30}  {pct_blown_now:>13.1f}%  {100-pct_pass_clean:>11.1f}%')
if timeout_now > 0:
    print(f'  {"Timeout (>365 days)":30}  {timeout_now/N_SIMS*100:>13.1f}%  {"n/a":>12}')
print()
print(f'  --- When passing (days to reach target) ---')
print(f'  {"Best case  (p10)":30}  {np.percentile(pass_days_now,10):>13.0f}')
print(f'  {"Typical    (p50 median)":30}  {np.median(pass_days_now):>13.0f}')
print(f'  {"Mean":30}  {np.mean(pass_days_now):>13.0f}')
print(f'  {"Slow run   (p90)":30}  {np.percentile(pass_days_now,90):>13.0f}')
print(f'  {"Worst case (p95)":30}  {np.percentile(pass_days_now,95):>13.0f}')
print(f'  {"Extreme    (p99)":30}  {np.percentile(pass_days_now,99):>13.0f}')
print()
print('=' * 68)
print()

# -- CONTEXT ------------------------------------------------------------------
risk_per_trade = BALANCE_START * RISK_PCT
exp_per_trade  = WIN_RATE * TP_R * risk_per_trade - (1 - WIN_RATE) * risk_per_trade
exp_daily      = AVG_TRADES_DAY * exp_per_trade

print('  CONTEXT')
print('  ' + '-' * 60)
print(f'  Buffer before blow:          {BALANCE_START - FLOOR:,.0f}  (only {(BALANCE_START-FLOOR)/(risk_per_trade):.0f} consecutive losses)')
print(f'  Gain needed to pass:         {TARGET - BALANCE_START:,.0f}')
print(f'  Risk per trade:              {risk_per_trade:,.0f}')
print(f'  Win pays / Loss costs:       {risk_per_trade*TP_R:,.0f} / {risk_per_trade:,.0f}')
print(f'  Expectancy per trade:        {exp_per_trade:+,.0f}')
print(f'  Expected daily P&L:          {exp_daily:+,.0f}')
print(f'  Days to target at avg pace:  {(TARGET - BALANCE_START) / exp_daily:.1f}')
print()
print('  VERDICT')
print('  ' + '-' * 60)
disadvantage = pct_pass_now - pct_pass_clean
print(f'  Bug losses cost you {abs(disadvantage):.1f}pp of pass probability.')
if pct_pass_now >= 80:
    print(f'  Still {pct_pass_now:.0f}% to pass - system is robust, keep running.')
elif pct_pass_now >= 60:
    print(f'  {pct_pass_now:.0f}% to pass - tough but very much alive. Keep running.')
elif pct_pass_now >= 40:
    print(f'  {pct_pass_now:.0f}% to pass - coin flip territory. Consider if worth the stress.')
else:
    print(f'  Only {pct_pass_now:.0f}% to pass - account is in serious trouble.')
print('=' * 68)
