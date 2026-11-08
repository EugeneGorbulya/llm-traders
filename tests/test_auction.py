import pytest

from llmtraders.auction import Order, clear


def test_simple_cross_tie_goes_to_price_nearest_reference():
    orders = [Order("A", "buy", 105, 3), Order("B", "sell", 95, 3)]
    hi = clear(orders, ref_price=104)
    assert (hi.price, hi.volume, hi.fills) == (105, 3, {"A": 3, "B": -3})
    lo = clear(orders, ref_price=96)
    assert lo.price == 95
    assert clear(orders, ref_price=100).price == 95


def test_no_cross_no_trade():
    res = clear([Order("A", "buy", 90, 5), Order("B", "sell", 110, 5)], ref_price=100)
    assert res.price is None and res.volume == 0 and not res.traded


def test_one_sided_book_no_trade():
    assert not clear([Order("A", "buy", 120, 5), Order("B", "buy", 110, 1)]).traded
    assert not clear([Order("A", "sell", 80, 5)]).traded
    assert not clear([]).traded


def test_zero_qty_orders_ignored():
    res = clear([Order("A", "buy", 120, 0), Order("B", "sell", 80, 4)])
    assert not res.traded


def test_max_volume_then_min_imbalance():
    orders = [
        Order("A", "buy", 110, 4),
        Order("B", "buy", 105, 4),
        Order("C", "sell", 100, 5),
    ]
    res = clear(orders)
    assert res.volume == 5
    assert res.price in (100, 105)


def test_rationing_price_priority():
    orders = [
        Order("A", "buy", 110, 4),
        Order("B", "buy", 105, 4),
        Order("C", "sell", 100, 5),
    ]
    res = clear(orders)
    assert res.fills == {"A": 4, "B": 1, "C": -5}


def test_pro_rata_largest_remainder_tie_by_agent_id():
    orders = [
        Order("B", "buy", 105, 3),
        Order("A", "buy", 105, 3),
        Order("C", "sell", 100, 3),
    ]
    res = clear(orders)
    assert res.volume == 3
    assert res.fills == {"A": 2, "B": 1, "C": -3}
    even = clear(
        [
            Order("A", "buy", 105, 3),
            Order("B", "buy", 105, 3),
            Order("C", "sell", 100, 4),
        ]
    )
    assert even.fills == {"A": 2, "B": 2, "C": -4}


def test_fills_balance_and_respect_limits():
    orders = [
        Order("A", "buy", 112, 5),
        Order("B", "buy", 101, 2),
        Order("C", "sell", 99, 3),
        Order("D", "sell", 108, 4),
        Order("E", "sell", 120, 1),
    ]
    res = clear(orders, ref_price=100)
    assert sum(res.fills.values()) == 0
    for o in orders:
        q = res.fills.get(o.agent_id, 0)
        if q > 0:
            assert o.side == "buy" and o.limit >= res.price and q <= o.qty
        if q < 0:
            assert o.side == "sell" and o.limit <= res.price and -q <= o.qty


@pytest.mark.parametrize(
    "kw",
    [
        {"side": "hold", "limit": 100, "qty": 1},
        {"side": "buy", "limit": 0, "qty": 1},
        {"side": "buy", "limit": 100, "qty": -1},
        {"side": "buy", "limit": float("inf"), "qty": 1},
    ],
)
def test_invalid_orders_rejected(kw):
    with pytest.raises(ValueError):
        Order("A", **kw)
