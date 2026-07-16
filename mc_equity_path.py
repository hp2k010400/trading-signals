"""
mc_equity_path.py  -  Day-by-day equity path simulation
=========================================================
Shows HOW the account is expected to move, not just pass/fail.
Runs 10,000 simulated challenges from current position and shows:
  - Median path (what a typical run looks like)
  - 10th/90th percentile (realistic range)
  - How many sims have passed/failed by each day

Run: python mc_equity_path.py
"""
import numpy as np

np.random.seed(42)

START_BAL   = 67_624
TARGET      = 77_000
FLOOR       = 63_000
DAILY_LIMIT = 3_500
MC_RUNS     = 10_000
MAX_DAYS    = 40

WIN_RATE    = 0.518
PF          = 1.98
AVG_RISK    = 406
LAMBDA      = 3.2
AVG_LOSS_R  = 1.15
AVG_WIN_R   = PF * (1 - WIN_RATE) * AVG_LOSS_R / WIN_RATE

def sim_day(bal):
    n = np.random.poisson(LAMBDA)
    if n == 0:
        return 0.0
    risk = AVG_RISK * (bal / 70_000)
    wins = np.random.random(n) < WIN_RATE
    return float(np.sum(wins) * risk * AVG_WIN_R - np.sum(~wins) * risk * AVG_LOSS_R)

# Run all simulations, recording day-by-day balance
all_paths = np.full((MC_RUNS, MAX_DAYS + 1), np.nan)
all_paths[:, 0] = START_BAL

statuses = ['running'] * MC_RUNS

for run in range(MC_RUNS):
    bal = float(START_BAL)
    status = 'timeout'
    for day in range(1, MAX_DAYS + 1):
        if statuses[run] != 'running':
            break
        daily_pnl = sim_day(bal)
        if daily_pnl < -DAILY_LIMIT:
            bal = FLOOR - 1  # force floor
            all_paths[run, day] = bal
            status = 'floor'
            statuses[run] = 'floor'
            break
        bal += daily_pnl
        all_paths[run, day] = bal
        if bal <= FLOOR:
            status = 'floor'
            statuses[run] = 'floor'
            break
        if bal >= TARGET:
            status = 'pass'
            statuses[run] = 'pass'
            break
    else:
        statuses[run] = 'timeout'

# For each day, compute percentiles across still-active runs
print(f"\nDAY-BY-DAY EQUITY PATH  (start: £{START_BAL:,})")
print(f"Target: £{TARGET:,}  |  Floor: £{FLOOR:,}")
print(f"Based on {MC_RUNS:,} simulations  |  WR={WIN_RATE*100:.0f}%  PF={PF}\n")

header = f"{'Day':>4}  {'10th%':>8}  {'Median':>8}  {'90th%':>8}  {'Passed':>7}  {'Failed':>7}  {'Running':>8}"
print(header)
print("-" * len(header))

for day in range(0, MAX_DAYS + 1):
    # Get balances for this day across all runs that were still active
    day_vals = []
    passed_by_day = sum(1 for i in range(MC_RUNS) if statuses[i] == 'pass' and
                        not np.isnan(all_paths[i, day]) and all_paths[i, day] >= TARGET)
    failed_by_day = sum(1 for i in range(MC_RUNS) if statuses[i] == 'floor' and
                        not np.isnan(all_paths[i, day]))

    # Active = not yet resolved
    for i in range(MC_RUNS):
        val = all_paths[i, day]
        if not np.isnan(val) and FLOOR < val < TARGET:
            day_vals.append(val)

    n_passed = statuses[:MC_RUNS].count('pass') if day == MAX_DAYS else sum(
        1 for i in range(MC_RUNS)
        if statuses[i] == 'pass' and
        any(not np.isnan(all_paths[i, d]) and all_paths[i, d] >= TARGET
            for d in range(1, day + 1))
    )

    running = len(day_vals)

    if day_vals:
        p10 = np.percentile(day_vals, 10)
        med = np.percentile(day_vals, 50)
        p90 = np.percentile(day_vals, 90)
        print(f"{day:>4}  £{p10:>7,.0f}  £{med:>7,.0f}  £{p90:>7,.0f}  "
              f"{n_passed:>6,}  {MC_RUNS - running - n_passed:>6,}  {running:>7,}")
    elif day == 0:
        print(f"{day:>4}  £{START_BAL:>7,}  £{START_BAL:>7,}  £{START_BAL:>7,}  "
              f"{0:>6,}  {0:>6,}  {MC_RUNS:>7,}")

    if running < MC_RUNS * 0.01 and day > 5:
        print(f"       ... >99% of runs resolved by day {day}")
        break

# Summary
n_pass  = statuses.count('pass')
n_floor = statuses.count('floor')
n_time  = statuses.count('timeout')

pass_days = []
for i in range(MC_RUNS):
    if statuses[i] == 'pass':
        for d in range(1, MAX_DAYS + 1):
            v = all_paths[i, d]
            if not np.isnan(v) and v >= TARGET:
                pass_days.append(d)
                break

print(f"\n{'='*55}")
print(f"  PASS  : {n_pass/MC_RUNS*100:.1f}%  ({n_pass:,} of {MC_RUNS:,})")
print(f"  FLOOR : {n_floor/MC_RUNS*100:.1f}%  ({n_floor:,} of {MC_RUNS:,})")
if pass_days:
    print(f"\n  Median days to pass : {int(np.median(pass_days))} trading days")
    print(f"  Fastest 10%         : {int(np.percentile(pass_days, 10))} days")
    print(f"  Slowest 10%         : {int(np.percentile(pass_days, 90))} days")
print(f"{'='*55}")
print(f"\n  Avg daily gain (median path) : "
      f"£{(TARGET - START_BAL) / np.median(pass_days):.0f}/day")
print(f"  Avg trades that day          : ~{LAMBDA:.0f}")
print(f"  Avg per trade (net)          : "
      f"£{(TARGET - START_BAL) / np.median(pass_days) / LAMBDA:.0f}")
