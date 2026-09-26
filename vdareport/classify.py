# vdareport/classify.py
#
# What kind of event was that?
#
# This is the file the whole project turns on, and it is short, because
# the work was done in the modelling rather than here.
#
# The unit of assessment is the TAXPAYER, not the address. Every wallet a
# person holds is pooled into one ledger. Once that is true, moving tokens
# between your own wallets has nowhere to go: nothing entered the pool and
# nothing left it, so nothing was realised. It is not detected as a
# self-transfer by a heuristic; it simply cannot be counted as a sale.
#
# Tools that assess per-address have to guess instead. They look at
# timing, at round amounts, at address clustering — and they are wrong
# often enough that "it invented a sale I never made" is one of the most
# common complaints about the whole category.

from __future__ import annotations

from dataclasses import dataclass

from .models import Direction, Kind, Transfer


@dataclass(frozen=True)
class Classified:
    """A transfer, and what it turned out to be — carrying its reason.

    The reason travels with the classification on purpose. Eight months
    from now, when someone asks why a movement was not taxed, the answer
    has to be in the record rather than in somebody's memory.
    """

    transfer: Transfer
    kind: Kind
    reason: str


def classify(transfer: Transfer, owned: set[str]) -> Classified:
    """Decide what one movement was, given every wallet the taxpayer holds.

    `owned` is the whole point. Pass this one address and it cannot tell
    an internal move from a sale — not because the code is weak, but
    because the information genuinely is not there.
    """
    counterparty = transfer.counterparty.lower()

    # The three lines that matter.
    if counterparty in owned:
        return Classified(
            transfer=transfer,
            kind=Kind.SELF_TRANSFER,
            reason=(
                f"counterparty {counterparty[:10]}... is another wallet of "
                "the same taxpayer, so nothing left the pool and nothing "
                "was realised"
            ),
        )

    if transfer.direction is Direction.IN:
        return Classified(
            transfer=transfer,
            kind=Kind.ACQUISITION,
            reason=(
                f"received from {counterparty[:10]}..., which the taxpayer "
                "does not hold"
            ),
        )

    return Classified(
        transfer=transfer,
        kind=Kind.DISPOSAL,
        reason=(
            f"sent to {counterparty[:10]}..., which the taxpayer does not hold"
        ),
    )


def classify_all(transfers: list[Transfer], owned: set[str]) -> list[Classified]:
    """Classify a whole history, oldest first.

    Sorted by timestamp because everything downstream — FIFO above all —
    depends on the order being the order things actually happened in,
    and not the order the API happened to hand them back in.
    """
    normalised = {w.lower() for w in owned}
    ordered = sorted(transfers, key=lambda t: (t.timestamp, t.tx_hash))
    return [classify(t, normalised) for t in ordered]


def summarise(events: list[Classified]) -> dict[str, int]:
    """How many of each kind. Useful long before any price data exists."""
    counts: dict[str, int] = {}
    for event in events:
        counts[event.kind.value] = counts.get(event.kind.value, 0) + 1
    return counts
