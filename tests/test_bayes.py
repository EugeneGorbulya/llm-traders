import pytest

from llmtraders.bayes import posterior_high, rational_price, value_from_p

TABLE_V2 = [
    ((), 0.500, 100.0),
    (("good",), 0.700, 112.0),
    (("bad",), 0.300, 88.0),
    (("good", "good"), 0.845, 120.7),
    (("good", "bad"), 0.500, 100.0),
    (("bad", "bad"), 0.155, 79.3),
]


@pytest.mark.parametrize("signals,p,price", TABLE_V2)
def test_table_v2(signals, p, price):
    assert posterior_high(signals) == pytest.approx(p, abs=0.0005)
    assert rational_price(signals) == pytest.approx(price, abs=0.1)


def test_order_does_not_matter():
    assert posterior_high(["good", "bad"]) == pytest.approx(
        posterior_high(["bad", "good"])
    )


def test_case_insensitive_and_unknown_signal():
    assert posterior_high(["GOOD"]) == pytest.approx(0.7)
    with pytest.raises(ValueError):
        posterior_high(["maybe"])


def test_value_from_p():
    assert value_from_p(0.0) == 70.0
    assert value_from_p(1.0) == 130.0
    assert value_from_p(0.7) == pytest.approx(112.0)
