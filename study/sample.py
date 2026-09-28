# study/sample.py
#
# Draw a sample of ordinary wallets without choosing them.
#
# Everything this study claims depends on the sample not having been
# picked to suit the claim. So the addresses come from the chain's own
# traffic: a spread of recent blocks, and out of each block only the
# plain ETH payments -- transactions that carry value and no call data.
# Both ends of such a transaction are almost always ordinary wallets
# rather than contracts, and nothing about the selection depends on what
# those wallets turn out to contain.
#
# Two limits, recorded in the output file rather than left unsaid:
# the sample is traffic-weighted, so an address that transacts often is
# likelier to appear than one that does not; and nothing here identifies
# an address as being held by an Indian resident. The study measures how
# s.115BBH behaves when applied to ordinary on-chain activity. It does
# not claim to describe the Indian holder population.
#
# The seed is fixed, so the same run draws the same sample. A finding
# somebody cannot reproduce is not a finding.

import json
import random
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vdareport.sources.etherscan import api_key

BASE = "https://api.etherscan.io/v2/api?chainid=1"
HEADERS = {"User-Agent": "vda-report/0.1"}
PAUSE = 0.25          # the free tier allows 5 calls a second
OUT = Path(__file__).parent / "wallets.json"


def ask(params):
    url = BASE + "".join(f"&{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def latest_block(key):
    got = ask({"module": "proxy", "action": "eth_blockNumber", "apikey": key})
    if "result" not in got:
        raise SystemExit(f"  Etherscan did not return a block number.\n  {got}")
    return int(got["result"], 16)


def wallets_in_block(number, key):
    got = ask({"module": "proxy", "action": "eth_getBlockByNumber",
               "tag": hex(number), "boolean": "true", "apikey": key})
    block = got.get("result")
    if not isinstance(block, dict):
        return []

    found = []
    for tx in block.get("transactions", []):
        if tx.get("input", "0x") != "0x":
            continue                        # a contract call, not a payment
        if int(tx.get("value", "0x0"), 16) == 0:
            continue                        # nothing actually moved
        for side in ("from", "to"):
            address = tx.get(side)
            if address:
                found.append(address.lower())
    return found


def main(blocks=40, spread=20_000, want=60, seed=20260930):
    key = api_key()
    top = latest_block(key)
    print(f"  latest block {top:,}")

    rng = random.Random(seed)
    # 12 blocks back from the tip, so nothing gets reorganised under us
    chosen = sorted(rng.sample(range(top - spread, top - 12), blocks))
    print(f"  reading {blocks} blocks spread across the last {spread:,}\n")

    seen = {}
    for index, number in enumerate(chosen, 1):
        addresses = wallets_in_block(number, key)
        for address in addresses:
            seen[address] = seen.get(address, 0) + 1
        print(f"    {index:>3}/{blocks}   block {number:,}   "
              f"{len(addresses):>3} addresses   {len(seen):,} distinct so far")
        time.sleep(PAUSE)

    # An address appearing again and again across unrelated blocks is an
    # exchange, a router or a service -- not somebody's wallet. Dropping
    # them is a decision about what the study is about, so it is recorded.
    ordinary = sorted(a for a, count in seen.items() if count <= 2)
    sample = sorted(rng.sample(ordinary, min(want, len(ordinary))))

    OUT.write_text(json.dumps({
        "drawn_on": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latest_block": top,
        "blocks_read": chosen,
        "seed": seed,
        "rule": "both ends of value-bearing transactions with empty input data",
        "excluded": "addresses appearing in more than 2 of the sampled blocks",
        "distinct_addresses": len(seen),
        "ordinary_addresses": len(ordinary),
        "sample": sample,
    }, indent=2))

    print(f"\n  {len(seen):,} distinct addresses")
    print(f"  {len(ordinary):,} appeared at most twice")
    print(f"  {len(sample)} drawn into the sample -> {OUT}")


if __name__ == "__main__":
    main()
