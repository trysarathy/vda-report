# vdareport/prices.py
#
# Turning a quantity of a token into a number of rupees — or refusing to.
#
# The refusal is the point of this file. Every other module can be judged
# on whether its arithmetic is right; this one is judged on what it does
# when it cannot do arithmetic at all.
#
# A report with a visible hole in it can be finished by hand. A report
# whose holes have been quietly filled with zeros looks finished, gets
# filed, and cannot be defended when somebody asks where a figure came
# from. So: no price on record means no number. Not a zero, not a
# carried-forward price from the day before, not an interpolation.
#
# Why recorded tables rather than a live price API:
#
#   A return you may have to justify eighteen months later has to be
#   reproducible. If prices come from a live feed that revises its own
#   history — and they all do — then running the same report twice gives
#   two different answers and you cannot tell which one you filed. A
#   recorded table is a snapshot you keep. Same history in, same report
#   out, every time.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal


def round_paise(amount: Decimal) -> Decimal:
    """Round to two decimal places, half up.

    Python rounds half to EVEN by default — 1234.565 becomes 1234.56,
    not 1234.57. That is the right convention in some fields and the
    wrong one here; Indian tax practice rounds half away from zero. The
    difference is a paisa at a time, which is exactly the kind of error
    that stays invisible until somebody reconciles your schedule against
    their own and the totals disagree.
    """
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PricedValue:
    """A rupee figure, carrying the two numbers it was built from.

    The inputs travel with the output so that any figure in the final
    report can be taken apart and checked, without rerunning anything.
    """

    inr: Decimal
    usd_unit_price: Decimal
    usd_inr_rate: Decimal
    on: date

    def explain(self) -> str:
        return (
            f"${self.usd_unit_price}/unit x {self.usd_inr_rate} INR/USD "
            f"on {self.on.isoformat()}"
        )


class TablePriceSource:
    """USD prices from a recorded table, keyed (ASSET, YYYY-MM-DD)."""

    def __init__(self, table: dict[tuple[str, str], str]):
        self._table = {(a.upper(), d): Decimal(v) for (a, d), v in table.items()}

    def usd_price(self, asset: str, at: datetime) -> Decimal | None:
        return self._table.get((asset.upper(), at.date().isoformat()))


class TableFxSource:
    """USD/INR from a recorded table, keyed YYYY-MM-DD.

    In production this should be the RBI reference rate for the date, or
    the SBI TT buying rate — whichever the taxpayer's filing position
    uses, consistently, and written down.
    """

    def __init__(self, table: dict[str, str]):
        self._table = {d: Decimal(v) for d, v in table.items()}

    def usd_inr(self, on: date) -> Decimal | None:
        return self._table.get(on.isoformat())


@dataclass(frozen=True)
class Unpriceable:
    """Why a value could not be produced. Carried through to the report."""

    asset: str
    on: date
    why: str


class Pricer:
    """quantity -> rupees, or a refusal with a reason.

    Two independent things can be missing: the token's USD price, and
    the USD/INR rate for that day. They fail differently and the report
    needs to say which, because they are fixed differently — one by
    finding a price source that covers the token, the other by filling a
    gap in the FX table.
    """

    def __init__(self, prices: TablePriceSource, fx: TableFxSource):
        self._prices = prices
        self._fx = fx

    def value_inr(
        self, asset: str, quantity: Decimal, at: datetime
    ) -> PricedValue | Unpriceable:
        on = at.date()

        usd_unit = self._prices.usd_price(asset, at)
        if usd_unit is None:
            return Unpriceable(
                asset=asset,
                on=on,
                why=f"no USD price on record for {asset} on {on.isoformat()}",
            )

        rate = self._fx.usd_inr(on)
        if rate is None:
            return Unpriceable(
                asset=asset,
                on=on,
                why=f"no USD/INR rate on record for {on.isoformat()}",
            )

        return PricedValue(
            inr=round_paise(quantity * usd_unit * rate),
            usd_unit_price=usd_unit,
            usd_inr_rate=rate,
            on=on,
        )
