"""
mc_current_scenario.py  -  Monte Carlo for current FTMO position
=================================================================
Simulates the remaining challenge from Harry's exact current state:

  Starting balance : £67,624  (after V3 losses + V4 bug losses)
  FTMO target      : £77,000  (fixed - 10% on original £70k)
  FTMO floor       : £63,000  (fixed - 10% drawdown on original £70k)
  FTMO daily limit : £3,500   (fixed - 5% of original £70k)

Uses trade-level statistics from the 8.5-year V4 REALISTIC stress test:
  Win rate   : 51.8%
  Profit factor: 1.98
  Avg trades/day: 3.2 (Poisson distributed)
  Avg risk/trade: 0.58% of £70k equity = £406

Run: python mc_current_scenario.py
"""
import numpy as np
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ── FTMO parameters (absolute, based on original £70k) ────────────────────────
START_BAL    = 67_624   # current balance
TARGET       = 77_000   # must reach this to pass Phase 1
FLOOR        = 63_000   # breach = immediate fail
DAILY_LIMIT  = 3_500    # single day loss limit
MC_RUNS      = 50_000   # simulations

# ── Trade-level stats from V4 REALISTIC stress test ───────────────────────────
WIN_RATE     = 0.518    # 51.8% win rate
PF           = 1.98     # profit factor
AVG_RISK_GBP = 406      # avg £ at risk per trade (0.58% of £70k)
LAMBDA       = 3.2      # avg trades per day (Poisson)
AVG_LOSS_R   = 1.15     # avg loss in R (includes spread/slip costs)
# Derive avg win from PF and win rate
# PF = (WR * avg_win) / ((1-WR) * avg_loss)
AVG_WIN_R    = PF * (1 - WIN_RATE) * AVG_LOSS_R / WIN_RATE  # ~2.13R

def simulate_day(eq):
    """Simulate one trading day. Returns daily P&L."""
    n_trades = np.random.poisson(LAMBDA)
    if n_trades == 0:
        return 0.0
    outcomes = np.random.random(n_trades)
    pnl = 0.0
    for o in outcomes:
        risk = AVG_RISK_GBP * (eq / 70_000)  # scale risk with account size
        if o < WIN_RATE:
            pnl += risk * AVG_WIN_R
        else:
            pnl -= risk * AVG_LOSS_R
    return pnl

def run_mc():
    passes, floors, daily_fails = 0, 0, 0
    days_to_pass_list = []

    for _ in range(MC_RUNS):
        bal = float(START_BAL)
        passed = floored = daily_failed = False

        for day in range(300):  # max 300 trading days
            daily_pnl = simulate_day(bal)

            # Daily loss limit check
            if daily_pnl < -DAILY_LIMIT:
                floored = True
                daily_failed = True
                break

            bal += daily_pnl

            if bal <= FLOOR:
                floored = True
                break
            if bal >= TARGET:
                passed = True
                days_to_pass_list.append(day + 1)
                break

        if passed:
            passes += 1
        elif floored:
            floors += 1
            if daily_failed:
                daily_fails += 1

    n = MC_RUNS
    pass_r    = passes / n * 100
    floor_r   = floors / n * 100
    timeout_r = (n - passes - floors) / n * 100
    avg_days  = np.mean(days_to_pass_list) if days_to_pass_list else None
    return pass_r, floor_r, timeout_r, daily_fails/n*100, avg_days

# ── Also run clean-start scenario for comparison ──────────────────────────────
def run_mc_clean():
    passes = 0
    for _ in range(MC_RUNS):
        bal = 70_000.0
        for day in range(300):
            daily_pnl = simulate_day(bal)
            if daily_pnl < -DAILY_LIMIT:
                break
            bal += daily_pnl
            if bal <= FLOOR:
                break
            if bal >= TARGET:
                passes += 1
                break
    return passes / MC_RUNS * 100

print(f"Running {MC_RUNS:,} Monte Carlo simulations...")
print(f"  Trade model: WR={WIN_RATE*100:.1f}% | PF={PF} | "
      f"~{LAMBDA} trades/day | avg risk £{AVG_RISK_GBP}")
print(f"\n  CURRENT POSITION:")
print(f"  Start:  £{START_BAL:,}")
print(f"  Target: £{TARGET:,}  (need +£{TARGET-START_BAL:,})")
print(f"  Floor:  £{FLOOR:,}   (room: £{START_BAL-FLOOR:,})")

pass_r, floor_r, timeout_r, daily_fail_r, avg_days = run_mc()

print(f"\n{'='*50}")
print(f"  PASS  (reach £77k)    : {pass_r:.1f}%")
print(f"  FLOOR (hit £63k)      : {floor_r:.1f}%")
print(f"  TIMEOUT (>300 days)   : {timeout_r:.1f}%")
print(f"  Daily limit breach    : {daily_fail_r:.1f}%")
if avg_days:
    print(f"  Avg days to pass      : {avg_days:.0f} trading days (~{avg_days/21:.1f} months)")
print(f"{'='*50}")

print(f"\nRunning clean-start comparison...")
clean_pass = run_mc_clean()
print(f"  Clean start (£70k) pass rate : {clean_pass:.1f}%")
print(f"  Current position pass rate   : {pass_r:.1f}%")
print(f"  Cost of early losses         : -{clean_pass - pass_r:.1f} percentage points")
