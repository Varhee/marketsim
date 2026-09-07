"""
Experiment: does having market makers actually keep a market calmer?

Runs two versions of the same market - one with market makers in the
agent population, one without - hits both with the same flash-crash
shock at the same tick, and compares how far price falls and how wide
the spread gets. This is the kind of thing the README points to as
"a real experiment" rather than just a demo, so it lives here as a
plain script you can run and read, not buried in a notebook.

Usage:
    python3 experiments/mm_liquidity_experiment.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import Side
from simulation import Simulation
from agents import NoiseTrader, MomentumTrader, MeanReversionTrader, MarketMaker, InstitutionalTrader


def run_market(with_market_makers: bool, seed: int, warmup=50, post_shock=100):
    agents = [
        NoiseTrader("noise-1"), NoiseTrader("noise-2"), NoiseTrader("noise-3"),
        MomentumTrader("momentum-1"),
        MeanReversionTrader("meanrev-1", size=50),
        InstitutionalTrader("institutional-1"),
    ]
    if with_market_makers:
        agents += [
            MarketMaker("marketmaker-1", max_inventory=4000, skew_sensitivity=0.00002),
            MarketMaker("marketmaker-2", max_inventory=4000, skew_sensitivity=0.00002),
        ]

    sim = Simulation(agents, starting_price=100.0, seed=seed)
    for _ in range(warmup):
        sim.step()

    pre_shock_price = sim.price_history[-1]
    scheduled_qty = 3000
    sim.agents["institutional-1"].schedule(Side.SELL, total_quantity=scheduled_qty, chunks=6)

    min_price = pre_shock_price
    max_spread = sim.book.spread() or 0.0
    for _ in range(post_shock):
        sim.step()
        min_price = min(min_price, sim.price_history[-1])
        spread = sim.book.spread()
        if spread is not None:
            max_spread = max(max_spread, spread)

    filled_qty = -sim.agents["institutional-1"].position  # position is negative shares after selling
    return {
        "pre_shock_price": pre_shock_price,
        "min_price": min_price,
        "final_price": sim.price_history[-1],
        "max_drawdown_pct": round((min_price - pre_shock_price) / pre_shock_price * 100, 2),
        "max_spread": round(max_spread, 3),
        "fill_rate_pct": round(filled_qty / scheduled_qty * 100, 1),
    }


def main():
    seeds = [1, 2, 3, 4, 5]
    with_mm = [run_market(True, s) for s in seeds]
    without_mm = [run_market(False, s) for s in seeds]

    def avg(rows, key):
        return round(sum(r[key] for r in rows) / len(rows), 3)

    print("Institutional liquidation, 5 seeds, market makers vs no market makers\n")
    print(f"{'':28}{'with MMs':>14}{'without MMs':>16}")
    print(f"{'avg max drawdown %':28}{avg(with_mm,'max_drawdown_pct'):>14}{avg(without_mm,'max_drawdown_pct'):>16}")
    print(f"{'avg max spread':28}{avg(with_mm,'max_spread'):>14}{avg(without_mm,'max_spread'):>16}")
    print(f"{'avg order fill rate %':28}{avg(with_mm,'fill_rate_pct'):>14}{avg(without_mm,'fill_rate_pct'):>16}")
    print()
    print("Per-seed drawdown %:")
    for s, w, wo in zip(seeds, with_mm, without_mm):
        print(f"  seed {s}: with MMs {w['max_drawdown_pct']:>7}% (filled {w['fill_rate_pct']:>5}%)   "
              f"without MMs {wo['max_drawdown_pct']:>7}% (filled {wo['fill_rate_pct']:>5}%)")
    print()
    print("Read this carefully: the 'without MMs' market barely moves, but the fill-rate")
    print("column shows why - most of the institutional order never executes, because")
    print("there's no resting liquidity to sell into. That's not stability, it's a market")
    print("that can't absorb the trade at all. Market makers make the crash *possible* by")
    print("making the order *fillable* - the real comparison is impact-per-share-filled,")
    print("not impact-per-market. This kind of counterintuitive result is exactly why the")
    print("bias-detector idea in the design brief matters: a headline number ('MMs make")
    print("crashes worse!') can be technically true and still be the wrong conclusion.")


if __name__ == "__main__":
    main()
