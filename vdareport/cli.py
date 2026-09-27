# vdareport/cli.py
#
# Two ways in.
#
#   python3 -m vdareport --fixture fixtures/taxpayer_a.json
#       Replays a recorded history. No network, no key, deterministic.
#
#   python3 -m vdareport --wallet 0x... --wallet 0x... --fy 2026-27
#       Reads real wallets off the chain. Needs a key in .env.
#       Without --prices it still classifies the history, which is the
#       part that is hard and needs no price data at all.
#
# The exit code carries information: 0 for a complete report, 1 when
# anything went unvalued, 2 when the chain could not be read. A report
# with holes is not a crash, but it is not a clean run either, and a
# script that files things needs to be able to tell the difference.

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .classify import classify_all, summarise
from .models import Kind
from .prices import Pricer, TableFxSource, TablePriceSource
from .report import build, render_csv, render_text
from .sources import fixture


def _load_price_tables(path: Path) -> Pricer:
    raw = json.loads(path.read_text())
    prices: dict[tuple[str, str], str] = {}
    for key, value in raw["usd_prices"].items():
        asset, day = key.split("|")
        prices[(asset, day)] = value
    return Pricer(TablePriceSource(prices), TableFxSource(raw["usd_inr"]))


def _classification_only(transfers, owned) -> str:
    """What can be said with no price data at all.

    Worth printing on its own, because working out which movements are
    internal is the hard part and it needs no prices.
    """
    events = classify_all(transfers, owned)
    counts = summarise(events)
    lines = [
        "",
        "  No price data supplied, so no rupee figures. Here is the",
        "  classification, which is the part that does not need prices:",
        "",
        f"    movements read      {sum(counts.values())}",
        f"    acquisitions        {counts.get('acquisition', 0)}",
        f"    disposals           {counts.get('disposal', 0)}",
        f"    self-transfers      {counts.get('self_transfer', 0)}",
        "",
    ]
    internal = [e for e in events if e.kind is Kind.SELF_TRANSFER]
    if internal:
        lines += ["  Movements between your own wallets, which are NOT sales:", ""]
        for e in internal:
            t = e.transfer
            lines.append(
                f"    {t.timestamp.date().isoformat()}  {t.amount} {t.asset}  "
                f"{t.tx_hash[:18]}..."
            )
        lines += ["", "  A tool that missed these would have reported them as",
                  "  taxable disposals.", ""]
    lines += ["  Pass --prices to produce the Schedule VDA working.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vdareport",
        description=(
            "Schedule VDA working papers from on-chain evidence. Every "
            "figure traces to a transaction hash, or is reported as unknown."
        ),
    )
    parser.add_argument("--fixture", type=Path, help="replay a recorded history")
    parser.add_argument("--wallet", action="append", default=[], metavar="0x...",
                        help="a wallet the taxpayer owns (repeat for each one)")
    parser.add_argument("--fy", default="2026-27", help="financial year, e.g. 2026-27")
    parser.add_argument("--prices", type=Path, help="recorded price and FX tables")
    parser.add_argument("--chain-id", type=int, default=1, help="1 = Ethereum mainnet")
    parser.add_argument("--csv", type=Path, help="also write the Schedule VDA table here")
    parser.add_argument("--most-recent", type=int, metavar="N",
                        help="sample the last N movements per wallet instead "
                             "of reading the whole history. For looking, not "
                             "for filing — the same flag vdareport.snapshot "
                             "takes, so the two agree about what was read.")

    args = parser.parse_args(argv)

    # ---- where the history comes from -----------------------------
    if args.fixture:
        case = fixture.load(args.fixture)
        transfers, owned = case.transfers, case.owned
        pricer = Pricer(case.prices, case.fx)
        financial_year = case.financial_year

    elif args.wallet:
        from .sources import etherscan

        owned = {w.strip().lower() for w in args.wallet}
        print(f"  reading {len(owned)} wallet(s) off the chain...", file=sys.stderr)
        try:
            transfers = etherscan.fetch_wallets(
                sorted(owned), chain_id=args.chain_id,
                most_recent=args.most_recent,
            )
        except etherscan.EtherscanError as exc:
            print(f"\n  could not read the chain: {exc}\n", file=sys.stderr)
            return 2
        print(f"  {len(transfers)} movement(s) found", file=sys.stderr)

        financial_year = args.fy
        if not args.prices:
            print(_classification_only(transfers, owned))
            return 0
        pricer = _load_price_tables(args.prices)

    else:
        parser.error("give me either --fixture or at least one --wallet")
        return 2

    # ---- the report -----------------------------------------------
    report, _events = build(transfers, owned, pricer, financial_year)
    print(render_text(report))

    if args.most_recent:
        print(f"  NOTE: built from a sample of the last {args.most_recent} "
              "movement(s) per wallet,")
        print("  not the whole history. Not a filing.\n")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        args.csv.write_text(render_csv(report))
        print(f"  Schedule VDA table written to {args.csv}\n")

    return 0 if report.is_complete else 1
