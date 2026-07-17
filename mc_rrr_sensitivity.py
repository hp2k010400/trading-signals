"""
mc_rrr_sensitivity.py  -  Risk:Reward Ratio sensitivity analysis
=================================================================
The live RRR is 0.98 (winners barely bigger than losers).
The backtest expects ~1.85 (winners nearly twice losers).

This sweeps RRR from 0.5 to 3.0 and shows the pass rate at each level,
for both backtest WR (51.8%) and live WR (42.86%).

Answers: "How much does a compressed RRR actually hurt the challenge?"

Run: python mc_rrr_sensitivity.py
"""
import numpy as np

np.random.seed(42)

START_BAL   = 67_624
TARGET      = 77_000
FLOOR       = 63_000
DAILY_LIMIT = 3_500
MC_RUNS     = 10_000
MAX_DAYS    = 300

AVG_LOSS_R  = 1.15
AVG_RISK    = 406
LAMBDA      = 3.2

BACKTEST_WR = 0.518
LIVE_WR     = 0.4286

RRR_VALUES  = [0.50, 0.75, 0.98, 1.10, 1.25, 1.50, 1.85, 2.00, 2.25, 2.50, 3.00]
LIVE_RRR    = 0.98
BACKTEST_RRR = 1.85

def run_mc_cell(wr, rrr):
    avg_win_r = rrr * AVG_LOSS_R
    pf = (wr * avg_win_r) / ((1 - wr) * AVG_LOSS_R)
    passes = 0
    for _ in range(MC_RUNS):
        bal = float(START_BAL)
        for _ in range(MAX_DAYS):
            n = np.random.poisson(LAMBDA)
            if n == 0:
                continue
            risk = AVG_RISK * (bal / 70_000)
            wins = np.random.random(n) < wr
            daily = float(
                np.sum(wins) * risk * avg_win_r -
                np.sum(~wins) * risk * AVG_LOSS_R
            )
            if daily < -DAILY_LIMIT:
                break
            bal += daily
            if bal <= FLOOR:
                break
            if bal >= TARGET:
                passes += 1
                break
    return passes / MC_RUNS * 100, pf

print("Running RRR sensitivity analysis...")
print(f"  Backtest RRR: {BACKTEST_RRR}  (avg win = {BACKTEST_RRR * AVG_LOSS_R:.2f}R)")
print(f"  Live RRR:     {LIVE_RRR}  (avg win = {LIVE_RRR * AVG_LOSS_R:.2f}R)")

results_bt = {}
results_live = {}
for rrr in RRR_VALUES:
    results_bt[rrr],   _ = run_mc_cell(BACKTEST_WR, rrr)
    results_live[rrr], _ = run_mc_cell(LIVE_WR, rrr)
    print(f"  RRR={rrr:.2f}  BT WR={BACKTEST_WR*100:.0f}%: {results_bt[rrr]:.1f}%  |  "
          f"Live WR={LIVE_WR*100:.0f}%: {results_live[rrr]:.1f}%", end='\r')

print(f"\n\n{'─'*70}")
print(f"PASS RATE vs RRR  (£{START_BAL:,} → £{TARGET:,} | floor £{FLOOR:,})")
print(f"{'─'*70}")
print(f"  [***] >95%   [**] 90-95%   [*] 80-90%   [ ] <80%")
print(f"  (L) = live RRR    (B) = backtest RRR\n")

print(f"  {'RRR':>6}  {'Avg Win':>8}  {'WR 51.8% (BT)':>16}  {'WR 42.9% (Live)':>18}")
print(f"  {'─'*6}  {'─'*8}  {'─'*16}  {'─'*18}")

for rrr in RRR_VALUES:
    avg_win = rrr * AVG_LOSS_R
    bt_val   = results_bt[rrr]
    live_val = results_live[rrr]

    def tag(v):
        if v >= 95: return "***"
        if v >= 90: return " **"
        if v >= 80: return "  *"
        return "   "

    bt_marker   = "(B)" if rrr == BACKTEST_RRR else "   "
    live_marker = "(L)" if rrr == LIVE_RRR     else "   "

    print(f"  {rrr:>6.2f}  {avg_win:>7.2f}R  "
          f"{bt_marker} {bt_val:>5.1f}%{tag(bt_val)}   "
          f"{live_marker} {live_val:>5.1f}%{tag(live_val)}")

print(f"\n{'─'*70}")

# Find crossover points
print(f"\nCROSSOVER POINTS (where pass rate drops below 90%)\n")

for label, wr, res in [("Backtest WR 51.8%", BACKTEST_WR, results_bt),
                        ("Live WR 42.9%",     LIVE_WR,     results_live)]:
    min_rrr = None
    for rrr in RRR_VALUES:
        if res[rrr] >= 90.0:
            min_rrr = rrr
            break
    if min_rrr:
        print(f"  {label}: min RRR for 90% pass = {min_rrr:.2f}  "
              f"(live is {LIVE_RRR}, buffer = {LIVE_RRR - min_rrr:+.2f})")
    else:
        print(f"  {label}: no tested RRR achieves 90% pass — edge is broken")

print(f"\n{'─'*70}")
print(f"  KEY QUESTION: Is live RRR 0.98 a real signal or 35-trade variance?")
print(f"  → Run mc_live_stats.py for the full picture.")
print(f"{'─'*70}")
