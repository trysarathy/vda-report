# study/compare.py
#
# What the window cost, measured.
#
# Two runs over the same sixty addresses, differing in one thing: how
# much history was read. Everything else -- the seed, the sample, the
# price source, the engine -- is identical. So any difference between
# them is attributable to the window and to nothing else.
#
# And then the question that decides how the netting result may be
# stated: is it one wallet, or is it many? A ratio computed across a
# pooled total answers the first question badly. A median across
# wallets answers it properly.

import json
import sys
from decimal import Decimal
from pathlib import Path
from statistics import median

HERE = Path(__file__).parent
WINDOW = json.loads((HERE / "results.json").read_text())
FULL = json.loads((HERE / "results-full.json").read_text())


def rule(title):
    print()
    print(f"  {title}")
    print("  " + "-" * 64)


def totals(data):
    filed = {a: r for a, r in data["wallets"].items() if r["rows"]}
    return {
        "wallets": len(filed),
        "rows": sum(r["rows"] for r in filed.values()),
        "gains": sum(Decimal(r["gains_inr"]) for r in filed.values()),
        "losses": sum(Decimal(r["losses_inr"]) for r in filed.values()),
        "payable": sum(Decimal(r["payable_inr"]) for r in filed.values()),
        "understated": sum(Decimal(r["understated_inr"]) for r in filed.values()),
        "gaps": sum(r["gaps"] for r in filed.values()),
        "holes": sum(1 for r in filed.values() if not r["complete"]),
    }


w, f = totals(WINDOW), totals(FULL)

rule("WHAT THE WINDOW COST")
print(f"    {'':<22}{'50 movements':>20}{'full history':>20}")
for key, label in [("wallets", "wallets filing"), ("rows", "Schedule VDA rows"),
                   ("gains", "gains"), ("losses", "losses"),
                   ("payable", "payable"), ("understated", "netting error"),
                   ("gaps", "gaps"), ("holes", "returns with holes")]:
    a, b = w[key], f[key]
    fmt = (lambda v: f"{v:,.2f}") if isinstance(a, Decimal) else (lambda v: f"{v:,}")
    print(f"    {label:<22}{fmt(a):>20}{fmt(b):>20}")

for name, t in (("50 movements", w), ("full history", f)):
    share = 100 * t["understated"] / t["payable"] if t["payable"] else 0
    print(f"\n    netting error as a share of true liability, {name}: {share:.1f}%")

rule("IS THE NETTING ERROR ONE WALLET?")
filed = {a: r for a, r in FULL["wallets"].items()
         if r["rows"] and Decimal(r["payable_inr"]) > 0}
ratios = {a: 100 * Decimal(r["understated_inr"]) / Decimal(r["payable_inr"])
          for a, r in filed.items()}
ranked = sorted(ratios.items(), key=lambda kv: kv[1], reverse=True)

print(f"    {len(filed)} wallets owe anything at all")
print(f"    median wallet's liability overstated by netting:  "
      f"{median(ratios.values()):.1f}%")
print(f"    wallets where netting would change it by >50%:   "
      f"{sum(1 for v in ratios.values() if v > 50)} of {len(filed)}")
print(f"    wallets where netting would change it by >10%:   "
      f"{sum(1 for v in ratios.values() if v > 10)} of {len(filed)}")
print()
print("    worst affected:")
for address, share in ranked[:5]:
    r = FULL["wallets"][address]
    print(f"      {address[:14]}...  {share:5.1f}%   "
          f"{r['rows']:>4} rows   payable Rs {Decimal(r['payable_inr']):,.2f}")

rule("THE BIGGEST WALLET ON ITS OWN")
biggest = max(filed, key=lambda a: Decimal(FULL["wallets"][a]["payable_inr"]))
r = FULL["wallets"][biggest]
gains, losses = Decimal(r["gains_inr"]), Decimal(r["losses_inr"])
print(f"    {biggest}")
print(f"      {r['rows']} rows")
print(f"      gains            Rs {gains:,.2f}")
print(f"      losses           Rs {losses:,.2f}")
print(f"      net economically Rs {gains - losses:,.2f}")
print(f"      tax due          Rs {Decimal(r['payable_inr']):,.2f}")

rest = {a: v for a, v in filed.items() if a != biggest}
rest_pay = sum(Decimal(FULL["wallets"][a]["payable_inr"]) for a in rest)
rest_und = sum(Decimal(FULL["wallets"][a]["understated_inr"]) for a in rest)
print()
print(f"    everyone else together:")
print(f"      payable          Rs {rest_pay:,.2f}")
print(f"      netting error    Rs {rest_und:,.2f}"
      f"   ({100 * rest_und / rest_pay if rest_pay else 0:.1f}%)")
print()
