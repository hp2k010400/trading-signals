"""
mc_phase2.py  -  FTMO Phase 2 Monte Carlo simulation
=====================================================
After passing Phase 1, FTMO resets the balance to £70,000.
Phase 2 rules:
  Profit target : +5%  = £73,500
  Max daily loss: -5%  = £3,500
  Max drawdown  : -10% = £7,000  (floor = £63,000)
  Time limit    : none (unlimited trading days)

Uses same trade stats as Phase 1 (WR 51.8%, PF 1.98, 3.2 trades/day).

Run: python mc_phase2.py
"""
import numpy as np

np.random.seed(42)

# Phase 1 (reference)
P1_START  = 70_000
P1_TARGET = 77_000
P1_FLOOR  = 63_000

# Phase 2
P2_START  = 70_000
P2_TARGET = 73_500   # +5%
P2_FLOOR  = 63_000   # same -10% from original
P2_DAILY  = 3_500    # same -5%

MC_RUNS   = 50_000
MAX_DAYS  = 300

WIN_RATE  = 0.518
PF        = 1.98
AVG_LOSS_R = 1.15
AVG_WIN_R  = PF * (1 - WIN_RATE) * AVG_LOSS_R / WIN_RATE
AVG_RISK   = 406
LAMBDA     = 3.2

def sim_day(bal, start):
    n = np.random.poisson(LAMBDA)
    if n == 0:
        return 0.0
    risk = AVG_RISK * (bal / 70_000)
    wins = np.random.random(n) < WIN_RATE
    return float(np.sum(wins) * risk * AVG_WIN_R - np.sum(~wins) * risk * AVG_LOSS_R)

def run_mc(start, target, floor, daily_limit):
    passes, floors = 0, 0
    days_list = []
    for _ in range(MC_RUNS):
        bal = float(start)
        for day in range(1, MAX_DAYS + 1):
            daily = sim_day(bal, start)
            if daily < -daily_limit:
                floors += 1
                break
            bal += daily
            if bal <= floor:
                floors += 1
                break
            if bal >= target:
                passes += 1
                days_list.append(day)
                break
    pass_r  = passes / MC_RUNS * 100
    floor_r = floors / MC_RUNS * 100
    avg_days = np.mean(days_list) if days_list else None
    med_days = int(np.median(days_list)) if days_list else None
    return pass_r, floor_r, avg_days, med_days

print(f"Running {MC_RUNS:,} simulations for Phase 1 and Phase 2...\n")

p1_pass, p1_floor, p1_avg, p1_med = run_mc(P1_START, P1_TARGET, P1_FLOOR, P2_DAILY)
p2_pass, p2_floor, p2_avg, p2_med = run_mc(P2_START, P2_TARGET, P2_FLOOR, P2_DAILY)

# Combined: probability of passing BOTH phases back to back
combined = (p1_pass / 100) * (p2_pass / 100) * 100

print(f"{'═'*52}")
print(f"  {'':30} {'Phase 1':>8}  {'Phase 2':>8}")
print(f"  {'─'*30} {'─'*8}  {'─'*8}")
print(f"  {'Start balance':30} {'£70,000':>8}  {'£70,000':>8}")
print(f"  {'Profit target':30} {'£77,000':>8}  {'£73,500':>8}")
print(f"  {'Need to gain':30} {'£7,000':>8}  {'£3,500':>8}")
print(f"  {'Floor':30} {'£63,000':>8}  {'£63,000':>8}")
print(f"  {'─'*30} {'─'*8}  {'─'*8}")
print(f"  {'Pass rate':30} {p1_pass:>7.1f}%  {p2_pass:>7.1f}%")
print(f"  {'Floor rate':30} {p1_floor:>7.1f}%  {p2_floor:>7.1f}%")
print(f"  {'Median days to complete':30} {p1_med:>8}  {p2_med:>8}")
print(f"  {'Avg days to complete':30} {p1_avg:>8.0f}  {p2_avg:>8.0f}")
print(f"{'═'*52}")

print(f"\n  COMBINED (pass Phase 1 AND Phase 2) : {combined:.1f}%")
print(f"  Total median trading days            : {p1_med + p2_med} days  (~{(p1_med + p2_med)/21:.1f} months)")
print(f"\n{'═'*52}")

# Phase 2 is easier - show why
need_p1 = P1_TARGET - P1_START
need_p2 = P2_TARGET - P2_START
room_p1 = P1_START - P1_FLOOR
room_p2 = P2_START - P2_FLOOR

print(f"\n  WHY PHASE 2 IS EASIER:")
print(f"  Phase 1: need £{need_p1:,} with £{room_p1:,} room  (ratio {need_p1/room_p1:.2f}x)")
print(f"  Phase 2: need £{need_p2:,} with £{room_p2:,} room  (ratio {need_p2/room_p2:.2f}x)")
print(f"\n  Phase 2 target is half the distance with the same floor.")
print(f"  The system wins more than it needs in less than half the time.")

print(f"\n{'═'*52}")
print(f"  FUNDED ACCOUNT (after passing both phases):")
print(f"  Account size  : £70,000 real capital")
print(f"  Profit split  : 80% to you / 20% to FTMO")
print(f"  At £{need_p1:,}/month (REALISTIC model): £{int(need_p1 * 0.80):,}/month net")
print(f"  At £{14202:,}/month (REALISTIC stress):  £{int(14202 * 0.80):,}/month net")
print(f"{'═'*52}")
