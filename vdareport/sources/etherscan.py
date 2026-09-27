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

# Etherscan returns at most this many rows per request, silently. Asking
# for a wallet with more history than this and taking what comes back is
# how you file a return that omits four years of transactions.
PAGE_SIZE = 10000

# Some hosts reject urllib's default identifier outright.
HEADERS = {"User-Agent": "vda-report/0.1"}


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
    request = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
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


def _page(wallet: str, chain_id: int, key: str, start_block: int,
          sort: str = "asc", offset: int = PAGE_SIZE) -> list[dict]:
    return _call({
        "chainid": chain_id,
        "module": "account",
        "action": "txlist",
        "address": wallet,
        "startblock": start_block,
        "endblock": 99999999,
        "page": 1,
        "offset": offset,
        "sort": sort,
        "apikey": key,
    })


def fetch_wallet(
    wallet: str,
    chain_id: int = 1,
    key: str | None = None,
    most_recent: int | None = None,
    max_pages: int = 100,
) -> list[Transfer]:
    """Every ETH movement this wallet has seen, oldest first.

    Etherscan caps a single response at PAGE_SIZE rows and says nothing
    about it — HTTP 200, a full-looking list, and everything past the cap
    simply absent. A wallet with more history than that produces a clean,
    confident, WRONG report. So this walks forward by block range until a
    page comes back short.

    The walk restarts from the last block seen rather than the one after
    it, because a single block can hold several of the wallet's
    transactions and a page boundary can fall inside one. That refetches
    a few rows; they are deduplicated by hash. Losing rows is
    unacceptable, fetching some twice is merely wasteful.

    `most_recent` takes just the last N movements instead of the whole
    history — useful for looking at a large wallet quickly. It is
    explicitly a sample, not a filing.
    """
    key = key or api_key()

    if most_recent:
        rows = _page(wallet, chain_id, key, 0, sort="desc", offset=most_recent)
        return sorted(to_transfers(rows, wallet),
                      key=lambda t: (t.timestamp, t.tx_hash))

    seen: dict[str, dict] = {}
    start_block = 0

    for _ in range(max_pages):
        page = _page(wallet, chain_id, key, start_block)
        if not page:
            break

        before = len(seen)
        for row in page:
            seen[str(row["hash"])] = row

        if len(page) < PAGE_SIZE:
            break                      # a short page is the end of the history
        if len(seen) == before:
            break                      # no progress: one block exceeds a page

        start_block = int(page[-1]["blockNumber"])
        time.sleep(PAUSE_SECONDS)
    else:
        raise EtherscanError(
            f"{wallet} has more history than {max_pages} pages of "
            f"{PAGE_SIZE}; raise max_pages rather than filing a partial one"
        )

    return sorted(to_transfers(list(seen.values()), wallet),
                  key=lambda t: (t.timestamp, t.tx_hash))


def fetch_wallets(wallets: list[str], chain_id: int = 1,
                  most_recent: int | None = None) -> list[Transfer]:
    """All of the taxpayer's wallets, pooled into one history.

    This is where the modelling decision becomes real data: one list,
    one taxpayer, no notion of which address anything belongs to except
    the field on each Transfer.

    `most_recent` samples each wallet instead of reading it whole. Good
    for looking; never for filing.
    """
    key = api_key()
    everything: list[Transfer] = []
    for index, wallet in enumerate(wallets):
        if index:
            time.sleep(PAUSE_SECONDS)
        everything.extend(
            fetch_wallet(wallet, chain_id=chain_id, key=key, most_recent=most_recent)
        )
    return sorted(everything, key=lambda t: (t.timestamp, t.tx_hash))
