# vdareport/models.py
#
# The vocabulary.
#
# Etherscan hands back JSON with twenty fields of noise in it. Nothing
# downstream of this file is allowed to see that shape. Everything speaks
# in the types below instead, so the day we swap Etherscan for something
# else, only the reading module changes.

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """A timestamp that knows it is UTC.

    Never build a naive datetime in this project.
    """
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class Direction(Enum):
    """Which way the tokens moved, seen from a wallet the taxpayer owns."""

    IN = "in"
    OUT = "out"


class Kind(Enum):
    """What a movement turns out to BE, once you know who owns what.

    The chain cannot tell you this. Working it out is step 3.
    """

    ACQUISITION = "acquisition"
    DISPOSAL = "disposal"
    SELF_TRANSFER = "self_transfer"


@dataclass(frozen=True)
class Transfer:
    """One movement of one asset, as read off the chain.

    Frozen, because it already happened. Nothing downstream gets to edit
    history — if a figure is wrong, the fix belongs in the code that
    reads or interprets, never in the record itself.
    """

    tx_hash: str
    timestamp: datetime
    asset: str
    amount: Decimal
    direction: Direction

    # The other side of the movement.
    counterparty: str

    # Which of the taxpayer's own wallets saw it.
    #
    # Both of these are needed together, and that pair is the whole
    # reason step 3 is possible: if the counterparty is also a wallet
    # in the taxpayer's own set, nothing was sold.
    wallet: str
