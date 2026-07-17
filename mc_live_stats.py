"""
mc_live_stats.py  -  Monte Carlo using exact current live statistics
=====================================================================
Plugs the real live account stats into the MC to answer:
"If these live numbers are genuine signal (not variance), am I in trouble?"

Live stats from FTMO dashboard (35 trades):
  Win rate      : 42.86%
  Avg profit    : £400.55
  Avg loss      : -£407.28
  Profit factor : 0.74
  RRR           : 0.98

Also runs a statistical significance test:
  Is 42.86% WR significantly different from 51.8% at 35 trades?
  How many trades before we can call it signal vs noise?

Run: python mc_live_stats.py
"""
import numpy as np
from math import sqrt, ceil

np.random.seed(42)

START_BAL   = 67_624
TARGET      = 77_000
FLOOR       = 63_000
DAILY_LIMIT = 3_500
MC_RUNS     = 50_000
MAX_DAYS    = 300
LAMBDA      = 3.2

# ── Live stats ─────────────────────────────────────────────────────────────────
LIVE_WR      = 0.4286
LIVE_AVG_WIN = 400.55
LIVE_AVG_LOSS = 407.28
LIVE_PF      = 0.74
LIVE_TRADES  = 35

# ── Backtest stats (reference) ─────────────────────────────────────────────────
BT_WR        = 0.518
BT_PF        = 1.98
AVG_RISK     = 406
AVG_LOSS_R   = 1.15
BT_AVG_WIN_R = BT_PF * (1 - BT_WR) * AVG_LOSS_R / BT_WR

# Derive live R-multiples from live £ stats
LIVE_AVG_WIN_R  = LIVE_AVG_WIN  / AVG_RISK
LIVE_AVG_LOSS_R = LIVE_AVG_LOSS / AVG_RISK

def run_mc(wr, avg_win_r, avg_loss_r, label):
    passes, floors = 0, 0
    days_list = []
    for _ in range(MC_RUNS):
        bal = float(START_BAL)
        for day in range(1, MAX_DAYS + 1):
            n = np.random.poisson(LAMBDA)
            if n == 0:
                continue
            risk = AVG_RISK * (bal / 70_000)
            wins = np.random.random(n) < wr
            daily = float(
                np.sum(wins) * risk * avg_win_r -
                np.sum(~wins) * risk * avg_loss_r
            )
            if daily < -DAILY_LIMIT:
                floors += 1
                break
            bal += daily
            if bal <= FLOOR:
                floors += 1
                break
            if bal >= TARGET:
                passes += 1
                days_list.append(day)
                break
    pass_r  = passes / MC_RUNS * 100
    floor_r = floors / MC_RUNS * 100
    med     = int(np.median(days_list)) if days_list else None
    return pass_r, floor_r, med

print(f"Running {MC_RUNS:,} simulations for each scenario...\n")

bt_pass,   bt_floor,   bt_med   = run_mc(BT_WR,   BT_AVG_WIN_R,   AVG_LOSS_R,      "Backtest")
live_pass, live_floor, live_med = run_mc(LIVE_WR,  LIVE_AVG_WIN_R, LIVE_AVG_LOSS_R, "Live")

print(f"{'═'*58}")
print(f"  {'':28} {'Backtest':>12}  {'Live (35T)':>12}")
print(f"  {'─'*28} {'─'*12}  {'─'*12}")
print(f"  {'Win rate':28} {BT_WR*100:>11.1f}%  {LIVE_WR*100:>11.2f}%")
print(f"  {'Profit factor':28} {BT_PF:>12.2f}  {LIVE_PF:>12.2f}")
print(f"  {'Avg win (R)':28} {BT_AVG_WIN_R:>11.2f}R  {LIVE_AVG_WIN_R:>11.2f}R")
print(f"  {'Avg loss (R)':28} {AVG_LOSS_R:>11.2f}R  {LIVE_AVG_LOSS_R:>11.2f}R")
print(f"  {'RRR (win/loss)':28} {BT_AVG_WIN_R/AVG_LOSS_R:>12.2f}  {LIVE_AVG_WIN_R/LIVE_AVG_LOSS_R:>12.2f}")
print(f"  {'─'*28} {'─'*12}  {'─'*12}")
print(f"  {'PASS rate':28} {bt_pass:>11.1f}%  {live_pass:>11.1f}%")
print(f"  {'FLOOR rate':28} {bt_floor:>11.1f}%  {live_floor:>11.1f}%")
if bt_med:
    print(f"  {'Median days to pass':28} {bt_med:>12}  ", end='')
    print(f"{live_med if live_med else 'N/A':>12}")
print(f"{'═'*58}")

# ── Statistical significance test ─────────────────────────────────────────────
print(f"\nSTATISTICAL SIGNIFICANCE  (is 42.86% real or noise?)\n")

# Standard error of WR at 35 trades
se_35 = sqrt(LIVE_WR * (1 - LIVE_WR) / LIVE_TRADES)
z_score = (BT_WR - LIVE_WR) / se_35
ci_low  = LIVE_WR - 1.96 * se_35
ci_high = LIVE_WR + 1.96 * se_35

print(f"  Observed WR       : {LIVE_WR*100:.2f}%  ({LIVE_TRADES} trades)")
print(f"  Backtest WR       : {BT_WR*100:.1f}%")
print(f"  95% CI on live WR : [{ci_low*100:.1f}%, {ci_high*100:.1f}%]")
print(f"  Z-score           : {z_score:.2f}  (>1.96 = statistically significant)")
print(f"  Significant?      : {'YES — real underperformance' if abs(z_score) > 1.96 else 'NO — consistent with backtest variance'}")

# How many trades to confirm significance
# Need z = 1.96, so n = (z * sigma / delta)^2
delta = BT_WR - LIVE_WR
sigma = sqrt(BT_WR * (1 - BT_WR))
n_needed = ceil((1.96 * sigma / delta) ** 2)
print(f"\n  Trades needed to confirm {LIVE_WR*100:.0f}% WR is real signal: {n_needed} trades")
print(f"  At {LAMBDA:.0f} trades/day that's ~{ceil(n_needed/LAMBDA)} trading days")

# ── Blended scenario (halfway between live and backtest) ──────────────────────
print(f"\n{'─'*58}")
print(f"BLENDED SCENARIO  (if live gradually converges to backtest)\n")

blend_wr      = (BT_WR + LIVE_WR) / 2
blend_win_r   = (BT_AVG_WIN_R + LIVE_AVG_WIN_R) / 2
blend_loss_r  = (AVG_LOSS_R + LIVE_AVG_LOSS_R) / 2
blend_pass, _, blend_med = run_mc(blend_wr, blend_win_r, blend_loss_r, "Blend")

print(f"  WR {LIVE_WR*100:.0f}% → {blend_wr*100:.0f}% (halfway to backtest)")
print(f"  Pass rate: {blend_pass:.1f}%  |  Median days: {blend_med}")
print(f"\n{'─'*58}")
print(f"  VERDICT:")
if live_pass >= 80:
    print(f"  Even if live stats are REAL, pass rate is {live_pass:.0f}%.")
    print(f"  35 trades is too small to call. Keep running.")
elif live_pass >= 50:
    print(f"  Live stats sustained would give {live_pass:.0f}% pass rate.")
    print(f"  Needs monitoring — wait for 100 trades before concluding.")
else:
    print(f"  Live stats sustained would give {live_pass:.0f}% pass rate.")
    print(f"  If WR stays at {LIVE_WR*100:.0f}% after 100 trades, the edge may be broken.")
print(f"{'─'*58}")
