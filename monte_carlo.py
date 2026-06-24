"""
monte_carlo.py — FTMO Challenge Monte Carlo Simulation
Runs 10,000 simulated challenge attempts using the real trade distribution
from the v5.10 backtest.

Answers:
  1. Probability of passing FTMO Phase 1 (£70k → +10% before -10%)
  2. Probability of passing Phase 2 (£70k → +5% before -10%, 60 days)
  3. Expected maximum drawdown during a challenge attempt
  4. 5th / 50th / 95th percentile equity at end of challenge window

Run: python monte_carlo.py
"""

import numpy as np
import sys, importlib

# ── Config ────────────────────────────────────────────────────────────────────
N_SIMS        = 10_000
ACCOUNT       = 70_000
P1_TARGET     = 7_000    # Phase 1: +10%
P1_DD_LIMIT   = 7_000    # Phase 1: max -10% from start
P1_DAYS       = 30       # Phase 1: max 30 trading days, min 10
P2_TARGET     = 3_500    # Phase 2: +5%
P2_DD_LIMIT   = 7_000    # Phase 2: max -10% from start
P2_DAYS       = 60       # Phase 2: max 60 trading days
DAILY_DD_CAP  = 3_500    # circuit breaker stops at -5% daily (FTMO limit)

# ── Load trades from backtest ─────────────────────────────────────────────────
print("Loading trade data from backtest...")
sys.path.insert(0, '.')
import backtest_system_combined as bt

bt.BT_FROM = None
bt.BT_TO   = None
bt.PARTIAL_R = None
stats = bt.run_portfolio(print_table=False)
trades = np.array([t for res in bt.results for t in res['trades']], dtype=float)
print(f"  {len(trades)} trades loaded | WR {stats['wr']:.1f}% | PF {stats['pf']:.2f} | "
      f"Avg win £{stats['avg_w']:,.0f} | Avg loss £{stats['avg_l']:,.0f}")

# Trades per trading day (504 trading days in 2 years)
tpd = len(trades) / 504.0

# ── Simulation ────────────────────────────────────────────────────────────────
def simulate_challenge(trades, max_days, target, dd_limit, n_sims=N_SIMS):
    """
    Bootstrap simulate n_sims challenge attempts.
    Each day, sample a Poisson(tpd) number of trades from the pool with replacement.
    Returns arrays of: pass/fail bool, max_drawdown, final_equity, days_taken
    """
    rng = np.random.default_rng(42)
    passed      = np.zeros(n_sims, dtype=bool)
    max_dds     = np.zeros(n_sims)
    final_eqs   = np.full(n_sims, float(ACCOUNT))
    days_taken  = np.full(n_sims, max_days)

    for sim in range(n_sims):
        equity  = float(ACCOUNT)
        peak_eq = float(ACCOUNT)
        max_dd  = 0.0
        failed  = False

        for day in range(max_days):
            # Random number of trades today
            n_today = max(1, rng.poisson(tpd))
            day_trades = rng.choice(trades, size=n_today, replace=True)
            day_pnl = float(day_trades.sum())

            # Apply daily circuit breaker
            if day_pnl < -DAILY_DD_CAP:
                day_pnl = -DAILY_DD_CAP

            equity  += day_pnl
            peak_eq  = max(peak_eq, equity)
            dd       = peak_eq - equity
            max_dd   = max(max_dd, dd)

            # Check drawdown from START (FTMO measures from initial balance)
            start_dd = ACCOUNT - equity
            if start_dd >= dd_limit:
                failed = True
                days_taken[sim] = day + 1
                break

            if equity - ACCOUNT >= target:
                passed[sim]    = True
                days_taken[sim] = day + 1
                break

        max_dds[sim]   = max_dd
        final_eqs[sim] = equity

    return passed, max_dds, final_eqs, days_taken


# ── Phase 1 ───────────────────────────────────────────────────────────────────
print(f"\nRunning {N_SIMS:,} Phase 1 simulations...")
p1_passed, p1_dds, p1_eqs, p1_days = simulate_challenge(
    trades, P1_DAYS, P1_TARGET, P1_DD_LIMIT)

# ── Phase 2 (conditional on passing Phase 1) ──────────────────────────────────
print(f"Running {N_SIMS:,} Phase 2 simulations...")
p2_passed, p2_dds, p2_eqs, p2_days = simulate_challenge(
    trades, P2_DAYS, P2_TARGET, P2_DD_LIMIT)

# ── Results ───────────────────────────────────────────────────────────────────
W = 65
print("\n" + "="*W)
print("  FTMO CHALLENGE MONTE CARLO RESULTS")
print("="*W)

p1_rate = p1_passed.mean() * 100
p2_rate = p2_passed.mean() * 100
combined = p1_rate * p2_rate / 100

print(f"""
  PASS RATES
  ──────────────────────────────────────────────────
  Phase 1 (30 days, +£7,000, max -£7,000):  {p1_rate:>6.1f}%
  Phase 2 (60 days, +£3,500, max -£7,000):  {p2_rate:>6.1f}%
  Combined (P1 then P2):                     {combined:>6.1f}%
""")

print(f"  PHASE 1 EQUITY AT END OF WINDOW (all sims)")
print(f"  ──────────────────────────────────────────────────")
for pct, label in [(5,'Worst 5%'), (25,'25th pct'), (50,'Median'), (75,'75th pct'), (95,'Best 5%')]:
    eq = np.percentile(p1_eqs, pct)
    print(f"  {label:<12}  £{eq:>8,.0f}  ({(eq-ACCOUNT)/ACCOUNT*100:+.1f}%)")

print(f"""
  PHASE 1 MAX DRAWDOWN (from peak during run)
  ──────────────────────────────────────────────────
  Median max DD:   £{np.median(p1_dds):>7,.0f}  ({np.median(p1_dds)/ACCOUNT*100:.1f}%)
  95th pct max DD: £{np.percentile(p1_dds,95):>7,.0f}  ({np.percentile(p1_dds,95)/ACCOUNT*100:.1f}%)
""")

p1_pass_sims = p1_days[p1_passed]
if len(p1_pass_sims):
    print(f"  DAYS TO PASS PHASE 1 (passing sims only)")
    print(f"  ──────────────────────────────────────────────────")
    print(f"  Fastest:  {p1_pass_sims.min():.0f} days")
    print(f"  Median:   {np.median(p1_pass_sims):.0f} days")
    print(f"  Slowest:  {p1_pass_sims.max():.0f} days")

print(f"""
  INTERPRETATION
  ──────────────────────────────────────────────────""")

if p1_rate >= 70:
    verdict = "✅ Strong edge — high probability of passing"
elif p1_rate >= 50:
    verdict = "⚠️  Decent edge — worth attempting, expect variance"
elif p1_rate >= 30:
    verdict = "⚠️  Marginal — consider more live data before paying £489"
else:
    verdict = "❌ Too risky — system needs more validation first"

print(f"  Phase 1 pass rate {p1_rate:.1f}%  →  {verdict}")
print(f"  At {p1_rate:.1f}% per attempt: expect to pass in ~{100/p1_rate:.1f} tries")
print(f"  Cost to funded: ~£{489 * (100/p1_rate):.0f} expected (£489 per attempt)")
print()
