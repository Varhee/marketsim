import statistics
from typing import List
from engine.order_book import Order, OrderBook, Side, OrderType
from .base import Agent


class MeanReversionTrader(Agent):
    """
    Watches a rolling window, works out how many standard deviations
    the current price sits from the window's mean, and fades the move
    once it crosses a z-score threshold. Direct opposite instinct to
    the momentum agent, which is the point - the two of them pulling
    against each other is most of what gives the sim its texture.
    """

    def __init__(self, agent_id: str, window: int = 30, z_threshold: float = 1.5, size: int = 30):
        super().__init__(agent_id)
        self.window = window
        self.z_threshold = z_threshold
        self.size = size

    def act(self, book: OrderBook, price_history: List[float]) -> List[Order]:
        if len(price_history) < self.window:
            return []

        recent = price_history[-self.window:]
        mean = statistics.mean(recent)
        stdev = statistics.pstdev(recent) or 0.0001
        current = price_history[-1]
        z = (current - mean) / stdev

        if z > self.z_threshold:
            # too far above the mean - bet on a pullback
            return [Order(side=Side.SELL, order_type=OrderType.MARKET, quantity=self.size, agent_id=self.agent_id)]
        if z < -self.z_threshold:
            return [Order(side=Side.BUY, order_type=OrderType.MARKET, quantity=self.size, agent_id=self.agent_id)]
        return []
