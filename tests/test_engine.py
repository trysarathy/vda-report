# tests/test_engine.py
#
# The tests are the argument.
#
# Anyone can write something that emits a plausible-looking tax table.
# The question is whether the arithmetic survives the cases that
# actually arise — and each test below is one of those cases, written
# down so it cannot quietly stop being true.
#
#   python3 -m pytest -v

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pytest

from vdareport.classify import Kind, classify_all
from vdareport.fifo import run
from vdareport.models import Direction, Transfer, utc
from vdareport.prices import (
    Pricer,
    TableFxSource,
    TablePriceSource,
    Unpriceable,
    round_paise,
)
from vdareport.report import build, financial_year_bounds, render_csv
from vdareport.sources import etherscan, fixture

FIXTURE = Path(__file__).parent.parent / "fixtures" / "taxpayer_a.json"

WALLET_A = "0xaaaa1111aaaa1111aaaa1111aaaa1111aaaa1111"
WALLET_B = "0xbbbb2222bbbb2222bbbb2222bbbb2222bbbb2222"
STRANGER = "0x7777buyer7777777777777777777777777777770"


@pytest.fixture
def case():
    return fixture.load(FIXTURE)


@pytest.fixture
def report(case):
    rep, events = build(
        case.transfers, case.owned, Pricer(case.prices, case.fx), case.financial_year
    )
    return rep, events


# ---------------------------------------------------------------------------
# The one that matters most
# ---------------------------------------------------------------------------


def test_moving_tokens_between_your_own_wallets_is_not_a_sale(case):
    """The failure mode this whole project is built around.

    On-chain, sending 1.5 ETH from your wallet to your other wallet is
    indistinguishable from selling it to a stranger. A tool that treats
    it as a disposal invents a taxable event out of nothing.
    """
    events = classify_all(case.transfers, case.owned)

    self_transfers = [e for e in events if e.kind is Kind.SELF_TRANSFER]
    assert len(self_transfers) == 2, "both legs of the internal move"
    for event in self_transfers:
        assert "same taxpayer" in event.reason

    disposal_counterparties = {
        e.transfer.counterparty for e in events if e.kind is Kind.DISPOSAL
    }
    assert WALLET_A not in disposal_counterparties
    assert WALLET_B not in disposal_counterparties


def test_the_same_movement_seen_from_both_wallets_is_not_double_counted(case):
    """The internal transfer appears twice in the raw data, once as an
    OUT and once as an IN. The pool must be unchanged by both."""
    ledger = run(classify_all(case.transfers, case.owned), Pricer(case.prices, case.fx))

    # 3 ETH acquired, 2.5 disposed of. If either leg of the
    # self-transfer had counted, this would not be 0.5.
    assert ledger.quantity_held("ETH") == Decimal("0.5")


# ---------------------------------------------------------------------------
# FIFO
# ---------------------------------------------------------------------------


def test_a_disposal_spanning_two_lots_produces_a_row_for_each(report):
    """Schedule VDA wants a row per acquisition-disposal pair, not a
    yearly total."""
    rep, _ = report
    eth = [m for m in rep.matches if m.asset == "ETH"]

    assert len(eth) == 2
    first, second = eth
    assert first.quantity == Decimal("2.0")
    assert first.acquired_at.date().isoformat() == "2026-04-10"
    assert second.quantity == Decimal("0.5")
    assert second.acquired_at.date().isoformat() == "2026-05-15"
    assert first.acquired_at < second.acquired_at, "oldest lot consumed first"


def test_the_arithmetic_is_right_to_the_paisa(report):
    """Worked by hand:

    lot 1   2.0 ETH x $2000 x 83.00 = Rs 3,32,000 cost
    lot 2   1.0 ETH x $2500 x 83.50 = Rs 2,08,750 cost
    sale    2.5 ETH x $3000 x 84.00 = Rs 6,30,000

    row 1   2.0 units: cost 3,32,000, consideration 5,04,000, gain 1,72,000
    row 2   0.5 units: cost 1,04,375, consideration 1,26,000, gain   21,625
    """
    rep, _ = report
    eth = [m for m in rep.matches if m.asset == "ETH"]

    assert eth[0].cost_inr == Decimal("332000.00")
    assert eth[0].consideration_inr == Decimal("504000.00")
    assert eth[0].gain_inr == Decimal("172000.00")

    assert eth[1].cost_inr == Decimal("104375.00")
    assert eth[1].consideration_inr == Decimal("126000.00")
    assert eth[1].gain_inr == Decimal("21625.00")


def test_the_rows_sum_back_to_the_consideration_received(report):
    """A schedule whose rows do not add up to what was actually received
    is a schedule that invites a question."""
    rep, _ = report
    eth = [m for m in rep.matches if m.asset == "ETH"]
    assert sum(m.consideration_inr for m in eth) == Decimal("630000.00")


def test_a_split_that_does_not_divide_evenly_still_reconciles():
    """Three rows of Rs 33.33 sum to Rs 99.99 against Rs 100.00
    received. The final slice absorbs the drift."""
    transfers = [
        Transfer("0x" + c * 64, utc(2026, 4, d), "ETH", Decimal("1"),
                 Direction.IN, STRANGER, WALLET_A)
        for c, d in zip("abc", (1, 2, 3))
    ]
    transfers.append(
        Transfer("0x" + "f" * 64, utc(2026, 5, 1), "ETH", Decimal("3"),
                 Direction.OUT, STRANGER, WALLET_A)
    )
    pricer = Pricer(
        TablePriceSource({("ETH", "2026-04-01"): "1", ("ETH", "2026-04-02"): "1",
                          ("ETH", "2026-04-03"): "1",
                          ("ETH", "2026-05-01"): "33.3333333333"}),
        TableFxSource({"2026-04-01": "1", "2026-04-02": "1",
                       "2026-04-03": "1", "2026-05-01": "1"}),
    )
    ledger = run(classify_all(transfers, {WALLET_A}), pricer)

    assert len(ledger.matches) == 3
    assert sum(m.consideration_inr for m in ledger.matches) == Decimal("100.00")


# ---------------------------------------------------------------------------
# Section 115BBH — the India-specific rule generic tools get wrong
# ---------------------------------------------------------------------------


def test_losses_do_not_reduce_gains(report):
    """s.115BBH allows no set-off of losses against gains and no
    carry-forward. A general-purpose crypto tax tool nets them, because
    that is what almost every other country does."""
    rep, _ = report

    assert rep.total_gains_inr == Decimal("193625.00")
    assert rep.total_losses_inr == Decimal("2860.00")
    assert rep.taxable_income_inr == rep.total_gains_inr
    assert rep.taxable_income_inr != rep.total_gains_inr - rep.total_losses_inr


def test_the_loss_is_recorded_even_though_it_is_not_deductible(report):
    """Not deductible is not the same as not disclosed."""
    rep, _ = report
    usdt = [m for m in rep.matches if m.asset == "USDT"]

    assert len(usdt) == 1
    assert usdt[0].gain_inr == Decimal("-2860.00")


def test_tax_and_cess(report):
    """30% flat, then 4% health and education cess on the tax itself."""
    rep, _ = report

    assert round_paise(rep.tax_at_30pct_inr) == Decimal("58087.50")
    assert round_paise(rep.cess_at_4pct_inr) == Decimal("2323.50")
    assert round_paise(rep.total_payable_inr) == Decimal("60411.00")


def test_the_financial_year_runs_on_indian_time():
    """A disposal at 23:00 UTC on 31 March has already become 1 April in
    India. Without a timezone that comparison cannot be made correctly,
    and the figure lands in the wrong return."""
    start, end = financial_year_bounds("2026-27")
    assert start <= utc(2026, 3, 31, 23, 0) < end, "23:00 UTC is 04:30 IST, next day"
    assert not (start <= utc(2026, 3, 31, 17, 0) < end), "17:00 UTC is still 31 March"


def test_disposals_outside_the_year_are_excluded_but_still_shape_the_basis():
    """A sale in FY2025-26 consumes the oldest lot, so a sale in
    FY2026-27 must match against the next one. Reading only the filing
    year's transactions gets both the basis and the order wrong."""
    transfers = [
        Transfer("0x" + "1" * 64, utc(2025, 5, 1), "ETH", Decimal("1"),
                 Direction.IN, STRANGER, WALLET_A),
        Transfer("0x" + "2" * 64, utc(2025, 6, 1), "ETH", Decimal("1"),
                 Direction.IN, STRANGER, WALLET_A),
        # sold in the PREVIOUS year — eats the May lot
        Transfer("0x" + "3" * 64, utc(2025, 9, 1), "ETH", Decimal("1"),
                 Direction.OUT, STRANGER, WALLET_A),
        # sold in the year being filed — must match the JUNE lot
        Transfer("0x" + "4" * 64, utc(2026, 9, 1), "ETH", Decimal("1"),
                 Direction.OUT, STRANGER, WALLET_A),
    ]
    pricer = Pricer(
        TablePriceSource({("ETH", "2025-05-01"): "1000", ("ETH", "2025-06-01"): "2000",
                          ("ETH", "2025-09-01"): "2500", ("ETH", "2026-09-01"): "3000"}),
        TableFxSource({"2025-05-01": "80.00", "2025-06-01": "80.00",
                       "2025-09-01": "80.00", "2026-09-01": "80.00"}),
    )

    rep, _ = build(transfers, {WALLET_A}, pricer, "2026-27")

    assert len(rep.matches) == 1, "only the disposal inside the year is filed"
    matched = rep.matches[0]
    assert matched.acquired_at.date().isoformat() == "2025-06-01", (
        "the May lot was already consumed by the earlier sale"
    )
    assert matched.gain_inr == Decimal("80000.00")


# ---------------------------------------------------------------------------
# Provenance — the rule the whole codebase exists to keep
# ---------------------------------------------------------------------------


def test_every_reported_row_names_the_transactions_it_came_from(report):
    rep, _ = report
    for m in rep.matches:
        assert m.acquisition_tx.startswith("0x")
        assert m.disposal_tx.startswith("0x")
        assert len(m.acquisition_tx) > 40
        assert len(m.disposal_tx) > 40


def test_the_csv_carries_the_hashes_through_to_the_filing(report):
    rep, _ = report
    csv_text = render_csv(rep)

    assert "Acquisition tx" in csv_text
    assert "Disposal tx" in csv_text
    for m in rep.matches:
        assert m.disposal_tx in csv_text


def test_an_asset_with_no_price_is_refused_not_zeroed(report):
    """Valuing XYZ at zero would understate the gain. Dropping it
    silently would hide a disposal."""
    rep, _ = report

    assert not rep.is_complete
    xyz = [g for g in rep.gaps if g.asset == "XYZ"]
    assert xyz, "the unpriceable token must be surfaced"
    assert any("no USD price on record" in g.why for g in xyz)
    assert not [m for m in rep.matches if m.asset == "XYZ"], "it never became a number"


def test_selling_more_than_the_history_accounts_for_is_flagged():
    """A wallet that held tokens before the first block we read.

    Assuming a zero cost basis taxes the whole proceeds; ignoring it
    taxes none. Both are wrong, so it is reported as a gap.
    """
    transfers = [
        Transfer("0x" + "d" * 64, utc(2026, 7, 1), "ETH", Decimal("5.0"),
                 Direction.OUT, STRANGER, WALLET_A)
    ]
    pricer = Pricer(
        TablePriceSource({("ETH", "2026-07-01"): "3000"}),
        TableFxSource({"2026-07-01": "84.00"}),
    )
    rep, _ = build(transfers, {WALLET_A}, pricer, "2026-27")

    assert not rep.is_complete
    assert any("opening balance predates" in g.why for g in rep.gaps)
    assert rep.taxable_income_inr == Decimal("0"), "no invented gain"


def test_both_kinds_of_missing_data_are_distinguishable():
    """A missing token price and a missing FX rate are fixed in
    different ways, so the report has to say which one happened."""
    pricer = Pricer(
        TablePriceSource({("ETH", "2026-05-01"): "2000"}),
        TableFxSource({"2026-04-01": "83.00"}),
    )
    no_price = pricer.value_inr("XYZ", Decimal("1"), utc(2026, 4, 1))
    no_fx = pricer.value_inr("ETH", Decimal("1"), utc(2026, 5, 1))

    assert isinstance(no_price, Unpriceable) and "USD price" in no_price.why
    assert isinstance(no_fx, Unpriceable) and "USD/INR" in no_fx.why


# ---------------------------------------------------------------------------
# Reading the chain
# ---------------------------------------------------------------------------


def test_a_reverted_transaction_is_not_a_disposal():
    """A failed transaction sits on the chain forever with a value on
    it. It moved nothing. Counting it reports a sale that never
    happened."""
    rows = [
        {"timeStamp": "1790399627", "hash": "0x" + "a" * 64,
         "from": WALLET_A, "to": STRANGER, "value": "1000000000000000000",
         "isError": "0"},
        {"timeStamp": "1790399628", "hash": "0x" + "b" * 64,
         "from": WALLET_A, "to": STRANGER, "value": "9000000000000000000",
         "isError": "1"},
        {"timeStamp": "1790399629", "hash": "0x" + "c" * 64,
         "from": WALLET_A, "to": STRANGER, "value": "0", "isError": "0"},
    ]
    transfers = etherscan.to_transfers(rows, WALLET_A)

    assert len(transfers) == 1, "the reverted tx and the zero-value call are skipped"
    assert transfers[0].amount == Decimal("1")


def test_wei_converts_to_ether_exactly():
    rows = [{"timeStamp": "1790399627", "hash": "0x" + "a" * 64,
             "from": STRANGER, "to": WALLET_A,
             "value": "55624799152637", "isError": "0"}]
    transfers = etherscan.to_transfers(rows, WALLET_A)

    assert transfers[0].amount == Decimal("0.000055624799152637")
    assert isinstance(transfers[0].amount, Decimal)


# ---------------------------------------------------------------------------
# Properties that make a report defensible months later
# ---------------------------------------------------------------------------


def test_the_same_history_always_produces_the_same_report(case):
    """No model, no randomness, no clock. Run it in March and again in
    December and the figures are identical."""
    pricer = Pricer(case.prices, case.fx)

    first, _ = build(case.transfers, case.owned, pricer, case.financial_year)
    second, _ = build(
        list(reversed(case.transfers)), case.owned, pricer, case.financial_year
    )

    assert render_csv(first) == render_csv(second)
    assert first.taxable_income_inr == second.taxable_income_inr


def test_money_never_touches_a_float(report):
    """A float cannot hold 0.1 exactly, and a return that is off by
    rounding is a return that cannot be defended."""
    rep, _ = report

    for m in rep.matches:
        assert isinstance(m.cost_inr, Decimal)
        assert isinstance(m.consideration_inr, Decimal)
        assert isinstance(m.gain_inr, Decimal)
    assert isinstance(rep.taxable_income_inr, Decimal)


def test_rounding_is_half_up_not_half_even():
    """Python rounds half to EVEN by default. Indian tax practice rounds
    half away from zero. The difference is a paisa at a time."""
    for value, expected in [("1234.565", "1234.57"), ("2.665", "2.67"),
                            ("0.125", "0.13")]:
        assert round_paise(Decimal(value)) == Decimal(expected)
        assert Decimal(value).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        ) != Decimal(expected), "this is exactly where the two conventions differ"


# ---------------------------------------------------------------------------
# Reading a wallet bigger than one page
# ---------------------------------------------------------------------------


def _long_history(total: int, wallet: str) -> list[dict]:
    rows = [
        {"blockNumber": str(1000 + i), "timeStamp": str(1400000000 + i * 600),
         "hash": "0x" + f"{i:064x}", "from": wallet, "to": STRANGER,
         "value": "1000000000000000", "isError": "0"}
        for i in range(total)
    ]
    # Several transactions sharing one block, straddling a page boundary.
    for i in range(9998, 10005):
        rows[i]["blockNumber"] = "10998"
    return rows


def test_a_wallet_bigger_than_one_page_is_read_in_full(monkeypatch):
    """Etherscan caps a response at 10,000 rows and says nothing about
    it — HTTP 200, a full-looking list, everything past the cap absent.

    A tool that takes the first page and stops produces a clean,
    confident, wrong return. This is the test that would have caught
    it: a wallet with 23,456 transactions must yield 23,456 movements.
    """
    rows = _long_history(23456, WALLET_A)

    def fake_call(params):
        start = int(params["startblock"])
        page = [r for r in rows if int(r["blockNumber"]) >= start]
        if params["sort"] == "desc":
            page = list(reversed(page))
        return page[: int(params["offset"])]

    monkeypatch.setattr(etherscan, "_call", fake_call)
    monkeypatch.setattr(etherscan, "PAUSE_SECONDS", 0)

    got = etherscan.fetch_wallet(WALLET_A, key="fake")

    assert len(got) == 23456, "a single page would have returned 10,000"


def test_no_transaction_is_lost_at_a_page_boundary(monkeypatch):
    """A page boundary can fall inside a block that holds several of the
    wallet's transactions. Resuming from the block AFTER the last one
    seen would drop the rest of that block."""
    rows = _long_history(23456, WALLET_A)

    def fake_call(params):
        start = int(params["startblock"])
        page = [r for r in rows if int(r["blockNumber"]) >= start]
        return page[: int(params["offset"])]

    monkeypatch.setattr(etherscan, "_call", fake_call)
    monkeypatch.setattr(etherscan, "PAUSE_SECONDS", 0)

    hashes = {t.tx_hash for t in etherscan.fetch_wallet(WALLET_A, key="fake")}
    straddling = {"0x" + f"{i:064x}" for i in range(9998, 10005)}

    assert straddling <= hashes, "transactions sharing block 10998 were lost"


def test_most_recent_is_one_page_and_says_so(monkeypatch):
    """The sampling path stays a single call. It is explicitly a look,
    not a filing."""
    rows = _long_history(23456, WALLET_A)
    calls = []

    def fake_call(params):
        calls.append(params)
        page = list(reversed(rows))
        return page[: int(params["offset"])]

    monkeypatch.setattr(etherscan, "_call", fake_call)

    got = etherscan.fetch_wallet(WALLET_A, key="fake", most_recent=50)

    assert len(calls) == 1
    assert len(got) == 50
