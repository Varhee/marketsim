from typing import List
from engine.order_book import Order, OrderBook, Side, OrderType
from .base import Agent


class MomentumTrader(Agent):
    """
    Simple "the trend is your friend" logic: compare price now to price
    `lookback` ticks ago, and if the move exceeds a threshold, chase it
    with a market order. These are the agents that turn a small wobble
    into a proper trend - and occasionally into a stampede.
    """

    def __init__(self, agent_id: str, lookback: int = 10, threshold: float = 0.006, size: int = 25):
        super().__init__(agent_id)
        self.lookback = lookback
        self.threshold = threshold
        self.size = size

    def act(self, book: OrderBook, price_history: List[float]) -> List[Order]:
        if len(price_history) <= self.lookback:
            return []

        past = price_history[-self.lookback]
        now = price_history[-1]
        if past == 0:
            return []
        move = (now - past) / past

        if move > self.threshold:
            return [Order(side=Side.BUY, order_type=OrderType.MARKET, quantity=self.size, agent_id=self.agent_id)]
        if move < -self.threshold:
            return [Order(side=Side.SELL, order_type=OrderType.MARKET, quantity=self.size, agent_id=self.agent_id)]
        return []
