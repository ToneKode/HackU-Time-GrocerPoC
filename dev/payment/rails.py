"""Payment rails and the cash-then-reward chooser.

Published rates used here (demo pins, not live offers):

- yuu: earn 1 point per HK$1 spent. Redeem at 200 points = HK$1
  (yuu base earn; Hang Seng enJoy basic redemption).
- HASE/HSBC: 5% cashback on the merchant item total. The card is charged
  the full total; the 5% is reward value, matching the "5% cashback"
  comparison. Hang Seng enJoy advertises a 5% tier and higher discounts
  at some grocers; this demo keeps a flat 5%.
- AlipayHK A.Point (Ant points): earn 1 point per HK$1. At participating
  merchants, 1,000 points offset HK$1, so each point is worth HK$0.001.
- PayMe: HK$30 off a merchant basket of HK$300 or more. That discount
  reduces cash paid. Under HK$300 the offer does not apply.

Selection, per merchant:
1. Minimize cash paid.
2. If cash paid ties, maximize the HKD value of the reward.
   A HK$5 yuu equivalent beats HK$2 of 5% cashback.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from dev.payment.money import as_float, money

YUU_POINTS_PER_HKD = 1
YUU_POINTS_PER_HKD_VALUE = 200
HASE_CASHBACK_RATE = Decimal("0.05")
ALIPAY_POINTS_PER_HKD = 1
ALIPAY_POINTS_PER_HKD_VALUE = 1000
PAYME_MIN_SPEND = Decimal("300")
PAYME_OFF = Decimal("30")

# Stable tie-break after cash and reward value are equal.
PREFERENCE = ("payme", "hase_hsbc", "yuu", "alipay_ant")

LABELS = {
    "yuu": "yuu points",
    "hase_hsbc": "HASE/HSBC cashback",
    "alipay_ant": "Alipay A.Point",
    "payme": "PayMe",
}


@dataclass(frozen=True)
class RailQuote:
    method: str
    eligible: bool
    cash_paid: Decimal
    reward_hkd: Decimal
    detail: str

    def as_dict(self) -> dict:
        return {
            "method": self.method,
            "label": LABELS[self.method],
            "eligible": self.eligible,
            "cash_paid": as_float(self.cash_paid),
            "reward_hkd": as_float(self.reward_hkd),
            "detail": self.detail,
        }


def _points(subtotal: Decimal) -> int:
    """Whole Hong Kong dollars earn points. Cents do not."""
    return int(subtotal)


def quote_rails(subtotal: Decimal) -> list[RailQuote]:
    basket = money(subtotal)
    yuu_points = _points(basket) * YUU_POINTS_PER_HKD
    yuu_value = money(Decimal(yuu_points) / Decimal(YUU_POINTS_PER_HKD_VALUE))
    alipay_points = _points(basket) * ALIPAY_POINTS_PER_HKD
    alipay_value = money(Decimal(alipay_points) / Decimal(ALIPAY_POINTS_PER_HKD_VALUE))
    cashback = money(basket * HASE_CASHBACK_RATE)
    payme_ok = basket >= PAYME_MIN_SPEND
    payme_cash = money(basket - PAYME_OFF) if payme_ok else basket

    return [
        RailQuote(
            method="yuu",
            eligible=True,
            cash_paid=basket,
            reward_hkd=yuu_value,
            detail=(
                f"Earn {yuu_points} yuu points "
                f"({YUU_POINTS_PER_HKD_VALUE} points = HK$1), worth HK${yuu_value}."
            ),
        ),
        RailQuote(
            method="hase_hsbc",
            eligible=True,
            cash_paid=basket,
            reward_hkd=cashback,
            detail=(
                f"5% HASE/HSBC cashback is worth HK${cashback}. "
                "The card is still charged the full item total."
            ),
        ),
        RailQuote(
            method="alipay_ant",
            eligible=True,
            cash_paid=basket,
            reward_hkd=alipay_value,
            detail=(
                f"Earn {alipay_points} A.Point "
                f"({ALIPAY_POINTS_PER_HKD_VALUE} points = HK$1), worth HK${alipay_value}."
            ),
        ),
        RailQuote(
            method="payme",
            eligible=payme_ok,
            cash_paid=payme_cash,
            reward_hkd=money(0),
            detail=(
                f"HK${PAYME_OFF} off, cash paid HK${payme_cash}."
                if payme_ok
                else f"Merchant items total HK${basket}, under HK${PAYME_MIN_SPEND}, so PayMe HK$30 off does not apply."
            ),
        ),
    ]


def choose_rail(subtotal: Decimal) -> tuple[RailQuote, list[RailQuote]]:
    quotes = quote_rails(subtotal)
    eligible = [quote for quote in quotes if quote.eligible]
    if not eligible:
        raise ValueError("no eligible payment rail")

    def sort_key(quote: RailQuote) -> tuple[Decimal, Decimal, int]:
        return (quote.cash_paid, -quote.reward_hkd, PREFERENCE.index(quote.method))

    best = min(eligible, key=sort_key)
    return best, quotes


def explain(best: RailQuote, quotes: list[RailQuote]) -> str:
    others = [quote for quote in quotes if quote.eligible and quote.method != best.method]
    label = LABELS[best.method]
    if not others:
        return f"{label} is the only eligible rail. Cash paid HK${best.cash_paid}."

    if all(quote.cash_paid > best.cash_paid for quote in others):
        compared = ", ".join(
            f"{LABELS[quote.method]} HK${quote.cash_paid}" for quote in others
        )
        return (
            f"{label} charges HK${best.cash_paid}, less cash than {compared}."
        )

    same_cash = [quote for quote in others if quote.cash_paid == best.cash_paid]
    if same_cash:
        compared = ", ".join(
            f"{LABELS[quote.method]} HK${quote.reward_hkd}" for quote in same_cash
        )
        return (
            f"Cash paid is HK${best.cash_paid} on the remaining rails. "
            f"{label} is worth HK${best.reward_hkd}, ahead of {compared}."
        )

    return (
        f"{label} minimizes cash paid (HK${best.cash_paid}) "
        f"and then reward value (HK${best.reward_hkd})."
    )
