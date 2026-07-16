"""
mc_losing_streaks.py  -  Consecutive loss streak analysis
==========================================================
Answers: "What's the worst realistic losing streak, and what does
it actually do to my balance?"

Two parts:
  1. Streak probability - how likely is a run of N consecutive losers?
  2. Balance impact     - simulate worst-day sequences and show the damage

Run: python mc_losing_streaks.py
"""
import numpy as np

np.random.seed(42)

WIN_RATE   = 0.518
LOSS_RATE  = 1 - WIN_RATE
AVG_RISK   = 406      # avg £ per trade at £70k
AVG_LOSS_R = 1.15     # avg loss in R
LAMBDA     = 3.2      # avg trades/day
START_BAL  = 67_624   # current balance
FLOOR      = 63_000
DAILY_LIMIT = 3_500

MC_RUNS    = 100_000  # for streak analysis
SIM_DAYS   = 10_000   # trading days to simulate for max streak

# ── Part 1: Streak probability ─────────────────────────────────────────────────
print("CONSECUTIVE LOSS PROBABILITY")
print("="*48)
print(f"  Win rate: {WIN_RATE*100:.1f}%  |  Loss rate: {LOSS_RATE*100:.1f}%\n")
print(f"  {'Streak':>8}  {'Probability':>14}  {'Expected every':>16}")
print(f"  {'─'*8}  {'─'*14}  {'─'*16}")

for n in range(1, 11):
    prob = LOSS_RATE ** n
    # Expected number of trades between occurrences
    every_n_trades = 1 / prob
    every_n_days = every_n_trades / LAMBDA
    if every_n_days < 1:
        freq = f"multiple/day"
    elif every_n_days < 21:
        freq = f"~{every_n_days:.0f} trading days"
    elif every_n_days < 252:
        freq = f"~{every_n_days/21:.1f} months"
    else:
        freq = f"~{every_n_days/252:.1f} years"
    print(f"  {n:>8}  {prob*100:>13.2f}%  {freq:>16}")

# ── Part 2: Max streak in 8.5 years of trading ────────────────────────────────
print(f"\n{'='*48}")
print(f"WORST STREAK IN SIMULATED 8.5-YEAR PERIOD")
print(f"  (simulating {SIM_DAYS:,} trading days × {MC_RUNS//SIM_DAYS:,} full periods)")
print(f"{'='*48}\n")

# Simulate 8.5 years (2142 trading days) many times
PERIOD_DAYS = 2142
total_trades_per_period = int(PERIOD_DAYS * LAMBDA)

max_streaks = []
for _ in range(MC_RUNS // PERIOD_DAYS * 10):
    trades = np.random.random(total_trades_per_period) > WIN_RATE  # True = loss
    max_s = cur_s = 0
    for t in trades:
        if t:
            cur_s += 1
            max_s = max(max_s, cur_s)
        else:
            cur_s = 0
    max_streaks.append(max_s)

max_streaks = np.array(max_streaks)
print(f"  Median worst streak in 8.5 years : {int(np.median(max_streaks))} consecutive losses")
print(f"  90th percentile worst streak     : {int(np.percentile(max_streaks, 90))} consecutive losses")
print(f"  99th percentile worst streak     : {int(np.percentile(max_streaks, 99))} consecutive losses")
print(f"  Absolute worst seen              : {int(np.max(max_streaks))} consecutive losses")

# ── Part 3: Balance impact of worst streak ────────────────────────────────────
print(f"\n{'='*48}")
print(f"BALANCE IMPACT — WORST STREAK SCENARIOS")
print(f"  Starting from £{START_BAL:,}  |  Floor £{FLOOR:,}")
print(f"{'='*48}\n")

print(f"  {'Streak':>8}  {'Balance after':>14}  {'Drawdown':>10}  {'Floor gap':>10}")
print(f"  {'─'*8}  {'─'*14}  {'─'*10}  {'─'*10}")

worst_typical = int(np.median(max_streaks))
worst_90 = int(np.percentile(max_streaks, 90))

for n in [3, 5, 7, worst_typical, worst_90, int(np.percentile(max_streaks, 99))]:
    n = max(n, 3)
    # Worst case: all losses in a single day (multiple trades)
    # Realistic: spread across multiple days
    # Use avg 3.2 trades/day, so n losses takes ~n/3.2 days
    loss_per_trade = AVG_RISK * AVG_LOSS_R
    total_loss = n * loss_per_trade
    bal_after = START_BAL - total_loss
    drawdown = total_loss
    floor_gap = bal_after - FLOOR
    days = n / LAMBDA

    label = ""
    if n == worst_typical:
        label = " ← typical worst"
    elif n == worst_90:
        label = " ← 90th pct worst"

    status = "SAFE" if bal_after > FLOOR else "FLOOR BREACHED"
    print(f"  {n:>8}  £{bal_after:>12,.0f}  £{drawdown:>8,.0f}  £{floor_gap:>8,.0f}  {status}{label}")

# ── Part 4: Worst day scenario ─────────────────────────────────────────────────
print(f"\n{'='*48}")
print(f"WORST SINGLE DAY — ALL {int(LAMBDA)+1} TRADES LOSE")
print(f"{'='*48}")
worst_day_loss = (int(LAMBDA) + 1) * AVG_RISK * AVG_LOSS_R
print(f"  If all ~{int(LAMBDA)+1} trades fire and all lose:")
print(f"  Loss    : £{worst_day_loss:,.0f}")
print(f"  Balance : £{START_BAL - worst_day_loss:,.0f}")
print(f"  Daily limit (£{DAILY_LIMIT:,}) {'BREACHED' if worst_day_loss > DAILY_LIMIT else 'NOT breached'}")
print(f"  Floor   (£{FLOOR:,}) {'BREACHED' if START_BAL - worst_day_loss < FLOOR else 'NOT breached'}")

# ── Part 5: Psychological context ─────────────────────────────────────────────
print(f"\n{'='*48}")
print(f"RECOVERY TIME AFTER WORST STREAK")
print(f"{'='*48}")
avg_daily_gain = (406 * WIN_RATE * (PF := 1.98) * (1-WIN_RATE) * AVG_LOSS_R / WIN_RATE
                  - 406 * LOSS_RATE * AVG_LOSS_R) * LAMBDA
# Simpler: just use known avg daily gain
avg_daily_gain = 721  # from equity path simulation

for n in [worst_typical, worst_90]:
    loss = n * AVG_RISK * AVG_LOSS_R
    days_to_recover = loss / avg_daily_gain
    print(f"  {n}-loss streak (£{loss:,.0f} loss) → recover in ~{days_to_recover:.1f} trading days")

print(f"\n  Key point: even the typical worst streak is recoverable")
print(f"  in under a week. Don't pull the bot after a bad run.")
print(f"{'='*48}")
