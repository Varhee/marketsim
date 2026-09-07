"""
The matching engine.

Takes an incoming order, walks the opposite side of the book from best
price outward, fills what it can at the resting order's price (not the
incoming order's price - that's what "price improvement" for the
aggressor means), and rests whatever's left if it's a limit order.
Market orders never rest; if there's nothing left to trade against,
the remainder is just cancelled.
"""

from __future__ import annotations
from typing import List
from .order_book import OrderBook, Order, Trade, Side, OrderType


class MatchingEngine:
    def __init__(self, book: OrderBook):
        self.book = book

    def submit(self, order: Order) -> List[Trade]:
        if order.order_type == OrderType.MARKET:
            return self._match_market(order)
        return self._match_limit(order)

    def cancel(self, order_id: int) -> bool:
        return self.book.cancel(order_id)

    # -- internals ------------------------------------------------------

    def _opposite_book(self, side: Side):
        return self.book.asks if side == Side.BUY else self.book.bids

    def _crosses(self, order: Order, resting_price: float) -> bool:
        if order.order_type == OrderType.MARKET:
            return True
        if order.side == Side.BUY:
            return order.price >= resting_price
        return order.price <= resting_price

    def _match_limit(self, order: Order) -> List[Trade]:
        trades = self._walk_book(order)
        if order.remaining > 0:
            self.book._rest(order)
        return trades

    def _match_market(self, order: Order) -> List[Trade]:
        # market orders take whatever price is on offer; no resting.
        return self._walk_book(order)

    def _walk_book(self, order: Order) -> List[Trade]:
        trades: List[Trade] = []
        opposite = self._opposite_book(order.side)
        price_order = sorted(opposite.keys()) if order.side == Side.BUY else sorted(
            opposite.keys(), reverse=True
        )

        for price in price_order:
            if order.remaining <= 0:
                break
            if not self._crosses(order, price):
                break

            level = opposite[price]
            skip_count = 0  # how many same-agent orders we've stepped over at this level
            while level and order.remaining > 0 and skip_count < len(level):
                resting = level[0]

                # self-trade prevention: an agent shouldn't be able to trade
                # against its own resting order (a market maker crossing its
                # own quote after a skew update is the case that surfaces this).
                # Skip it in FIFO order rather than letting it fill.
                if resting.agent_id == order.agent_id:
                    level.rotate(-1)
                    skip_count += 1
                    continue

                fill_qty = min(order.remaining, resting.remaining)

                resting.filled += fill_qty
                order.filled += fill_qty

                if order.side == Side.BUY:
                    buy_id, sell_id = order.order_id, resting.order_id
                    buyer, seller = order.agent_id, resting.agent_id
                else:
                    buy_id, sell_id = resting.order_id, order.order_id
                    buyer, seller = resting.agent_id, order.agent_id

                trade = Trade(
                    buy_order_id=buy_id,
                    sell_order_id=sell_id,
                    price=price,
                    quantity=fill_qty,
                    buyer_id=buyer,
                    seller_id=seller,
                    aggressor=order.side,
                )
                trades.append(trade)
                self.book.last_trade_price = price
                self.book.trade_history.append(trade)

                if resting.remaining == 0:
                    level.popleft()
                    self.book.orders_by_id.pop(resting.order_id, None)

            self.book._prune_level(opposite, price)

        return trades
