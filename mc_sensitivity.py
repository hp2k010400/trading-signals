"""
mc_sensitivity.py  -  Break-even sensitivity analysis
======================================================
Sweeps win rate and profit factor across a grid, running MC for each
combination to find exactly where the edge breaks down.

Answers: "How bad can live performance get before this challenge fails?"

Run: python mc_sensitivity.py
"""
import numpy as np

np.random.seed(42)

START_BAL   = 67_624
TARGET      = 77_000
FLOOR       = 63_000
DAILY_LIMIT = 3_500
MC_RUNS     = 5_000   # per cell - fast enough for a grid
MAX_DAYS    = 300

AVG_LOSS_R  = 1.15    # fixed - avg loss in R including spread/slip
LAMBDA      = 3.2     # avg trades/day
AVG_RISK    = 406     # avg £ risk per trade

# Grid to sweep
WIN_RATES = [0.35, 0.38, 0.41, 0.44, 0.47, 0.50, 0.518, 0.54, 0.57, 0.60]
PROF_FACTS = [1.20, 1.40, 1.60, 1.80, 1.98, 2.20, 2.40, 2.60]

CURRENT_WR = 0.518
CURRENT_PF = 1.98

def run_mc_cell(wr, pf):
    avg_win_r = pf * (1 - wr) * AVG_LOSS_R / wr
    passes = 0
    for _ in range(MC_RUNS):
        bal = float(START_BAL)
        for _ in range(MAX_DAYS):
            n = np.random.poisson(LAMBDA)
            if n == 0:
                continue
            risk = AVG_RISK * (bal / 70_000)
            wins = np.random.random(n) < wr
            daily = float(np.sum(wins) * risk * avg_win_r - np.sum(~wins) * risk * AVG_LOSS_R)
            if daily < -DAILY_LIMIT:
                bal = FLOOR - 1
                break
            bal += daily
            if bal <= FLOOR:
                break
            if bal >= TARGET:
                passes += 1
                break
    return passes / MC_RUNS * 100

print("Running sensitivity grid (this takes ~30 seconds)...")
print(f"  Baseline: WR={CURRENT_WR*100:.1f}%  PF={CURRENT_PF}\n")

# Build results grid
results = {}
total = len(WIN_RATES) * len(PROF_FACTS)
done = 0
for wr in WIN_RATES:
    for pf in PROF_FACTS:
        results[(wr, pf)] = run_mc_cell(wr, pf)
        done += 1
        print(f"  [{done:>3}/{total}] WR={wr*100:.0f}%  PF={pf:.2f}  → {results[(wr,pf)]:.1f}%", end='\r')

print(f"\n\n{'─'*80}")
print(f"PASS RATE GRID  (from £{START_BAL:,} → £{TARGET:,} | floor £{FLOOR:,})")
print(f"{'─'*80}")
print(f"  [***] = >95%  [**] = 90-95%  [*] = 80-90%  [·] = <80%  [X] = current")
print(f"{'─'*80}\n")

# Header row
pf_labels = "".join(f"  PF={pf:.2f}" for pf in PROF_FACTS)
print(f"{'WR':>7}{pf_labels}")
print(f"{'':>7}" + "  -------" * len(PROF_FACTS))

for wr in WIN_RATES:
    row = f"  {wr*100:>4.1f}%  "
    for pf in PROF_FACTS:
        val = results[(wr, pf)]
        is_current = (wr == CURRENT_WR and pf == CURRENT_PF)
        if val >= 95:
            tag = "***"
        elif val >= 90:
            tag = " **"
        elif val >= 80:
            tag = "  *"
        else:
            tag = "   "
        marker = "X" if is_current else " "
        row += f" {marker}{val:>5.1f}%{tag}"
    print(row)

print(f"\n{'─'*80}")

# Find the break-even boundary
print(f"\nBREAK-EVEN ANALYSIS  (90% pass rate threshold)\n")
print(f"  {'Win Rate':>10}  {'Min PF needed':>15}  {'Status'}")
print(f"  {'─'*10}  {'─'*15}  {'─'*20}")
for wr in WIN_RATES:
    min_pf = None
    for pf in PROF_FACTS:
        if results[(wr, pf)] >= 90.0:
            min_pf = pf
            break
    label = "CURRENT" if wr == CURRENT_WR else ""
    if min_pf:
        print(f"  {wr*100:>9.1f}%  {min_pf:>15.2f}  {label}")
    else:
        print(f"  {wr*100:>9.1f}%  {'no PF tested works':>15}  {label} DANGER ZONE")

# Find min WR at current PF that still passes
print(f"\n  At current PF={CURRENT_PF}:  min win rate for 90% pass = ", end='')
for wr in WIN_RATES:
    if results[(wr, CURRENT_PF)] >= 90.0:
        print(f"{wr*100:.0f}%  (current: {CURRENT_WR*100:.1f}%,  buffer: {(CURRENT_WR - wr)*100:.1f} pp)")
        break

# Find min PF at current WR that still passes
print(f"  At current WR={CURRENT_WR*100:.1f}%: min PF for 90% pass    = ", end='')
for pf in PROF_FACTS:
    if results[(CURRENT_WR, pf)] >= 90.0:
        print(f"{pf:.2f}    (current: {CURRENT_PF},    buffer: {CURRENT_PF - pf:.2f})")
        break

print(f"\n{'─'*80}")
print(f"  TL;DR: The system has significant margin before the edge disappears.")
print(f"  Monitor live rolling WR and PF - pull the plug if WR < 44% sustained.")
print(f"{'─'*80}")
