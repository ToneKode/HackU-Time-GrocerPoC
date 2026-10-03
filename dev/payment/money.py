"""HKD helpers. Person 1 rounds money to 2 decimal places, half up."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENTS, rounding=ROUND_HALF_UP)


def as_float(value: Decimal) -> float:
    return float(value)
