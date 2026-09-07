from typing import List
from engine.order_book import Order, OrderBook, Side, OrderType
from .base import Agent


class InstitutionalTrader(Agent):
    """
    Doesn't trade often, but when it does it's big enough to move the
    book. Rather than dumping the whole order in one tick (which would
    be unrealistic - and honestly a bit boring to watch) it slices a
    scheduled order into chunks over a few ticks, which is closer to
    how a real execution desk would work an order to limit impact.
    """

    def __init__(self, agent_id: str):
        super().__init__(agent_id)
        self.pending_side: Side | None = None
        self.pending_qty: int = 0
        self.chunk: int = 0

    def schedule(self, side: Side, total_quantity: int, chunks: int = 5):
        self.pending_side = side
        self.pending_qty = total_quantity
        self.chunk = max(1, total_quantity // chunks)

    def act(self, book: OrderBook, price_history: List[float]) -> List[Order]:
        if not self.pending_side or self.pending_qty <= 0:
            return []

        qty = min(self.chunk, self.pending_qty)
        self.pending_qty -= qty
        order = Order(side=self.pending_side, order_type=OrderType.MARKET, quantity=qty, agent_id=self.agent_id)

        if self.pending_qty <= 0:
            self.pending_side = None

        return [order]
