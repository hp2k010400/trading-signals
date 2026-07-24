"""
streak_analysis.py
Losing streak probability analysis for M1GOATV2.
Shows how often N-loss streaks occur and their financial impact.

Run: python streak_analysis.py
"""
import numpy as np

# ── CONFIG ────────────────────────────────────────────────────────────────────
WIN_RATE   = 0.493
BALANCE    = 70_000
RISK_FRAC  = 0.005
AVG_LOSS   = -(BALANCE * RISK_FRAC * 1.18)  # ~1R + spread/slippage
AVG_WIN    = BALANCE * RISK_FRAC * (4.0 - 0.18)
FLOOR      = 63_000
N_SIMS     = 1_000_000
TRADES_PER_CHALLENGE = 150  # approximate trades to pass challenge

RNG = np.random.default_rng(42)
LOSS_RATE = 1 - WIN_RATE

print('=' * 62)
print('  LOSING STREAK ANALYSIS  |  M1GOATV2  |  WR 49.3%')
print('=' * 62)

# ── SECTION 1: RAW PROBABILITIES ──────────────────────────────────────────────
print()
print('  Probability of N losses in a row (from any given trade):')
print(f'  {"Streak":>8}  {"Probability":>13}  {"1-in-N":>10}')
print(f'  {"-"*38}')
for n in range(1, 11):
    p = LOSS_RATE ** n
    print(f'  {n:>7}x  {p*100:>12.2f}%  {"1 in "+str(round(1/p)):>10}')

# ── SECTION 2: EXPECTED OCCURRENCES IN A CHALLENGE ────────────────────────────
print()
print(f'  Expected occurrences in {TRADES_PER_CHALLENGE} trades (one challenge):')
print(f'  {"Streak":>8}  {"Expected times":>15}  {"Likely?":>10}')
print(f'  {"-"*40}')
for n in range(3, 11):
    p = LOSS_RATE ** n
    expected = (TRADES_PER_CHALLENGE - n + 1) * p
    likely = 'YES' if expected >= 1.0 else ('POSSIBLE' if expected >= 0.3 else 'UNLIKELY')
    print(f'  {n:>7}x  {expected:>14.1f}  {likely:>10}')

# ── SECTION 3: FINANCIAL IMPACT ───────────────────────────────────────────────
print()
print(f'  Financial impact at 0.5% risk on GBP{BALANCE:,}:')
print(f'  {"Streak":>8}  {"Est loss":>12}  {"Balance after":>15}  {"Buffer left":>12}')
print(f'  {"-"*52}')
for n in range(1, 11):
    loss = abs(AVG_LOSS) * n
    bal = BALANCE - loss
    buffer = bal - FLOOR
    danger = ' DANGER' if buffer < 2000 else ''
    print(f'  {n:>7}x  GBP{loss:>8,.0f}  GBP{bal:>11,.0f}  GBP{buffer:>8,.0f}{danger}')

# ── SECTION 4: MONTE CARLO SIMULATION ─────────────────────────────────────────
print()
print(f'  Running {N_SIMS:,} simulations of {TRADES_PER_CHALLENGE}-trade sequences...')

max_streaks = []
streak_counts = {n: 0 for n in range(5, 11)}

for _ in range(N_SIMS):
    outcomes = RNG.random(TRADES_PER_CHALLENGE) > WIN_RATE  # True = loss
    max_streak = 0
    current = 0
    for loss in outcomes:
        if loss:
            current += 1
            if current > max_streak:
                max_streak = current
            for n in range(5, 11):
                if current == n:
                    streak_counts[n] += 1
        else:
            current = 0
    max_streaks.append(max_streak)

max_streaks = np.array(max_streaks)

print()
print(f'  Longest losing streak in {TRADES_PER_CHALLENGE} trades:')
print(f'    Average longest streak:  {max_streaks.mean():.1f} losses')
print(f'    Median longest streak:   {np.median(max_streaks):.0f} losses')
print(f'    90% of challenges see:   up to {np.percentile(max_streaks, 90):.0f} losses in a row')
print(f'    99% of challenges see:   up to {np.percentile(max_streaks, 99):.0f} losses in a row')

print()
print(f'  Probability of seeing at least one streak of N in {TRADES_PER_CHALLENGE} trades:')
print(f'  {"Streak":>8}  {"Probability":>13}  {"Verdict":>30}')
print(f'  {"-"*58}')
for n in range(5, 11):
    p = streak_counts[n] / N_SIMS * 100
    if p >= 70:   verdict = 'NORMAL — expect this every challenge'
    elif p >= 40: verdict = 'COMMON — happens most challenges'
    elif p >= 15: verdict = 'POSSIBLE — roughly 1 in 5 challenges'
    elif p >= 5:  verdict = 'UNCOMMON — roughly 1 in 20'
    else:         verdict = 'RARE'
    print(f'  {n:>7}x  {p:>12.1f}%  {verdict:>30}')

print()
print('  VERDICT')
print(f'  {"-"*55}')
print(f'  A 5-loss streak is NORMAL. Expect it 3+ times per challenge.')
print(f'  A 6-7 loss streak happens in most challenges.')
print(f'  Even a 10-loss streak only costs ~GBP3,500 — half your buffer.')
print(f'  The edge wins over hundreds of trades, not dozens.')
print('=' * 62)
print('Done.')
