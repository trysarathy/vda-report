# vdareport/sources/fixture.py
#
# A recorded history, loaded from disk.
#
# Same shape as the live source, so the engine cannot tell the two
# apart. That is what makes the whole thing testable with no network
# and reproducible afterwards: a report built from a recorded history
# is byte-identical every time it is run, which is the property you
# actually need when somebody asks you to justify a figure months
# later.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..models import Direction, Transfer
from ..prices import TableFxSource, TablePriceSource


@dataclass
class Case:
    """Everything needed to produce one report."""

    financial_year: str
    owned: set[str]
    transfers: list[Transfer]
    prices: TablePriceSource
    fx: TableFxSource


def load(path: str | Path) -> Case:
    raw = json.loads(Path(path).read_text())

    transfers = [
        Transfer(
            tx_hash=row["tx_hash"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            asset=row["asset"].upper(),
            amount=Decimal(str(row["amount"])),
            direction=Direction(row["direction"]),
            counterparty=row["counterparty"].lower(),
            wallet=row["wallet"].lower(),
        )
        for row in raw["transfers"]
    ]

    # "ETH|2026-04-10" is flattened in the file because JSON keys cannot
    # be tuples. Unflatten here, at the edge, so nothing downstream has
    # to know about the file format.
    prices: dict[tuple[str, str], str] = {}
    for key, value in raw["usd_prices"].items():
        asset, day = key.split("|")
        prices[(asset, day)] = value

    return Case(
        financial_year=raw["financial_year"],
        owned={a.lower() for a in raw["owned_wallets"]},
        transfers=transfers,
        prices=TablePriceSource(prices),
        fx=TableFxSource(raw["usd_inr"]),
    )
