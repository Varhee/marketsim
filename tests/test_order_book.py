"""
Not exhaustive, but covers the stuff that would actually be embarrassing
to get wrong: price-time priority, partial fills, and market orders
eating through multiple price levels.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.order_book import OrderBook, Order, Side, OrderType
from engine.matching_engine import MatchingEngine


def fresh():
    book = OrderBook()
    engine = MatchingEngine(book)
    return book, engine


def test_resting_limit_order_sits_on_book():
    book, engine = fresh()
    o = Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=100, price=99.5, agent_id="a")
    trades = engine.submit(o)
    assert trades == []
    assert book.best_bid() == 99.5
    assert book.total_bid_volume() == 100


def test_crossing_limit_order_fills_immediately():
    book, engine = fresh()
    engine.submit(Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=50, price=100.0, agent_id="seller"))
    trades = engine.submit(Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=50, price=100.0, agent_id="buyer"))
    assert len(trades) == 1
    assert trades[0].price == 100.0
    assert trades[0].quantity == 50
    assert book.best_ask() is None


def test_price_time_priority():
    book, engine = fresh()
    # two sell orders at the same price - first one in should fill first
    first = Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=30, price=100.0, agent_id="s1")
    second = Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=30, price=100.0, agent_id="s2")
    engine.submit(first)
    engine.submit(second)

    trades = engine.submit(Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=30, price=100.0, agent_id="buyer"))
    assert len(trades) == 1
    assert trades[0].seller_id == "s1"


def test_partial_fill_across_levels():
    book, engine = fresh()
    engine.submit(Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=40, price=49.0, agent_id="s1"))
    engine.submit(Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=60, price=50.0, agent_id="s2"))

    # matches the worked example from the brief: BUY 100 @ 50 against SELL 40@49 + SELL 60@50
    trades = engine.submit(Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=100, price=50.0, agent_id="buyer"))
    assert len(trades) == 2
    assert trades[0].price == 49.0 and trades[0].quantity == 40
    assert trades[1].price == 50.0 and trades[1].quantity == 60


def test_market_order_never_rests():
    book, engine = fresh()
    trades = engine.submit(Order(side=Side.BUY, order_type=OrderType.MARKET, quantity=100, agent_id="buyer"))
    assert trades == []
    assert book.best_bid() is None  # nothing to buy, and it shouldn't rest


def test_self_trade_prevention():
    book, engine = fresh()
    # same agent resting on both sides at overlapping prices shouldn't self-fill
    engine.submit(Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=50, price=99.0, agent_id="mm"))
    other_seller = Order(side=Side.SELL, order_type=OrderType.LIMIT, quantity=50, price=99.0, agent_id="someone_else")
    engine.submit(other_seller)

    trades = engine.submit(Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=50, price=99.0, agent_id="mm"))
    assert len(trades) == 1
    assert trades[0].seller_id == "someone_else"  # skipped its own resting order, matched the other one


def test_cancel_removes_order_from_book():
    book, engine = fresh()
    o = Order(side=Side.BUY, order_type=OrderType.LIMIT, quantity=10, price=98.0, agent_id="a")
    engine.submit(o)
    assert engine.cancel(o.order_id) is True
    assert book.best_bid() is None


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS  {t.__name__}")
    print(f"\n{len(tests)} passed")
