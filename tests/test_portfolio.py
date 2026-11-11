from decimal import Decimal

from app.services.portfolio import calculate_buyout_price, calculate_payoff, calculate_period_interest


def test_fortnight_interest_and_expected_return_use_original_principal() -> None:
    principal = Decimal("3000.00")
    rate = Decimal("20.0000")

    interest = calculate_period_interest(principal, rate)

    assert interest == Decimal("600.00")
    assert calculate_payoff(principal, interest) == Decimal("3600.00")
    assert calculate_payoff(principal, interest * 2) == Decimal("4200.00")


def test_payoff_subtracts_confirmed_savings_and_coupon_without_negative_balance() -> None:
    due = calculate_payoff(
        Decimal("3000.00"),
        Decimal("600.00"),
        savings_applied=Decimal("1000.00"),
        coupon_discount=Decimal("100.00"),
    )

    assert due == Decimal("2500.00")
    assert calculate_payoff(
        Decimal("3000.00"),
        Decimal("600.00"),
        savings_applied=Decimal("4000.00"),
    ) == Decimal("0.00")


def test_buyout_is_half_the_assessed_sale_price() -> None:
    assert calculate_buyout_price(Decimal("9000.00")) == Decimal("4500.00")


def test_interest_rounds_to_nearest_cent() -> None:
    assert calculate_period_interest(
        Decimal("1000.00"),
        Decimal("12.3456"),
    ) == Decimal("123.46")
