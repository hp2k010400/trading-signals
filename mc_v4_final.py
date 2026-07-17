"""
mc_v4_final.py  -  Monte Carlo with confirmed backtest parameters
=================================================================
Uses the actual per-strategy backtest results (same engine as stress test,
hours confirmed against EA code):

  System win rate  : 53.1%
  Avg win          : 2.63R
  Avg loss         : 1.11R
  Profit factor    : 2.69
  Avg risk/trade   : 0.531% of account (~£372 at £70k base)
  Trades/day       : 3.2 (Poisson)

Previous MC used WR=51.8%, PF=1.98, AVG_LOSS=1.15 — slightly conservative.

Current position   : £67,624
Target             : £77,000  (+10% of £70k starting balance)
Hard floor         : £63,000  (-10% of £70k = total drawdown limit)
Daily loss limit   : £3,500   (-5% of £70k)

Run: python mc_v4_final.py
"""
import numpy as np
from math import sqrt, ceil

np.random.seed(42)

START_BAL   = 67_624
TARGET      = 77_000
FLOOR       = 63_000
DAILY_LIMIT = 3_500
MC_RUNS     = 100_000
MAX_DAYS    = 60
LAMBDA      = 3.2

# Confirmed from per-strategy backtest (same engine as stress test)
WR          = 0.531
AVG_WIN_R   = 2.63
AVG_LOSS_R  = 1.11
AVG_RISK    = 372   # £ per trade at £70k base, scales proportionally

def run_mc(wr, avg_win_r, avg_loss_r, label, seed=42):
    rng = np.random.default_rng(seed)
    passes, floors, timeouts = 0, 0, 0
    days_list = []
    for _ in range(MC_RUNS):
        bal = float(START_BAL)
        passed = False
        for day in range(1, MAX_DAYS + 1):
            n = int(rng.poisson(LAMBDA))
            if n == 0:
                continue
            risk = AVG_RISK * (bal / 70_000)
            outcomes = rng.random(n) < wr
            wins  = outcomes.sum()
            loss  = n - wins
            daily = float(wins * risk * avg_win_r - loss * risk * avg_loss_r)
            if daily < -DAILY_LIMIT:
                floors += 1; break
            bal += daily
            if bal <= FLOOR:
                floors += 1; break
            if bal >= TARGET:
                passes += 1
                days_list.append(day)
                passed = True; break
        else:
            timeouts += 1
    pass_r  = passes / MC_RUNS * 100
    floor_r = floors / MC_RUNS * 100
    p10  = int(np.percentile(days_list, 10))  if days_list else None
    med  = int(np.median(days_list))           if days_list else None
    p90  = int(np.percentile(days_list, 90))  if days_list else None
    return pass_r, floor_r, timeouts / MC_RUNS * 100, p10, med, p90

print(f"Running {MC_RUNS:,} simulations...\n")

pass_r, floor_r, timeout_r, p10, med, p90 = run_mc(WR, AVG_WIN_R, AVG_LOSS_R, "Actual")

needed   = TARGET - START_BAL
progress = (START_BAL - 70_000) / (TARGET - 70_000) * 100

print(f"{'═'*55}")
print(f"  MONTE CARLO  —  Phase 1 from current position\n")
print(f"  Starting balance   : £{START_BAL:,.0f}")
print(f"  Target             : £{TARGET:,.0f}  (need £{needed:,.0f} more)")
print(f"  Progress           : {progress:.1f}% of target reached")
print(f"  Hard floor         : £{FLOOR:,.0f}")
print(f"  Daily loss limit   : £{DAILY_LIMIT:,.0f}")
print(f"  {'─'*51}")
print(f"  System win rate    : {WR*100:.1f}%")
print(f"  Avg win            : {AVG_WIN_R:.2f}R")
print(f"  Avg loss           : {AVG_LOSS_R:.2f}R")
print(f"  Profit factor      : {(WR*AVG_WIN_R)/((1-WR)*AVG_LOSS_R):.2f}")
print(f"  Avg risk / trade   : £{AVG_RISK:.0f}  (scales with balance)")
print(f"  Trades per day     : {LAMBDA:.1f} avg")
print(f"  {'─'*51}")
print(f"  PASS rate          : {pass_r:.1f}%")
print(f"  Floor hit rate     : {floor_r:.1f}%")
print(f"  Timeout rate       : {timeout_r:.1f}%  (>{MAX_DAYS} days)")
if med:
    print(f"  Days to pass       : {p10} (10th pct)  {med} (median)  {p90} (90th pct)")
print(f"{'═'*55}")

# Expected daily profit
exp_r_per_trade = WR * AVG_WIN_R - (1 - WR) * AVG_LOSS_R
exp_daily       = exp_r_per_trade * AVG_RISK * LAMBDA
days_expected   = needed / exp_daily

print(f"\n  Expected edge per trade : {exp_r_per_trade:.3f}R")
print(f"  Expected daily profit   : £{exp_daily:.0f}")
print(f"  Days to target (naive)  : {days_expected:.0f}")

# Daily loss limit check — worst realistic day
worst_day = LAMBDA * 2 * AVG_RISK * AVG_LOSS_R  # 2x trades all losing
print(f"\n  Worst realistic day     : £{worst_day:.0f} loss  "
      f"({'within' if worst_day <= DAILY_LIMIT else 'BREACHES'} daily limit)")

# Compare with original MC parameters
print(f"\n{'─'*55}")
print(f"  COMPARISON WITH ORIGINAL MC PARAMETERS\n")
old_wr, old_win_r, old_loss_r = 0.518, 2.13, 1.15
old_pf = (old_wr * old_win_r) / ((1 - old_wr) * old_loss_r)
pass_old, *_ = run_mc(old_wr, old_win_r, old_loss_r, "Old", seed=42)

print(f"  {'':25} {'Original':>12}  {'Actual':>12}")
print(f"  {'─'*25} {'─'*12}  {'─'*12}")
print(f"  {'Win rate':25} {old_wr*100:>11.1f}%  {WR*100:>11.1f}%")
print(f"  {'Avg win':25} {old_win_r:>11.2f}R  {AVG_WIN_R:>11.2f}R")
print(f"  {'Avg loss':25} {old_loss_r:>11.2f}R  {AVG_LOSS_R:>11.2f}R")
print(f"  {'Profit factor':25} {old_pf:>12.2f}  {(WR*AVG_WIN_R)/((1-WR)*AVG_LOSS_R):>12.2f}")
print(f"  {'─'*25} {'─'*12}  {'─'*12}")
print(f"  {'PASS rate':25} {pass_old:>11.1f}%  {pass_r:>11.1f}%")
print(f"{'─'*55}")
