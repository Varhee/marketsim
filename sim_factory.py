"""
One place to build a "standard" market so the backend, the tests and
anyone poking around in a REPL all get the same population of agents.
Numbers here came from actually running the sim and nudging things
until a flash crash looked like a flash crash and not a flat line or a
death spiral - see the notes in engine tuning further down if you
want to push it around yourself.
"""

from simulation import Simulation
from agents import NoiseTrader, MomentumTrader, MeanReversionTrader, MarketMaker, InstitutionalTrader


def build_simulation(seed: int | None = None) -> Simulation:
    agents = [
        NoiseTrader("noise-1"),
        NoiseTrader("noise-2"),
        NoiseTrader("noise-3"),
        MomentumTrader("momentum-1"),
        MeanReversionTrader("meanrev-1", size=50),
        MeanReversionTrader("meanrev-2", window=15, z_threshold=1.0, size=40),
        MarketMaker("marketmaker-1", max_inventory=4000, skew_sensitivity=0.00002),
        MarketMaker("marketmaker-2", max_inventory=4000, skew_sensitivity=0.00002),
        InstitutionalTrader("institutional-1"),
    ]
    return Simulation(agents, starting_price=100.0, seed=seed)
