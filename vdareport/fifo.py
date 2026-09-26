# vdareport/fifo.py
#
# Lot matching. Which parcel did the tokens you sold come out of?
#
# This is inventory costing. It is the same problem as costing a sale of
# goods out of stock bought at different prices on different days, and it
# has the same answer: keep the purchases as separate lots, consume the
# oldest first, and report one row per matched parcel.
#
# Schedule VDA wants exactly that — a row per acquisition-and-disposal
# pair, each with its own acquisition date and its own cost — not a
# yearly total. So selling 2.5 ETH out of a 2.0 lot and a 1.0 lot is two
# rows, not one, with two different acquisition dates.
#
# Two things here are unusual and deliberate:
#
#   A Lot is MUTABLE, unlike everything else in this codebase. That is
#   correct: a Transfer is history and must never change, but a lot's
#   remaining balance is a running figure that is supposed to be
#   consumed. The mutation is the point.
#
#   An acquisition that could not be priced still creates a lot. The
#   QUANTITY is known even when the cost is not, and dropping it would
#   corrupt the running balance and shift every later match onto the
#   wrong parcel. It is carried with cost_inr = None, and any disposal
#   that reaches it is reported as a gap instead of a number.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from .classify import Classified
from .models import Kind
from .prices import PricedValue, Pricer, round_paise


@dataclass
class Lot:
    """One parcel acquired on one day at one cost."""

    asset: str
    acquired_at: datetime
    quantity: Decimal
    remaining: Decimal
    cost_inr: Decimal | None  # None when the acquisition could not be priced
    tx_hash: str

    def unit_cost(self) -> Decimal | None:
        if self.cost_inr is None:
            return None
        return self.cost_inr / self.quantity


@dataclass(frozen=True)
class Match:
    """One Schedule VDA row: this parcel, sold on that day."""

    asset: str
    quantity: Decimal
    acquired_at: datetime
    disposed_at: datetime
    cost_inr: Decimal
    consideration_inr: Decimal
    acquisition_tx: str
    disposal_tx: str

    @property
    def gain_inr(self) -> Decimal:
        return self.consideration_inr - self.cost_inr


@dataclass(frozen=True)
class Gap:
    """Something the engine could not turn into a figure, and why.

    A gap is a result, not a failure. It goes on the report where a
    human can see it and close it.
    """

    asset: str
    on: date
    why: str
    tx_hash: str


@dataclass
class Ledger:
    matches: list[Match] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    lots: dict[str, list[Lot]] = field(default_factory=dict)

    def quantity_held(self, asset: str) -> Decimal:
        return sum(
            (lot.remaining for lot in self.lots.get(asset.upper(), [])),
            Decimal("0"),
        )


def _apportion(total: Decimal, part: Decimal, whole: Decimal) -> Decimal:
    """The share of `total` that `part` out of `whole` represents."""
    return round_paise(total * part / whole)


def run(events: list[Classified], pricer: Pricer) -> Ledger:
    """Walk the history in order and match disposals against lots.

    Self-transfers are skipped outright. Not filtered out as a special
    case — there is simply nothing for them to do, because the pool they
    would move between is the same pool.
    """
    ledger = Ledger()

    for event in events:
        transfer = event.transfer
        asset = transfer.asset.upper()
        lots = ledger.lots.setdefault(asset, [])

        # ---- nothing happened -------------------------------------
        if event.kind is Kind.SELF_TRANSFER:
            continue

        # ---- a new parcel -----------------------------------------
        if event.kind is Kind.ACQUISITION:
            priced = pricer.value_inr(asset, transfer.amount, transfer.timestamp)
            cost = priced.inr if isinstance(priced, PricedValue) else None
            if cost is None:
                ledger.gaps.append(
                    Gap(
                        asset=asset,
                        on=transfer.timestamp.date(),
                        why=(
                            f"acquisition of {transfer.amount} {asset} could not "
                            f"be valued — {priced.why}"
                        ),
                        tx_hash=transfer.tx_hash,
                    )
                )
            lots.append(
                Lot(
                    asset=asset,
                    acquired_at=transfer.timestamp,
                    quantity=transfer.amount,
                    remaining=transfer.amount,
                    cost_inr=cost,
                    tx_hash=transfer.tx_hash,
                )
            )
            continue

        # ---- a disposal -------------------------------------------
        proceeds = pricer.value_inr(asset, transfer.amount, transfer.timestamp)
        if not isinstance(proceeds, PricedValue):
            ledger.gaps.append(
                Gap(
                    asset=asset,
                    on=transfer.timestamp.date(),
                    why=(
                        f"disposal of {transfer.amount} {asset} could not be "
                        f"valued — {proceeds.why}"
                    ),
                    tx_hash=transfer.tx_hash,
                )
            )
            continue

        outstanding = transfer.amount
        consideration_allocated = Decimal("0")

        while outstanding > 0 and lots and lots[0].remaining <= 0:
            lots.pop(0)

        while outstanding > 0:
            if not lots:
                # Sold more than the history we read accounts for.
                # Assuming a zero cost taxes the whole proceeds;
                # ignoring it taxes none. Both are wrong.
                ledger.gaps.append(
                    Gap(
                        asset=asset,
                        on=transfer.timestamp.date(),
                        why=(
                            f"{outstanding} {asset} disposed of with no "
                            "acquisition on record — the opening balance "
                            "predates the history that was read"
                        ),
                        tx_hash=transfer.tx_hash,
                    )
                )
                break

            lot = lots[0]
            take = min(outstanding, lot.remaining)

            share = _apportion(proceeds.inr, take, transfer.amount)
            outstanding -= take
            lot.remaining -= take

            # The last slice absorbs any rounding drift, so the rows
            # always add back to the consideration actually received.
            if outstanding == 0:
                share = proceeds.inr - consideration_allocated
            consideration_allocated += share

            if lot.cost_inr is None:
                ledger.gaps.append(
                    Gap(
                        asset=asset,
                        on=transfer.timestamp.date(),
                        why=(
                            f"{take} {asset} came out of a parcel acquired "
                            f"{lot.acquired_at.date().isoformat()} whose cost "
                            "is unknown, so no gain can be computed"
                        ),
                        tx_hash=transfer.tx_hash,
                    )
                )
            else:
                ledger.matches.append(
                    Match(
                        asset=asset,
                        quantity=take,
                        acquired_at=lot.acquired_at,
                        disposed_at=transfer.timestamp,
                        cost_inr=_apportion(lot.cost_inr, take, lot.quantity),
                        consideration_inr=share,
                        acquisition_tx=lot.tx_hash,
                        disposal_tx=transfer.tx_hash,
                    )
                )

            if lot.remaining <= 0:
                lots.pop(0)

    return ledger
