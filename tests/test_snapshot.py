# tests/test_snapshot.py
#
# The price builder writes data that ends up on a tax return, so the
# properties that matter are about honesty rather than speed: fetch only
# what is needed, say where every figure came from, never put one day's
# price under another day's date, and never let "we could not ask"
# masquerade as "there is no answer".
#
#   python3 -m pytest -v

from __future__ import annotations

import urllib.error
from decimal import Decimal
from pathlib import Path

import pytest

from vdareport import snapshot
from vdareport.prices import Pricer, TableFxSource, TablePriceSource
from vdareport.report import build as build_report
from vdareport.snapshot import build, fetch_usd_price, needed
from vdareport.sources import fixture

FIXTURE = Path(__file__).parent.parent / "fixtures" / "taxpayer_a.json"

PRICES = {
    ("ETH", "2026-04-10"): "2000.00", ("ETH", "2026-05-15"): "2500.00",
    ("ETH", "2026-06-20"): "2600.00", ("ETH", "2026-08-05"): "3000.00",
    ("USDT", "2026-09-01"): "1.00",   ("USDT", "2026-11-10"): "0.98",
}
FX = {
    "2026-04-10": "83.00", "2026-05-15": "83.50", "2026-06-20": "83.80",
    "2026-08-05": "84.00", "2026-09-01": "84.20", "2026-11-10": "83.00",
    "2026-12-01": "84.50", "2027-01-15": "85.00",
}


class _Response:
    """Stands in for what urlopen hands back."""

    def __init__(self, body: str):
        self._body = body.encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def case():
    return fixture.load(FIXTURE)


@pytest.fixture
def fetchers():
    """Stand-ins for the two live sources, counting their own calls."""
    counts = {"price": 0, "fx": 0}

    def price(asset, day):
        counts["price"] += 1
        found = PRICES.get((asset, day))
        return Decimal(found) if found else None

    def fx(day):
        counts["fx"] += 1
        if day not in FX:
            return None
        # Pretend this date fell on a weekend, as ECB dates regularly do.
        if day == "2026-12-01":
            return Decimal(FX[day]), "2026-11-28"
        return Decimal(FX[day]), day

    return price, fx, counts


def _build(case, fetchers, existing=None):
    price, fx, _ = fetchers
    return build(case.transfers, existing=existing, pause_seconds=0,
                 price_fetcher=price, fx_fetcher=fx, log=lambda m: None)


# ---------------------------------------------------------------------------
# Asking for the right things
# ---------------------------------------------------------------------------


def test_it_only_asks_for_dates_the_history_actually_uses(case):
    """The history spans 280 days but touches 8 of them. Filling the
    range would mean 280 calls and a file nobody can read."""
    pairs, days = needed(case.transfers)

    assert len(days) == 8
    assert len(pairs) == 8
    assert sorted(days)[0] == "2026-04-10"
    assert sorted(days)[-1] == "2027-01-15"


def test_a_second_run_only_fetches_the_gaps(case, fetchers):
    """A run that dies partway through two hundred dates must not start
    again from nothing."""
    _price, _fx, counts = fetchers

    first = _build(case, fetchers)
    first_calls = dict(counts)
    counts["price"] = counts["fx"] = 0

    _build(case, fetchers, existing=first)

    assert first_calls["fx"] == 8
    assert counts["fx"] == 0, "every rate was already on file"
    assert counts["price"] == 2, "only the two it could not get before"


def test_an_unknown_symbol_is_refused_rather_than_guessed():
    """Pricing SOMETOKEN as the wrong asset is worse than not pricing
    it. The symbol map is explicit and anything outside it returns None
    without a network call."""
    assert fetch_usd_price("NOTACOIN", "2026-04-10") is None


# ---------------------------------------------------------------------------
# Reading a candle
# ---------------------------------------------------------------------------


def test_the_close_is_the_price(monkeypatch):
    """[time, low, high, open, close, volume] — the close is the figure
    the exchange publishes as that day's price."""
    def one_candle(request, timeout=None):
        return _Response(
            "[[1624233600, 1864.5, 2259.1, 2242.89, 1885.67, 598655.07]]"
        )

    monkeypatch.setattr(snapshot, "urlopen", one_candle)

    assert fetch_usd_price("ETH", "2021-06-21") == Decimal("1885.67")


def test_a_candle_for_the_wrong_day_is_not_used(monkeypatch):
    """Taking whatever came back would quietly put one day's price
    under another day's date — a wrong figure that looks right and
    traces to nothing."""
    def neighbouring_day(request, timeout=None):
        # 1624147200 is 2021-06-20, not the 21st that was asked for.
        return _Response("[[1624147200, 100.0, 200.0, 150.0, 175.0, 1.0]]")

    monkeypatch.setattr(snapshot, "urlopen", neighbouring_day)

    assert fetch_usd_price("ETH", "2021-06-21") is None


def test_a_date_before_the_venue_listed_the_asset_is_a_gap(monkeypatch):
    """Coinbase listed ETH in 2016, so a 2015 transaction has no price
    there. That is a real limit, reported as a gap rather than zeroed."""
    def nothing(request, timeout=None):
        return _Response("[]")

    monkeypatch.setattr(snapshot, "urlopen", nothing)

    assert fetch_usd_price("ETH", "2015-10-13") is None


# ---------------------------------------------------------------------------
# Being unable to ask is not the same as there being no answer
# ---------------------------------------------------------------------------


def test_a_rate_limit_is_retried_and_then_reported_as_a_failure(monkeypatch):
    """429 means "ask again later". Writing it into the file as "no USD
    price on record" turns a thirty-second delay into a permanent hole
    in a return, and states in writing that an asset had no price."""
    attempts = []

    def always_429(request, timeout=None):
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url, 429, "Too Many Requests", {}, None
        )

    monkeypatch.setattr(snapshot, "urlopen", always_429)
    monkeypatch.setattr(snapshot.time, "sleep", lambda s: None)

    with pytest.raises(snapshot.FetchFailed) as caught:
        fetch_usd_price("ETH", "2026-04-10")

    assert "429" in str(caught.value)
    assert len(attempts) == 4, "retried before giving up"


def test_a_refusal_is_not_retried(monkeypatch):
    """No amount of waiting fixes a 403. Retrying one just burns the
    rate limit."""
    attempts = []

    def forbidden(request, timeout=None):
        attempts.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    monkeypatch.setattr(snapshot, "urlopen", forbidden)
    monkeypatch.setattr(snapshot.time, "sleep", lambda s: None)

    with pytest.raises(snapshot.FetchFailed):
        fetch_usd_price("ETH", "2026-04-10")

    assert len(attempts) == 1


def test_a_failure_to_ask_reads_differently_from_an_absent_price(case, monkeypatch):
    """The two outcomes must be distinguishable in the written record."""
    def unreachable(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 503, "Server Error", {}, None)

    monkeypatch.setattr(snapshot, "urlopen", unreachable)
    monkeypatch.setattr(snapshot.time, "sleep", lambda s: None)

    table = build(case.transfers[:1], pause_seconds=0,
                  fx_fetcher=lambda d: None, log=lambda m: None)

    assert any("COULD NOT ASK" in item for item in table["_missing"])
    assert not any("has no USD price" in item for item in table["_missing"])


def test_the_source_having_no_price_says_exactly_that(case, fetchers):
    table = _build(case, fetchers)

    assert any("the source has no USD price for XYZ" in item
               for item in table["_missing"])
    assert not any("COULD NOT ASK" in item for item in table["_missing"])


def test_every_request_identifies_itself(monkeypatch):
    """Frankfurter sits behind Cloudflare, which 403s urllib's default
    identifier before the request reaches the API at all."""
    seen = {}

    def capture(request, timeout=None):
        seen["ua"] = request.get_header("User-agent")
        return _Response('{"rates": {"INR": "92.89"}, "date": "2026-04-10"}')

    monkeypatch.setattr(snapshot, "urlopen", capture)

    snapshot.fetch_usd_inr("2026-04-10")

    assert seen["ua"] == "vda-report/0.1"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_a_substituted_rate_is_recorded_not_hidden(case, fetchers):
    """The ECB does not publish at weekends, so a Sunday transaction
    takes the preceding Friday's rate. Presenting Friday's number as
    Sunday's, with nothing to say so, is the kind of quiet substitution
    this whole project exists to avoid."""
    table = _build(case, fetchers)

    assert table["_fx_substitutions"] == {"2026-12-01": "2026-11-28"}
    assert table["usd_inr"]["2026-12-01"] == "84.50"


def test_what_could_not_be_fetched_is_named(case, fetchers):
    """XYZ has no entry in the symbol map, so it cannot be priced."""
    table = _build(case, fetchers)

    assert len(table["_missing"]) == 2
    assert all("XYZ" in item for item in table["_missing"])
    assert not [k for k in table["usd_prices"] if k.startswith("XYZ")]


def test_every_figure_says_where_it_came_from(case, fetchers):
    table = _build(case, fetchers)

    assert table["_fetched_at"].startswith("20")
    assert "Coinbase" in table["_sources"]["usd_prices"]
    assert "CLOSE" in table["_sources"]["usd_prices"], (
        "which figure out of the candle was taken has to be on the record"
    )
    assert "RBI" in table["_sources"]["usd_inr"], (
        "the file must carry the warning that this is not the RBI rate"
    )


def test_the_output_drives_the_engine_unchanged(case, fetchers):
    """The whole point: what this writes is what the report reads."""
    table = _build(case, fetchers)

    prices = {}
    for key, value in table["usd_prices"].items():
        asset, day = key.split("|")
        prices[(asset, day)] = value
    pricer = Pricer(TablePriceSource(prices), TableFxSource(table["usd_inr"]))

    report, _ = build_report(case.transfers, case.owned, pricer, case.financial_year)

    assert report.total_gains_inr == Decimal("193625.00")
    assert report.total_losses_inr == Decimal("2860.00")
