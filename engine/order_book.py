"""
The limit order book.

This is the actual data structure the matching engine reads and writes.
Bids are kept highest-price-first, asks lowest-price-first, and within a
price level orders queue up in the order they arrived (price-time priority).
Nothing fancy - a couple of sorted dicts of deques would work fine at this
scale, so that's what it is.
"""

from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from itertools import count
from typing import Deque, Dict, List, Optional
import time

_order_ids = count(1)


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass
class Order:
    side: Side
    order_type: OrderType
    quantity: int
    price: Optional[float] = None  # None for market orders
    agent_id: str = "anon"
    order_id: int = field(default_factory=lambda: next(_order_ids))
    timestamp: float = field(default_factory=time.time)
    filled: int = 0

    @property
    def remaining(self) -> int:
        return self.quantity - self.filled

    def __repr__(self):
        p = f"{self.price:.2f}" if self.price is not None else "MKT"
        return f"<Order#{self.order_id} {self.side.value} {self.remaining}/{self.quantity} @ {p} [{self.agent_id}]>"


@dataclass
class Trade:
    buy_order_id: int
    sell_order_id: int
    price: float
    quantity: int
    buyer_id: str
    seller_id: str
    timestamp: float = field(default_factory=time.time)
    aggressor: Side = Side.BUY  # which side crossed the spread


class OrderBook:
    """
    Two price ladders. bids[price] and asks[price] are each a deque of
    Order objects sitting at that price, oldest first - that queue order
    is what gives time priority once price priority is settled.
    """

    def __init__(self, symbol: str = "SIM"):
        self.symbol = symbol
        self.bids: Dict[float, Deque[Order]] = {}
        self.asks: Dict[float, Deque[Order]] = {}
        self.orders_by_id: Dict[int, Order] = {}
        self.last_trade_price: Optional[float] = None
        self.trade_history: List[Trade] = []

    # -- helpers -----------------------------------------------------

    def best_bid(self) -> Optional[float]:
        return max(self.bids.keys()) if self.bids else None

    def best_ask(self) -> Optional[float]:
        return min(self.asks.keys()) if self.asks else None

    def spread(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return None
        return round(ba - bb, 4)

    def mid_price(self) -> Optional[float]:
        bb, ba = self.best_bid(), self.best_ask()
        if bb is None or ba is None:
            return self.last_trade_price
        return round((bb + ba) / 2, 4)

    def depth(self, levels: int = 5) -> dict:
        """Top N price levels each side, aggregated by price."""
        bid_prices = sorted(self.bids.keys(), reverse=True)[:levels]
        ask_prices = sorted(self.asks.keys())[:levels]
        return {
            "bids": [
                {"price": p, "quantity": sum(o.remaining for o in self.bids[p])}
                for p in bid_prices
            ],
            "asks": [
                {"price": p, "quantity": sum(o.remaining for o in self.asks[p])}
                for p in ask_prices
            ],
        }

    def total_bid_volume(self) -> int:
        return sum(o.remaining for q in self.bids.values() for o in q)

    def total_ask_volume(self) -> int:
        return sum(o.remaining for q in self.asks.values() for o in q)

    # -- book maintenance ---------------------------------------------

    def _book_for(self, side: Side) -> Dict[float, Deque[Order]]:
        return self.bids if side == Side.BUY else self.asks

    def _rest(self, order: Order):
        """Put a (partially) unfilled limit order onto the book."""
        if order.remaining <= 0:
            return
        book = self._book_for(order.side)
        book.setdefault(order.price, deque()).append(order)
        self.orders_by_id[order.order_id] = order

    def cancel(self, order_id: int) -> bool:
        order = self.orders_by_id.get(order_id)
        if order is None:
            return False
        book = self._book_for(order.side)
        level = book.get(order.price)
        if not level:
            return False
        try:
            level.remove(order)
        except ValueError:
            return False
        if not level:
            del book[order.price]
        del self.orders_by_id[order_id]
        return True

    def _prune_level(self, book: Dict[float, Deque[Order]], price: float):
        level = book.get(price)
        if level is not None and not level:
            del book[price]
