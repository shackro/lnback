from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def as_money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_period_interest(principal: Decimal, rate_percent: Decimal) -> Decimal:
    return as_money(principal * rate_percent / Decimal("100"))


def calculate_payoff(
    outstanding_principal: Decimal,
    period_interest: Decimal,
    savings_applied: Decimal = Decimal("0.00"),
    coupon_discount: Decimal = Decimal("0.00"),
) -> Decimal:
    total_due = outstanding_principal + period_interest - savings_applied - coupon_discount
    return max(Decimal("0.00"), as_money(total_due))


def calculate_buyout_price(assessed_sale_price: Decimal) -> Decimal:
    return as_money(assessed_sale_price * Decimal("0.50"))
