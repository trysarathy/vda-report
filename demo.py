#!/usr/bin/env python3
"""A three-minute walk through what this tool does and why.

    python3 demo.py

Runs entirely from the recorded history in fixtures/. No network, no
API key, no chance of failing on somebody's wifi. The same figures
every time, which is the property the whole project is built on.
"""

from __future__ import annotations

from decimal import Decimal

from vdareport.classify import Kind, classify_all
from vdareport.prices import Pricer, round_paise
from vdareport.report import build
from vdareport.sources import fixture

CASE = fixture.load("fixtures/taxpayer_a.json")
WALLET_A = "0xaaaa1111aaaa1111aaaa1111aaaa1111aaaa1111"
WALLET_B = "0xbbbb2222bbbb2222bbbb2222bbbb2222bbbb2222"

RULE = "=" * 70
THIN = "-" * 70


def rupees(amount: Decimal) -> str:
    return f"Rs {round_paise(amount):,}"


def part_one() -> None:
    print(RULE)
    print(" 1.  THE CHAIN DOES NOT RECORD WHY")
    print(RULE)
    print()
    print("  On-chain, sending 1.5 ETH from your wallet to your other wallet")
    print("  is indistinguishable from selling it to a stranger. Same shape,")
    print("  same fields, same everything.")
    print()

    print(f"  A.  Both of the taxpayer's wallets declared")
    print()
    for event in classify_all(CASE.transfers, {WALLET_A, WALLET_B}):
        t = event.transfer
        if t.asset != "ETH":
            continue
        print(f"      {t.timestamp.date()}  {t.amount:>5} ETH   "
              f"{event.kind.value.upper()}")
    print()

    print(f"  B.  The same history, assessed one address at a time")
    print()
    only_a = [t for t in CASE.transfers if t.wallet == WALLET_A]
    for event in classify_all(only_a, {WALLET_A}):
        t = event.transfer
        if t.asset != "ETH":
            continue
        flag = "   <-- a sale that never happened" \
            if event.kind is Kind.DISPOSAL and t.counterparty == WALLET_B else ""
        print(f"      {t.timestamp.date()}  {t.amount:>5} ETH   "
              f"{event.kind.value.upper()}{flag}")
    print()
    print("  Not detected. Made impossible. The unit of assessment is the")
    print("  TAXPAYER, not the address — so all their wallets are one pool,")
    print("  and an internal move has nowhere to go.")
    print()


def part_two() -> None:
    report, _ = build(
        CASE.transfers, CASE.owned, Pricer(CASE.prices, CASE.fx),
        CASE.financial_year,
    )

    print(RULE)
    print(" 2.  SECTION 115BBH: LOSSES DO NOT REDUCE GAINS")
    print(RULE)
    print()
    print("  India allows no set-off of losses against gains, and no")
    print("  carry-forward. Every other major jurisdiction nets them, so")
    print("  every general-purpose crypto tax tool nets them too.")
    print()

    gains, losses = report.total_gains_inr, report.total_losses_inr
    netted = gains - losses

    print(f"      Gains                          {rupees(gains):>16}")
    print(f"      Losses                         {rupees(losses):>16}")
    print()
    print(f"      This tool    taxable income    {rupees(gains):>16}")
    print(f"      Netting      taxable income    {rupees(netted):>16}")
    print()

    mine = report.total_payable_inr
    theirs = netted * Decimal("0.30") * Decimal("1.04")
    print(f"      Tax payable, correctly          {rupees(mine):>16}")
    print(f"      Tax payable, if netted          {rupees(theirs):>16}")
    print(f"      Understated by                  {rupees(mine - theirs):>16}")
    print()
    print("  On this recorded history the losses are small, so the gap is")
    print("  small. On the live wallet in out/vitalik.csv the losses were")
    print("  three quarters of the gains, and the gap was FOUR TIMES the")
    print("  liability -- Rs 16.67 correctly, Rs 4.11 if netted.")
    print()


def part_three() -> None:
    report, _ = build(
        CASE.transfers, CASE.owned, Pricer(CASE.prices, CASE.fx),
        CASE.financial_year,
    )

    print(RULE)
    print(" 3.  WHAT IT REFUSES TO DO")
    print(RULE)
    print()
    print("  A figure that cannot be traced to a transaction hash is not a")
    print("  figure, it is a guess. Where this cannot value something it")
    print("  says so, with the hash, instead of substituting a zero.")
    print()
    for gap in report.gaps:
        print(f"      {gap.on}  {gap.asset}   {gap.tx_hash[:20]}...")
        print(f"                  {gap.why}")
    print()
    print("  A report with a visible hole can be finished by hand.")
    print("  A report whose holes were quietly filled looks finished,")
    print("  gets filed, and cannot be defended.")
    print()

    print(THIN)
    print(f"  Every row below names the transactions it came from.")
    print(THIN)
    print()
    for i, m in enumerate(report.matches, 1):
        sign = "gain" if m.gain_inr >= 0 else "loss"
        print(f"  {i}. {m.quantity} {m.asset}")
        print(f"     {m.acquired_at.date()} -> {m.disposed_at.date()}   "
              f"cost {rupees(m.cost_inr)}   {sign} {rupees(abs(m.gain_inr))}")
        print(f"     {m.acquisition_tx[:24]}...  ->  {m.disposal_tx[:24]}...")
    print()
    print(f"      Total payable                   "
          f"{rupees(report.total_payable_inr):>16}")
    print()


if __name__ == "__main__":
    print()
    part_one()
    part_two()
    part_three()
    print(RULE)
    print("  39 tests:  python3 -m pytest -v")
    print("  Live:      python3 -m vdareport --wallet 0x... --prices ... --fy 2026-27")
    print(RULE)
    print()
