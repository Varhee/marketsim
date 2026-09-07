"""
Glues the order book, matching engine and agent population together
into something that can be stepped forward one tick at a time. This is
deliberately the only place that knows about "ticks" - the engine and
the agents don't care what a tick is, they just react to what they're
shown.
"""

from __future__ import annotations
import random
import statistics
from typing import List, Optional

from engine.order_book import OrderBook, Side
from engine.matching_engine import MatchingEngine
from agents.base import Agent


class Simulation:
    def __init__(self, agents: List[Agent], symbol: str = "SIM", starting_price: float = 100.0, seed: Optional[int] = None):
        if seed is not None:
            random.seed(seed)
        self.book = OrderBook(symbol)
        self.engine = MatchingEngine(self.book)
        self.agents = {a.agent_id: a for a in agents}
        self.price_history: List[float] = [starting_price]
        self.volatility_history: List[float] = [0.0]
        self.tick_count = 0
        self.total_volume = 0

        # seed the book with a resting quote so there's something to trade against
        self.book.last_trade_price = starting_price

    def step(self) -> dict:
        """Advance the market one tick. Returns a snapshot for the caller."""
        self.tick_count += 1
        tick_trades = []

        # randomising agent order each tick avoids any one agent always
        # getting first crack at the book, which would bias the sim
        agent_ids = list(self.agents.keys())
        random.shuffle(agent_ids)

        for agent_id in agent_ids:
            agent = self.agents[agent_id]
            for order in agent.act(self.book, self.price_history):
                trades = self.engine.submit(order)
                for t in trades:
                    tick_trades.append(t)
                    self.total_volume += t.quantity
                    buyer = self.agents.get(t.buyer_id)
                    seller = self.agents.get(t.seller_id)
                    if buyer:
                        buyer.on_fill(Side.BUY, t.price, t.quantity)
                    if seller:
                        seller.on_fill(Side.SELL, t.price, t.quantity)

        current_price = self.book.mid_price() or self.price_history[-1]
        self.price_history.append(current_price)
        self.volatility_history.append(self.realized_volatility())
        # keep unbounded history off the hot path in memory for very long runs
        if len(self.volatility_history) > 5000:
            self.volatility_history = self.volatility_history[-2000:]

        return {
            "tick": self.tick_count,
            "price": current_price,
            "trades": tick_trades,
            "depth": self.book.depth(),
            "spread": self.book.spread(),
        }

    # -- metrics used by the dashboard / research lab ---------------------

    def realized_volatility(self, window: int = 30) -> float:
        recent = self.price_history[-window:]
        if len(recent) < 2:
            return 0.0
        returns = [
            (recent[i] - recent[i - 1]) / recent[i - 1]
            for i in range(1, len(recent))
            if recent[i - 1] != 0
        ]
        if len(returns) < 2:
            return 0.0
        return round(statistics.pstdev(returns) * (252 ** 0.5), 4)  # annualised-ish, tick-scale toy metric

    def liquidity_score(self) -> float:
        """Crude proxy: total resting volume near best bid/ask, spread-adjusted."""
        spread = self.book.spread()
        volume = self.book.total_bid_volume() + self.book.total_ask_volume()
        if not spread or spread == 0:
            return round(volume, 2)
        return round(volume / spread, 2)

    def inject_shock(self, kind: str = "flash_crash") -> dict:
        """
        Manual market shock, independent of the scheduled agent behaviour.
        Mirrors the 'INJECT MARKET SHOCK' button from the design doc.
        Returns a small record of what was triggered, so the caller can
        log it and report before/after numbers later.
        """
        institutional = next(
            (a for a in self.agents.values() if a.__class__.__name__ == "InstitutionalTrader"),
            None,
        )
        if kind == "flash_crash" and institutional:
            institutional.schedule(Side.SELL, total_quantity=4500, chunks=6)
        elif kind == "liquidity_crisis":
            for a in self.agents.values():
                if a.__class__.__name__ == "MarketMaker":
                    a.max_inventory = 1  # forces makers to pull quotes almost immediately
        elif kind == "volatility_spike":
            for a in self.agents.values():
                if a.__class__.__name__ == "NoiseTrader":
                    a.activity = min(1.0, a.activity * 3)

        return {"kind": kind, "tick": self.tick_count, "price_before": self.price_history[-1]}
