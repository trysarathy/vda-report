# study/inspect.py
#
# Interrogate the result before anybody else does.
#
# An aggregate across sixty wallets can be one wallet wearing a costume.
# Before either finding can be stated out loud, three things have to be
# true of it: the total is not one address, the small rows are small in
# money and not only in count, and the wallets with no losses are absent
# for a reason we can name.

import json
from decimal import Decimal
from pathlib import Path
from statistics import median

DATA = json.loads((Path(__file__).parent / "results.json").read_text())
WALLETS = {a: r for a, r in DATA["wallets"].items() if r["rows"]}


def rupees(amount):
    return f"Rs {amount:,.2f}"


def rule(title):
    print()
    print(f"  {title}")
    print("  " + "-" * 62)


payable = {a: Decimal(r["payable_inr"]) for a, r in WALLETS.items()}
total = sum(payable.values())
ranked = sorted(payable.items(), key=lambda kv: kv[1], reverse=True)

rule("IS THE TOTAL ONE WALLET?")
for index, (address, amount) in enumerate(ranked[:5], 1):
    share = 100 * amount / total if total else 0
    print(f"    {index}.  {address[:14]}...  {rupees(amount):>18}   {share:5.1f}%")
top = 100 * ranked[0][1] / total if total else 0
print()
print(f"    largest single wallet        {top:.1f}% of all liability")
print(f"    largest five together        "
      f"{100 * sum(a for _, a in ranked[:5]) / total:.1f}%")
print(f"    median wallet                {rupees(median(payable.values()))}")

rule("ARE THE SMALL ROWS SMALL IN MONEY, NOT JUST IN COUNT?")
all_rows = sum(r["rows"] for r in WALLETS.values())
all_gains = sum(Decimal(r["gains_inr"]) for r in WALLETS.values())
print(f"    {all_rows:,} rows carrying {rupees(all_gains)} of gains")
print()
for limit in ("1", "10", "100"):
    n = sum(r["rows_under"][limit] for r in WALLETS.values())
    g = sum(Decimal(r["gains_under"][limit]) for r in WALLETS.values())
    print(f"    under Rs {limit:>3}   {n:>4} rows ({100*n/all_rows:4.1f}% of rows)"
          f"   {rupees(g):>14}"
          f"   ({100*g/all_gains if all_gains else 0:.4f}% of gains)")
print()
smallest = min(Decimal(r["smallest_row_inr"]) for r in WALLETS.values())
print(f"    smallest row in the whole sample   {rupees(smallest)}")

rule("WHERE DID THE LOSSES GO?")
with_losses = {a: r for a, r in WALLETS.items() if Decimal(r["losses_inr"]) > 0}
print(f"    {len(with_losses)} of {len(WALLETS)} wallets had any loss at all")
print(f"    total losses across the sample     "
      f"{rupees(sum(Decimal(r['losses_inr']) for r in WALLETS.values()))}")
print(f"    total gains                        {rupees(all_gains)}")

rule("HOW MUCH COULD NOT BE VALUED?")
gaps = sum(r["gaps"] for r in WALLETS.values())
complete = sum(1 for r in WALLETS.values() if r["complete"])
print(f"    {gaps} gap(s) across the sample")
print(f"    {complete} of {len(WALLETS)} returns complete with no holes")
print(f"    {len(DATA['wallets']) - len(WALLETS)} wallets read but with nothing "
      f"to file in FY {DATA['financial_year']}")
print(f"    {len(DATA['unread'])} wallets could not be read")
print()
