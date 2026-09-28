# study/robust.py
#
# Try to break the surviving finding.
#
# The liability total turned out to be one wallet wearing a costume. A
# pooled ratio -- all the small rows over all the rows -- can fail the
# same way: one address with four hundred dust rows would produce the
# same 38% and mean nothing about anybody else.
#
# So compute the share WITHIN each wallet and take the median across
# wallets. A median cannot be moved by one address no matter how large
# it is. If the finding survives that, it is a statement about ordinary
# wallets. If it does not, it was never a finding.

import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median

# Which run to look at: results.json by default, or whichever file is
# named on the command line.
NAME = sys.argv[1] if len(sys.argv) > 1 else "results.json"
DATA = json.loads((Path(__file__).parent / NAME).read_text())
WALLETS = {a: r for a, r in DATA["wallets"].items() if r["rows"]}


def rule(title):
    print()
    print(f"  {title}")
    print("  " + "-" * 62)


counts = sorted((r["rows"] for r in WALLETS.values()), reverse=True)
rule("IS THE ROW COUNT ALSO ONE WALLET?")
print(f"    {sum(counts)} rows across {len(WALLETS)} wallets")
print(f"    largest wallet   {counts[0]} rows "
      f"({100*counts[0]/sum(counts):.1f}% of all rows)")
print(f"    median wallet    {median(counts):.0f} rows")
print(f"    smallest         {counts[-1]} rows")
print(f"    top five         {counts[:5]}")

rule("THE SHARE WITHIN EACH WALLET, NOT POOLED")
for limit in ("1", "10", "100"):
    shares = [100 * r["rows_under"][limit] / r["rows"] for r in WALLETS.values()]
    touched = sum(1 for s in shares if s > 0)
    print(f"    under Rs {limit:>3}   median wallet {median(shares):5.1f}% of its rows"
          f"   |  {touched} of {len(WALLETS)} wallets affected")

rule("WHO FILES ROWS BUT OWES NOTHING?")
nothing = [a for a, r in WALLETS.items() if Decimal(r["payable_inr"]) == 0]
rows_for_nothing = sum(WALLETS[a]["rows"] for a in nothing)
print(f"    {len(nothing)} of {len(WALLETS)} filers owe Rs 0.00")
print(f"    between them they must still file {rows_for_nothing} rows")
print(f"    ({100*rows_for_nothing/sum(counts):.1f}% of every row in the sample,")
print(f"     carrying no liability whatsoever)")

rule("WHAT THE WINDOW COULD NOT SEE")
print(f"    {sum(r['gaps'] for r in WALLETS.values())} gaps across "
      f"{len(WALLETS)} wallets")
print(f"    {sum(1 for r in WALLETS.values() if not r['complete'])} returns "
      f"have at least one hole")
print(f"    each hole is a disposal whose acquisition predates the "
      f"{DATA['movements_per_wallet']}-movement window")
print()
