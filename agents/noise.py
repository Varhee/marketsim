import random
from typing import List
from engine.order_book import Order, OrderBook, Side, OrderType
from .base import Agent


class NoiseTrader(Agent):
    """
    Trades for no particular reason, near whatever the current mid is.
    Every real market has a background hum of these - retail flow,
    rebalancing, people who just want to trade - and they're what
    keeps the book from going stale between the "smarter" agents.
    """

    def __init__(self, agent_id: str, activity: float = 0.35, tick_size: float = 0.05):
        super().__init__(agent_id)
        self.activity = activity
        self.tick_size = tick_size

    def act(self, book: OrderBook, price_history: List[float]) -> List[Order]:
        if random.random() > self.activity:
            return []

        mid = book.mid_price() or (price_history[-1] if price_history else 100.0)
        side = random.choice([Side.BUY, Side.SELL])
        qty = random.choice([10, 20, 30, 50, 100])

        # mostly limit orders scattered a few ticks off mid, occasional market order
        if random.random() < 0.15:
            return [Order(side=side, order_type=OrderType.MARKET, quantity=qty, agent_id=self.agent_id)]

        offset = random.randint(-4, 4) * self.tick_size
        price = max(0.01, round(mid + offset, 2))
        return [Order(side=side, order_type=OrderType.LIMIT, quantity=qty, price=price, agent_id=self.agent_id)]
