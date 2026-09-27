# vdareport/snapshot.py
#
# Building the price tables the engine refuses to work without.
#
#   python3 -m vdareport.snapshot --wallet 0x... --out prices/fy2026-27.json
#
# prices.py explains why the engine reads recorded tables rather than a
# live feed: a return you may have to justify in 2028 has to produce the
# same figures in 2028 as it did the day you filed it, and price feeds
# revise their own history. This is the other half of that decision —
# the thing that goes and gets the numbers, once, and writes them down.
#
# Five properties, all of which exist because this data ends up on a tax
# return:
#
#   It only fetches dates that actually appear in the history.
#
#   It is resumable. An existing output file is loaded first and only
#   the gaps are fetched.
#
#   It records where every figure came from and when it was fetched.
#
#   It records substitutions instead of hiding them. The ECB does not
#   publish rates at weekends, so a Sunday transaction gets Friday's
#   rate — and the file says so, by date.
#
#   It distinguishes "could not ask" from "there is no answer". These
#   are completely different facts and collapsing them writes a
#   permanent hole into a return from a transient failure.
#
# The honest caveat, written here because it has to travel with the
# output: the FX source below is the ECB reference rate, which is NOT
# the RBI reference rate. For an Indian return the RBI figure is the
# defensible one. This gets you a working report; swap the source, or
# hand-correct the table, before anything is filed.

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

from .models import Transfer

# Symbols this can price, and what the price source calls them.
# Deliberately explicit: an unknown symbol is refused rather than
# guessed at, because guessing the wrong coin is worse than no price.
COINBASE_PRODUCTS = {
    "ETH": "ETH-USD",
    "BTC": "BTC-USD",
    "USDT": "USDT-USD",
    "USDC": "USDC-USD",
    "DAI": "DAI-USD",
    "WBTC": "WBTC-USD",
    "MATIC": "MATIC-USD",
    "LINK": "LINK-USD",
}

# Coinbase's exchange API, which needs no key and no account. The
# aggregators all want one now, and an aggregator's blended average is
# a worse answer for a return anyway: this is what one named, regulated
# venue actually quoted that day, which is a sentence you can say to an
# assessing officer.
PRICE_URL = (
    "https://api.exchange.coinbase.com/products/{product}/candles"
    "?start={day}T00:00:00Z&end={day}T23:59:59Z&granularity=86400"
)
FX_URL = "https://api.frankfurter.app/{day}?from=USD&to=INR"

# Some hosts (Frankfurter sits behind Cloudflare) reject urllib's
# default identifier with a 403 before the request ever reaches the API.
HEADERS = {"User-Agent": "vda-report/0.1"}

SOURCES = {
    "usd_prices": (
        "Coinbase Exchange daily candles — the CLOSE of the UTC day, "
        "from api.exchange.coinbase.com/products/{pair}/candles"
    ),
    "usd_inr": (
        "Frankfurter (ECB reference rates). NOT the RBI reference rate — "
        "substitute the RBI figure before filing."
    ),
}


class FetchFailed(RuntimeError):
    """The source could not be reached, or refused.

    This is emphatically NOT the same thing as "there is no price for
    that day", and the difference is the whole reason this class exists.
    A rate limit written into the file as "no USD price on record" turns
    a thirty-second delay into a permanent hole in a tax return, and the
    report then states, in writing, that an asset had no price — which
    is false.
    """


def _get(url: str, attempts: int = 4, backoff: float = 5.0) -> dict | list:
    """One request. Returns the payload, or raises with the reason.

    429s and 5xx mean "ask again later", so they are retried with a
    widening pause before being given up on. Everything else fails
    immediately, because retrying a 404 just wastes the rate limit.
    """
    last = "no attempt made"

    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=30) as response:
                return json.loads(response.read().decode())

        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code} {exc.reason}"
            if exc.code in (401, 403):
                # No amount of waiting fixes a refusal. Retrying one
                # just burns the rate limit.
                raise FetchFailed(f"{last} — the source refused the request") from exc
            if exc.code == 429 or exc.code >= 500:
                if attempt < attempts - 1:
                    time.sleep(backoff * (2 ** attempt))
                    continue
            raise FetchFailed(last) from exc

        except (urllib.error.URLError, OSError) as exc:
            last = f"could not reach it: {exc}"
            if attempt < attempts - 1:
                time.sleep(backoff * (2 ** attempt))
                continue
            raise FetchFailed(last) from exc

        except json.JSONDecodeError as exc:
            raise FetchFailed(f"the reply was not JSON: {exc}") from exc

    raise FetchFailed(last)


def fetch_usd_price(asset: str, day: str) -> Decimal | None:
    """Daily USD price, None if the source genuinely has none.

    Raises FetchFailed if the source could not be asked — a distinction
    the caller has to keep, because one is a fact about the asset and
    the other is a fact about the network.
    """
    product = COINBASE_PRODUCTS.get(asset.upper())
    if product is None:
        return None

    payload = _get(PRICE_URL.format(product=product, day=day))
    if not isinstance(payload, list) or not payload:
        # The venue answered and has no candle for that day. Coinbase
        # listed ETH in 2016, so a 2015 transaction lands here — a real
        # limit, reported as a gap rather than papered over.
        return None

    # [[time, low, high, open, close, volume], ...]. The timestamp is
    # checked rather than trusted: taking whatever candle came back
    # would quietly put a neighbouring day's price under this date.
    #
    # The CLOSE is used rather than the open, the high or the midpoint,
    # because it is the one figure the exchange itself publishes as that
    # day's price, and picking a different one would be a judgement this
    # file is not entitled to make on a taxpayer's behalf.
    wanted = int(datetime.fromisoformat(f"{day}T00:00:00+00:00").timestamp())
    for candle in payload:
        try:
            if int(candle[0]) == wanted:
                return Decimal(str(candle[4]))
        except (IndexError, TypeError, ValueError):
            continue

    return None


def fetch_usd_inr(day: str) -> tuple[Decimal, str] | None:
    """USD/INR, with the date the rate actually applies to.

    The ECB does not publish at weekends or on holidays, so asking for a
    Sunday returns the preceding Friday. The caller records that
    difference rather than pretending it did not happen.
    """
    payload = _get(FX_URL.format(day=day))
    try:
        return Decimal(str(payload["rates"]["INR"])), str(payload["date"])
    except (KeyError, TypeError):
        return None


def needed(transfers: list[Transfer]) -> tuple[set[tuple[str, str]], set[str]]:
    """Exactly the (asset, date) pairs and dates this history requires."""
    pairs = {
        (t.asset.upper(), t.timestamp.date().isoformat()) for t in transfers
    }
    days = {day for _, day in pairs}
    return pairs, days


def build(
    transfers: list[Transfer],
    existing: dict | None = None,
    pause_seconds: float = 0.5,
    price_fetcher=fetch_usd_price,
    fx_fetcher=fetch_usd_inr,
    log=lambda msg: print(msg, file=sys.stderr),
) -> dict:
    """Fetch what is missing and return the complete table."""
    existing = existing or {}
    prices: dict[str, str] = dict(existing.get("usd_prices", {}))
    fx: dict[str, str] = dict(existing.get("usd_inr", {}))
    substitutions: dict[str, str] = dict(existing.get("_fx_substitutions", {}))

    pairs, days = needed(transfers)
    want_prices = sorted({f"{a}|{d}" for a, d in pairs} - set(prices))
    want_fx = sorted(days - set(fx))
    missing: list[str] = []

    log(
        f"  {len(pairs)} asset-days and {len(days)} dates in this history; "
        f"{len(want_prices)} prices and {len(want_fx)} rates still to fetch"
    )
    if want_prices or want_fx:
        total = (len(want_prices) + len(want_fx)) * pause_seconds
        log(f"  at {pause_seconds}s between calls that is about {total/60:.1f} minutes")

    for index, key in enumerate(want_prices):
        asset, day = key.split("|")
        if index:
            time.sleep(pause_seconds)
        try:
            value = price_fetcher(asset, day)
        except FetchFailed as exc:
            missing.append(f"COULD NOT ASK for {asset} on {day} — {exc}")
            log(f"    FAILED   {asset} {day}  ({exc})")
            continue
        if value is None:
            missing.append(f"the source has no USD price for {asset} on {day}")
            log(f"    NO DATA  {asset} {day}")
            continue
        prices[key] = str(value)
        log(f"    {asset} {day}  ${value}")

    for index, day in enumerate(want_fx):
        if index or want_prices:
            time.sleep(pause_seconds)
        try:
            got = fx_fetcher(day)
        except FetchFailed as exc:
            missing.append(f"COULD NOT ASK for USD/INR on {day} — {exc}")
            log(f"    FAILED   USD/INR {day}  ({exc})")
            continue
        if got is None:
            missing.append(f"the source has no USD/INR rate for {day}")
            log(f"    NO DATA  USD/INR {day}")
            continue
        rate, applies_to = got
        fx[day] = str(rate)
        if applies_to != day:
            substitutions[day] = applies_to
            log(f"    USD/INR {day}  {rate}   (published {applies_to})")
        else:
            log(f"    USD/INR {day}  {rate}")

    return {
        "_built_by": "vdareport.snapshot",
        "_fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "_sources": SOURCES,
        "_fx_substitutions": substitutions,
        "_missing": missing,
        "usd_prices": dict(sorted(prices.items())),
        "usd_inr": dict(sorted(fx.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vdareport.snapshot",
        description=(
            "Fetch the prices and FX rates a wallet history needs, once, "
            "and write them down so the report is reproducible."
        ),
    )
    parser.add_argument("--wallet", action="append", default=[], metavar="0x...",
                        help="a wallet the taxpayer owns (repeat for each one)")
    parser.add_argument("--out", type=Path, required=True,
                        help="where to write the tables (reused if it exists)")
    parser.add_argument("--chain-id", type=int, default=1)
    parser.add_argument("--pause", type=float, default=0.5,
                        help="seconds between calls; the free tiers are strict")
    parser.add_argument("--most-recent", type=int, metavar="N",
                        help="sample the last N movements per wallet instead "
                             "of reading the whole history. For looking, not "
                             "for filing.")

    args = parser.parse_args(argv)
    if not args.wallet:
        parser.error("give me at least one --wallet")
        return 2

    from .sources import etherscan

    wallets = sorted({w.strip().lower() for w in args.wallet})
    print(f"  reading {len(wallets)} wallet(s) off the chain...", file=sys.stderr)
    try:
        transfers = etherscan.fetch_wallets(
            wallets, chain_id=args.chain_id, most_recent=args.most_recent
        )
    except etherscan.EtherscanError as exc:
        print(f"\n  could not read the chain: {exc}\n", file=sys.stderr)
        return 2
    print(f"  {len(transfers)} movement(s) found", file=sys.stderr)
    if args.most_recent:
        print("  (a sample — not the whole history)", file=sys.stderr)

    existing = None
    if args.out.exists():
        existing = json.loads(args.out.read_text())
        print(f"  resuming from {args.out}", file=sys.stderr)

    table = build(transfers, existing=existing, pause_seconds=args.pause)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(table, indent=2) + "\n")

    print(f"\n  wrote {args.out}", file=sys.stderr)
    print(f"    {len(table['usd_prices'])} price(s), {len(table['usd_inr'])} rate(s)",
          file=sys.stderr)
    if table["_fx_substitutions"]:
        print(f"    {len(table['_fx_substitutions'])} date(s) took the preceding "
              "business day's rate — see _fx_substitutions", file=sys.stderr)
    if table["_missing"]:
        print(f"\n  {len(table['_missing'])} still missing:", file=sys.stderr)
        for item in table["_missing"]:
            print(f"    {item}", file=sys.stderr)
        print("\n  Run again to retry only these.\n", file=sys.stderr)
        return 1

    print("\n  Complete. Pass it with --prices.\n", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
