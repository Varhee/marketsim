from typing import List
from engine.order_book import Order, OrderBook, Side, OrderType
from .base import Agent


class MarketMaker(Agent):
    """
    Quotes both sides of the book every tick and lives off the spread.
    The interesting part isn't the quoting, it's the inventory skew:
    the more this agent accumulates on one side, the more it nudges
    its own quotes to encourage trades that bring it back to flat.
    Push it too far past `max_inventory` and it pulls its quotes
    altogether - which is exactly the behaviour that turns a normal
    market into a liquidity crisis when several of these exist at once.
    """

    def __init__(
        self,
        agent_id: str,
        half_spread: float = 0.10,
        quote_size: int = 100,
        max_inventory: int = 3000,
        skew_sensitivity: float = 0.00003,
    ):
        super().__init__(agent_id)
        self.half_spread = half_spread
        self.quote_size = quote_size
        self.max_inventory = max_inventory
        self.skew_sensitivity = skew_sensitivity
        self.active_order_ids: List[int] = []

    def act(self, book: OrderBook, price_history: List[float]) -> List[Order]:
        mid = book.mid_price() or (price_history[-1] if price_history else 100.0)

        # pulled out of the market - too much risk on the book already
        if abs(self.position) >= self.max_inventory:
            return []

        # skew quotes away from the side we're overloaded on, so we're
        # more eager to trade back towards flat and less eager to add to it
        skew = -self.position * self.skew_sensitivity * mid

        bid_price = max(0.01, round(mid - self.half_spread + skew, 2))
        ask_price = max(bid_price + 0.01, round(mid + self.half_spread + skew, 2))

        size = self.quote_size
        # thin out the size on the side that would deepen our inventory
        if self.position > self.max_inventory * 0.5:
            size_buy = max(10, size // 3)
            size_sell = size
        elif self.position < -self.max_inventory * 0.5:
            size_buy = size
            size_sell = max(10, size // 3)
        else:
            size_buy = size_sell = size

        return [
            Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=size_buy, price=bid_price, agent_id=self.agent_id),
            Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=size_sell, price=ask_price, agent_id=self.agent_id),
        ]
