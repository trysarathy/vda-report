# vdareport/sources/etherscan.py
#
# The only module in this project that touches the network.
#
# Everything else is pure arithmetic over data. That boundary is
# deliberate: it means the engine can be tested with no network at all,
# it means swapping Etherscan for a direct node or another chain touches
# this one file, and it means a network failure can never quietly become
# a wrong number somewhere deep in the report.
#
# Known limit, named rather than hidden: `txlist` returns ETH movements
# only. ERC-20 tokens (USDT, USDC and the rest) live on a different
# endpoint, `tokentx`. That is the next piece of work, not an oversight.

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ..models import Direction, Transfer

BASE = "https://api.etherscan.io/v2/api"
WEI = Decimal(10) ** 18

# The free tier allows 5 calls a second. Staying under it is our job,
# not theirs.
PAUSE_SECONDS = 0.25


class EtherscanError(RuntimeError):
    """The chain could not be read.

    This is raised, never swallowed. An API failure that quietly returns
    an empty list is indistinguishable from a wallet with no history —
    and that difference is the difference between a correct return and
    an undeclared one.
    """


def api_key() -> str:
    """Read the key from .env, falling back to the environment."""
    env_file = Path(".env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("ETHERSCAN_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    from_env = os.environ.get("ETHERSCAN_API_KEY")
    if from_env:
        return from_env

    raise EtherscanError(
        "no ETHERSCAN_API_KEY found — expected a line reading "
        "ETHERSCAN_API_KEY=... in .env in the current directory"
    )


def _call(params: dict) -> list[dict]:
    """One request. Returns rows, or raises. Never returns a guess."""
    url = f"{BASE}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError) as exc:
        raise EtherscanError(f"could not reach Etherscan: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EtherscanError(f"Etherscan sent something that is not JSON: {exc}") from exc

    if payload.get("status") == "1":
        return payload.get("result", [])

    message = str(payload.get("message", ""))
    result = payload.get("result", "")

    # A genuinely empty wallet is not an error.
    if "No transactions found" in message or "No transactions found" in str(result):
        return []

    raise EtherscanError(f"Etherscan refused the request: {message} — {result}")


def to_transfers(rows: list[dict], wallet: str) -> list[Transfer]:
    """Turn Etherscan's JSON into this project's vocabulary.

    Etherscan's shape stops here. Nothing downstream ever sees a dict.
    """
    wallet = wallet.lower()
    transfers: list[Transfer] = []

    for row in rows:
        # A reverted transaction moved nothing. Reporting it as a
        # disposal would invent a sale that never happened.
        if str(row.get("isError", "0")) == "1":
            continue

        value = Decimal(str(row.get("value", "0")))
        if value == 0:
            # A contract call carrying no ETH. Real event, no movement.
            continue

        sender = str(row.get("from", "")).lower()
        recipient = str(row.get("to", "")).lower()

        if sender == wallet:
            direction, counterparty = Direction.OUT, recipient
        elif recipient == wallet:
            direction, counterparty = Direction.IN, sender
        else:
            # Neither side is this wallet. Not ours to record.
            continue

        if not counterparty:
            # Contract creation has no `to`. Skipped rather than guessed.
            continue

        transfers.append(
            Transfer(
                tx_hash=str(row["hash"]),
                timestamp=datetime.fromtimestamp(
                    int(row["timeStamp"]), tz=timezone.utc
                ),
                asset="ETH",
                # Wei to ETH, in Decimal. A float here would put a
                # rounding error into a tax return.
                amount=value / WEI,
                direction=direction,
                counterparty=counterparty,
                wallet=wallet,
            )
        )

    return transfers


def fetch_wallet(
    wallet: str,
    chain_id: int = 1,
    key: str | None = None,
    most_recent: int | None = None,
) -> list[Transfer]:
    """Every ETH movement this wallet has seen, oldest first.

    `most_recent` takes just the last N movements instead of the whole
    history — useful for looking at a large wallet quickly. Leave it off
    for anything you intend to file.
    """
    params = {
        "chainid": chain_id,
        "module": "account",
        "action": "txlist",
        "address": wallet,
        "startblock": 0,
        "endblock": 99999999,
        "apikey": key or api_key(),
    }
    if most_recent:
        params.update({"sort": "desc", "page": 1, "offset": most_recent})
    else:
        params["sort"] = "asc"

    rows = _call(params)

    # Always hand back oldest-first, whichever way we asked for it.
    # FIFO downstream depends on the order being real chronology.
    return sorted(to_transfers(rows, wallet), key=lambda t: (t.timestamp, t.tx_hash))


def fetch_wallets(wallets: list[str], chain_id: int = 1) -> list[Transfer]:
    """All of the taxpayer's wallets, pooled into one history.

    This is where the modelling decision becomes real data: one list,
    one taxpayer, no notion of which address anything belongs to except
    the field on each Transfer.
    """
    key = api_key()
    everything: list[Transfer] = []
    for index, wallet in enumerate(wallets):
        if index:
            time.sleep(PAUSE_SECONDS)
        everything.extend(fetch_wallet(wallet, chain_id=chain_id, key=key))
    return sorted(everything, key=lambda t: (t.timestamp, t.tx_hash))
