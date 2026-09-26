# vdareport/report.py
#
# Section 115BBH, and the Schedule VDA working paper.
#
# This is the file where India stops resembling anywhere else.
#
# Almost every other country lets you net crypto losses against crypto
# gains. s.115BBH does not:
#
#   - gains are taxed at a flat 30%
#   - losses may NOT be set off against gains
#   - losses may NOT be carried forward
#   - the only deduction allowed is the cost of acquisition
#
# A general-purpose crypto tax tool nets them, because netting is what
# almost everywhere else does. For India that understates the liability,
# and the taxpayer finds out when the notice arrives. So the report
# states gains and losses separately, and taxes the gains alone.
#
# The financial year is the other thing that has to be got right. It
# runs 1 April to 31 March in INDIAN time, not UTC. That is why every
# timestamp in this codebase carries a timezone: a disposal at 23:00 UTC
# on 31 March has already become 1 April in India and belongs to the
# NEXT year. Without a timezone, that comparison is not possible to make
# correctly and the figure lands in the wrong return with nothing to
# show that it did.

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from .classify import Classified, classify_all
from .fifo import Gap, Match, run
from .models import Kind, Transfer
from .prices import PricedValue, Pricer, round_paise

IST = timezone(timedelta(hours=5, minutes=30))

TAX_RATE = Decimal("0.30")
CESS_RATE = Decimal("0.04")


def financial_year_bounds(fy: str) -> tuple[datetime, datetime]:
    """'2026-27' -> 1 Apr 2026 00:00 IST, up to but not including 1 Apr 2027."""
    start_year = int(fy.split("-")[0])
    return (
        datetime(start_year, 4, 1, tzinfo=IST),
        datetime(start_year + 1, 4, 1, tzinfo=IST),
    )


@dataclass
class Report:
    financial_year: str
    matches: list[Match]
    gaps: list[Gap]
    peak_balance_inr: Decimal | None
    peak_on: date | None
    peak_caveat: str | None

    # ---- s.115BBH ---------------------------------------------------

    @property
    def total_gains_inr(self) -> Decimal:
        return sum((m.gain_inr for m in self.matches if m.gain_inr > 0), Decimal("0"))

    @property
    def total_losses_inr(self) -> Decimal:
        return sum((-m.gain_inr for m in self.matches if m.gain_inr < 0), Decimal("0"))

    @property
    def taxable_income_inr(self) -> Decimal:
        # The whole point of this file. Losses are disclosed above and
        # deliberately absent here.
        return self.total_gains_inr

    @property
    def tax_at_30pct_inr(self) -> Decimal:
        return self.taxable_income_inr * TAX_RATE

    @property
    def cess_at_4pct_inr(self) -> Decimal:
        # Health and education cess is charged on the TAX, not on the income.
        return self.tax_at_30pct_inr * CESS_RATE

    @property
    def total_payable_inr(self) -> Decimal:
        return self.tax_at_30pct_inr + self.cess_at_4pct_inr

    @property
    def is_complete(self) -> bool:
        return not self.gaps


def _peak_balance(
    events: list[Classified], pricer: Pricer, start: datetime, end: datetime
) -> tuple[Decimal | None, date | None, str | None]:
    """Schedule FA wants the highest value the holding reached in the year.

    Walked event by event: holdings are updated on acquisitions and
    disposals, and everything held is valued on EVERY event date,
    self-transfers included — an internal move changes no quantity, but
    it is still a day we hold a price for, and the peak can fall on it.

    Two honest limits, named rather than buried:

      The peak is only sampled on days something happened. A true peak
      needs a price for every day of the year; the recorded tables hold
      prices for transaction dates only. So this is a floor, not a
      maximum.

      If some holding cannot be valued at all, it is excluded and the
      figure is returned with a caveat saying so. Returning nothing
      would throw away a real lower bound; returning it silently would
      claim more precision than exists. Schedule FA errors carry
      penalties up to Rs 10 lakh, so the caveat travels with the number.
    """
    held: dict[str, Decimal] = {}
    peak = Decimal("0")
    peak_on: date | None = None
    excluded: set[str] = set()

    for event in events:
        t = event.transfer
        asset = t.asset.upper()

        if event.kind is Kind.ACQUISITION:
            held[asset] = held.get(asset, Decimal("0")) + t.amount
        elif event.kind is Kind.DISPOSAL:
            held[asset] = held.get(asset, Decimal("0")) - t.amount

        if not (start <= t.timestamp < end):
            continue

        total = Decimal("0")
        for a, qty in held.items():
            if qty <= 0:
                continue
            valued = pricer.value_inr(a, qty, t.timestamp)
            if isinstance(valued, PricedValue):
                total += valued.inr
            else:
                excluded.add(a)

        if total > peak:
            peak, peak_on = total, t.timestamp.date()

    if peak_on is None:
        return None, None, "nothing valuable enough to report was held in the year"

    caveat = "sampled on transaction dates only, so this is a floor"
    if excluded:
        caveat += f"\n  and it excludes {', '.join(sorted(excluded))}, which could not be valued"
    return peak, peak_on, caveat


def build(
    transfers: list[Transfer],
    owned: set[str],
    pricer: Pricer,
    financial_year: str,
) -> tuple[Report, list[Classified]]:
    """The whole pipeline: classify, match, then filter to the year.

    Note the order. FIFO runs over the ENTIRE history, and only then are
    the rows filtered down to the year being filed. Reading just the
    filing year's transactions would get both the cost basis and the lot
    order wrong — a sale last year already consumed the oldest parcel,
    and this year's sale has to match against the next one.
    """
    events = classify_all(transfers, owned)
    ledger = run(events, pricer)
    start, end = financial_year_bounds(financial_year)

    in_year = [m for m in ledger.matches if start <= m.disposed_at < end]
    peak, peak_on, why = _peak_balance(events, pricer, start, end)

    return (
        Report(
            financial_year=financial_year,
            matches=in_year,
            gaps=ledger.gaps,
            peak_balance_inr=peak,
            peak_on=peak_on,
            peak_caveat=why,
        ),
        events,
    )


def _rupees(amount: Decimal) -> str:
    """Display only.

    The properties above keep full precision so that figures compose
    without compounding a rounding error; the rounding happens once,
    here, at the point the number is shown to a human.
    """
    return f"Rs {round_paise(amount):,}"


def render_text(report: Report) -> str:
    out = [
        "",
        f"  Schedule VDA working paper — FY {report.financial_year}",
        "  " + "=" * 58,
        "",
    ]

    if not report.matches:
        out.append("  No disposals in this financial year.")
    for i, m in enumerate(report.matches, 1):
        out += [
            f"  {i}. {m.quantity} {m.asset}",
            f"     acquired  {m.acquired_at.date()}   cost  {_rupees(m.cost_inr)}",
            f"     disposed  {m.disposed_at.date()}   for   {_rupees(m.consideration_inr)}",
            f"     {'gain' if m.gain_inr >= 0 else 'loss'}      "
            f"{_rupees(abs(m.gain_inr))}",
            f"     acquisition tx  {m.acquisition_tx[:18]}...",
            f"     disposal tx     {m.disposal_tx[:18]}...",
            "",
        ]

    out += [
        "  " + "-" * 58,
        f"  {'Gains':<32}{_rupees(report.total_gains_inr)}",
        f"  {'Losses (NOT deductible)':<32}{_rupees(report.total_losses_inr)}",
        f"  {'Taxable income':<32}{_rupees(report.taxable_income_inr)}",
        f"  {'Tax at 30%':<32}{_rupees(report.tax_at_30pct_inr)}",
        f"  {'Health & education cess 4%':<32}{_rupees(report.cess_at_4pct_inr)}",
        f"  {'Total payable':<32}{_rupees(report.total_payable_inr)}",
        "",
        "  s.115BBH allows no set-off of losses against gains and no",
        "  carry-forward. The losses above are disclosed, not deducted.",
        "",
        "  " + "-" * 58,
        "  Schedule FA — peak balance",
    ]
    if report.peak_balance_inr is not None:
        out.append(f"  at least {_rupees(report.peak_balance_inr)} on {report.peak_on}")
        if report.peak_caveat:
            out.append(f"  ({report.peak_caveat})")
    else:
        out.append(f"  UNKNOWN — {report.peak_caveat}")

    if report.gaps:
        out += ["", "  " + "-" * 58, f"  {len(report.gaps)} item(s) the engine refused to value:", ""]
        for g in report.gaps:
            out.append(f"    {g.on}  {g.asset}  {g.tx_hash[:18]}...")
            out.append(f"              {g.why}")
        out += [
            "",
            "  Each of these is a hole a human can close. None of them",
            "  became a zero.",
        ]

    out.append("")
    return "\n".join(out)


def render_csv(report: Report) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "Date of acquisition",
        "Date of transfer",
        "Asset",
        "Quantity",
        "Cost of acquisition (INR)",
        "Consideration received (INR)",
        "Income / (loss) (INR)",
        "Acquisition tx",
        "Disposal tx",
    ])
    for m in report.matches:
        writer.writerow([
            m.acquired_at.date().isoformat(),
            m.disposed_at.date().isoformat(),
            m.asset,
            str(m.quantity),
            str(m.cost_inr),
            str(m.consideration_inr),
            str(m.gain_inr),
            m.acquisition_tx,
            m.disposal_tx,
        ])
    return buffer.getvalue()
