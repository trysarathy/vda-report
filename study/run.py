# study/run.py
#
# Apply the engine to the drawn sample and record what it finds.
#
# Two things are measured, and neither requires knowing WHY a transfer
# happened -- which the chain does not record, and which this study
# therefore does not claim to know.
#
#   1. Disclosure weight.  What share of the Schedule VDA rows a
#      taxpayer must file carry almost no money?  A row is a mandatory
#      disclosure line whatever its size: a disposal realising forty
#      paise is reported, taxed at 30% and denied set-off in exactly the
#      same way as one realising four lakh.
#
#   2. Netting error.  s.115BBH allows no set-off of losses against
#      gains.  Every tool built for a jurisdiction that does allow it
#      computes gains minus losses.  The distance between those two
#      numbers, across real histories, is what getting the rule wrong
#      actually costs.
#
# Prices are fetched once for the whole sample, not once per wallet.
# The price of ETH on a given day does not depend on whose wallet is
# asking, so the same table serves all sixty reports.

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vdareport.prices import Pricer, TableFxSource, TablePriceSource
from vdareport.report import build as build_report
from vdareport.snapshot import build as build_prices
from vdareport.sources import etherscan

HERE = Path(__file__).parent
WALLETS = HERE / "wallets.json"
RESULTS = HERE / "results.json"
PRICES = HERE / "prices.json"

MOVEMENTS = 50            # most recent movements read per wallet
FY = "2026-27"
THRESHOLDS = [Decimal("1"), Decimal("10"), Decimal("100")]
PAUSE = 0.25


def rupees(amount):
    return f"{amount:,.2f}"


def fetch_all(addresses):
    """Read each wallet. A wallet that cannot be read is recorded as
    unread, never as empty -- the difference matters."""
    movements, unread = {}, {}
    for index, address in enumerate(addresses, 1):
        try:
            got = etherscan.fetch_wallet(address, most_recent=MOVEMENTS)
        except Exception as exc:                                # noqa: BLE001
            unread[address] = f"{type(exc).__name__}: {exc}"
            got = []
        movements[address] = got
        note = f"   UNREAD: {unread[address]}" if address in unread else ""
        print(f"    {index:>3}/{len(addresses)}  {address[:12]}...  "
              f"{len(got):>3} movements{note}")
        time.sleep(PAUSE)
    return movements, unread


def measure(report):
    """Everything this study counts, for one wallet."""
    rows = report.matches
    gains = sum((m.gain_inr for m in rows if m.gain_inr > 0), Decimal(0))

    small_rows, small_gains = {}, {}
    for limit in THRESHOLDS:
        under = [m for m in rows if m.consideration_inr < limit]
        small_rows[str(limit)] = len(under)
        small_gains[str(limit)] = str(
            sum((m.gain_inr for m in under if m.gain_inr > 0), Decimal(0))
        )

    netted = report.total_gains_inr - report.total_losses_inr
    if netted < 0:
        netted = Decimal(0)
    payable_if_netted = netted * Decimal("0.30") * Decimal("1.04")

    return {
        "rows": len(rows),
        "gains_inr": str(gains),
        "losses_inr": str(report.total_losses_inr),
        "payable_inr": str(report.total_payable_inr),
        "payable_if_netted_inr": str(payable_if_netted),
        "understated_inr": str(report.total_payable_inr - payable_if_netted),
        "rows_under": small_rows,
        "gains_under": small_gains,
        "gaps": len(report.gaps),
        "complete": report.is_complete,
        "smallest_row_inr": str(min((m.consideration_inr for m in rows),
                                    default=Decimal(0))),
    }


def main():
    drawn = json.loads(WALLETS.read_text())
    addresses = drawn["sample"]
    print(f"  {len(addresses)} wallets drawn on {drawn['drawn_on']}")
    print()

    print("  reading the chain")
    movements, unread = fetch_all(addresses)

    pooled = [t for rows in movements.values() for t in rows]
    print()
    print(f"  {len(pooled):,} movements in total")
    if not pooled:
        raise SystemExit("  nothing was read -- stopping rather than "
                         "reporting an empty study")

    print()
    print("  pricing (once for the whole sample)")
    tables = build_prices(pooled, pause_seconds=0, workers=8)
    PRICES.write_text(json.dumps(tables, indent=2))

    lookup = {}
    for key, value in tables["usd_prices"].items():
        asset, day = key.split("|")
        lookup[(asset, day)] = value
    pricer = Pricer(TablePriceSource(lookup), TableFxSource(tables["usd_inr"]))

    print()
    print("  computing sixty separate returns")
    results = {}
    for address, rows in movements.items():
        if not rows:
            continue
        report, _events = build_report(rows, {address}, pricer, FY)
        results[address] = measure(report)

    RESULTS.write_text(json.dumps({
        "financial_year": FY,
        "movements_per_wallet": MOVEMENTS,
        "drawn": drawn,
        "unread": unread,
        "wallets": results,
    }, indent=2))

    filed = {a: r for a, r in results.items() if r["rows"]}
    all_rows = sum(r["rows"] for r in filed.values())
    all_gains = sum(Decimal(r["gains_inr"]) for r in filed.values())
    understated = sum(Decimal(r["understated_inr"]) for r in filed.values())
    payable = sum(Decimal(r["payable_inr"]) for r in filed.values())

    print()
    print("=" * 66)
    print(f"  {len(addresses)} wallets drawn, {len(unread)} unread, "
          f"{len(filed)} with a return to file in FY {FY}")
    print(f"  {all_rows:,} Schedule VDA rows")
    print("=" * 66)

    if all_rows:
        print()
        print("  rows carrying less than:")
        for limit in THRESHOLDS:
            n = sum(r["rows_under"][str(limit)] for r in filed.values())
            g = sum(Decimal(r["gains_under"][str(limit)]) for r in filed.values())
            share = 100 * n / all_rows
            gshare = (100 * g / all_gains) if all_gains else Decimal(0)
            print(f"      Rs {limit:>4}   {n:>5} rows  ({share:5.1f}% of rows)"
                  f"   carrying {gshare:5.2f}% of the gains")
        print()
        print(f"  tax payable, correctly            Rs {rupees(payable)}")
        print(f"  tax payable, if losses were netted Rs "
              f"{rupees(payable - understated)}")
        print(f"  understated by                     Rs {rupees(understated)}")
        if payable:
            print(f"                                     "
                  f"({100 * understated / payable:.1f}% of the true liability)")

    print()
    print(f"  written to {RESULTS.name} and {PRICES.name}")


if __name__ == "__main__":
    main()
