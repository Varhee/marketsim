"""
Every agent gets the same view of the world each tick (current book,
recent trade prices) and hands back a list of Order objects it wants
submitted. The agent doesn't touch the book directly - keeps the
simulation loop in full control of ordering and makes agents trivially
testable in isolation.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import List
from engine.order_book import Order, OrderBook


class Agent(ABC):
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.starting_cash: float = 1_000_000.0
        self.cash: float = self.starting_cash
        self.position: int = 0

    @abstractmethod
    def act(self, book: OrderBook, price_history: List[float]) -> List[Order]:
        """Look at the market, return zero or more new orders."""
        raise NotImplementedError

    def on_fill(self, side, price: float, quantity: int):
        """Simulation loop calls this after a trade involving this agent."""
        signed = quantity if side.value == "BUY" else -quantity
        self.position += signed
        self.cash -= signed * price

    def mark_to_market_pnl(self, current_price: float) -> float:
        """Cash on hand plus what the current position is worth, minus what we started with."""
        return round(self.cash + self.position * current_price - self.starting_cash, 2)
