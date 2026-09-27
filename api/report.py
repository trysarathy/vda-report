# api/report.py
#
# The engine, behind one HTTP endpoint.
#
#   /api/report?sample=1            replay the recorded history
#   /api/report?wallet=0x..&n=10    read a real wallet off the chain
#
# The Etherscan key lives in the server's environment and never reaches
# the browser. That is the only reason this needs a server at all.
#
# Two things are capped on purpose. `n` is limited because a serverless
# function is killed after a short window and a truncated read that
# looked complete is the exact bug this project exists to prevent -- so
# the response says, on its face, that it is a sample. And anything the
# engine refuses to value comes back as a gap rather than a zero, the
# same as it does on the command line.

from __future__ import annotations

import json
import os
import sys
import time
from decimal import Decimal
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vdareport.classify import classify_all, summarise           # noqa: E402
from vdareport.prices import (                                    # noqa: E402
    Pricer, TableFxSource, TablePriceSource, round_paise,
)
from vdareport.report import build                                # noqa: E402
from vdareport.snapshot import build as build_price_tables        # noqa: E402
from vdareport.sources import etherscan, fixture                  # noqa: E402

MAX_SAMPLE = 25
DEFAULT_SAMPLE = 10
FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "fixtures", "taxpayer_a.json",
)


def money(amount: Decimal) -> str:
    return f"{round_paise(amount):,}"


def as_rows(report) -> list[dict]:
    return [
        {
            "quantity": str(m.quantity),
            "asset": m.asset,
            "acquired": m.acquired_at.date().isoformat(),
            "disposed": m.disposed_at.date().isoformat(),
            "cost": money(m.cost_inr),
            "consideration": money(m.consideration_inr),
            "gain": money(abs(m.gain_inr)),
            "is_loss": m.gain_inr < 0,
            "acquisition_tx": m.acquisition_tx,
            "disposal_tx": m.disposal_tx,
        }
        for m in report.matches
    ]


def as_payload(report, events, meta: dict) -> dict:
    gains, losses = report.total_gains_inr, report.total_losses_inr
    netted = gains - losses
    if netted < 0:
        netted = Decimal("0")

    return {
        "ok": True,
        **meta,
        "financial_year": report.financial_year,
        "classified": summarise(events),
        "rows": as_rows(report),
        "totals": {
            "gains": money(gains),
            "losses": money(losses),
            "taxable": money(report.taxable_income_inr),
            "tax": money(report.tax_at_30pct_inr),
            "cess": money(report.cess_at_4pct_inr),
            "payable": money(report.total_payable_inr),
            "payable_if_netted": money(netted * Decimal("0.30") * Decimal("1.04")),
            "taxable_if_netted": money(netted),
            "understated_by": money(
                report.total_payable_inr - netted * Decimal("0.30") * Decimal("1.04")
            ),
        },
        "peak": {
            "inr": money(report.peak_balance_inr) if report.peak_balance_inr else None,
            "on": report.peak_on.isoformat() if report.peak_on else None,
            "caveat": report.peak_caveat,
        },
        "gaps": [
            {"on": g.on.isoformat(), "asset": g.asset, "why": g.why, "tx": g.tx_hash}
            for g in report.gaps
        ],
        "complete": report.is_complete,
    }


def run_sample() -> dict:
    case = fixture.load(FIXTURE)
    report, events = build(
        case.transfers, case.owned, Pricer(case.prices, case.fx),
        case.financial_year,
    )
    return as_payload(report, events, {
        "mode": "sample",
        "source": "a recorded history, shaped to exercise every hard case",
        "wallets": sorted(case.owned),
        "movements": len(case.transfers),
        "sampled": None,
    })


def run_wallets(wallets: list[str], sample: int, financial_year: str) -> dict:
    transfers = etherscan.fetch_wallets(wallets, most_recent=sample)
    if not transfers:
        return {
            "ok": False,
            "error": "No ETH movements found for that address. It may hold "
                     "only tokens -- ERC-20 support is the next piece of work.",
        }

    tables = build_price_tables(
        transfers, pause_seconds=0, workers=8, log=lambda m: None
    )
    prices: dict[tuple[str, str], str] = {}
    for key, value in tables["usd_prices"].items():
        asset, day = key.split("|")
        prices[(asset, day)] = value

    pricer = Pricer(TablePriceSource(prices), TableFxSource(tables["usd_inr"]))
    report, events = build(transfers, set(wallets), pricer, financial_year)

    return as_payload(report, events, {
        "mode": "live",
        "source": "read from Ethereum mainnet; prices from Coinbase, FX from ECB",
        "wallets": wallets,
        "movements": len(transfers),
        "sampled": sample,
        "fx_substitutions": tables["_fx_substitutions"],
        "price_notes": tables["_missing"],
    })


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802  (the runtime requires this name)
        started = time.time()
        query = parse_qs(urlparse(self.path).query)

        try:
            if query.get("sample"):
                payload = run_sample()
            else:
                wallets = [
                    w.strip().lower()
                    for w in query.get("wallet", [])
                    if w.strip()
                ]
                if not wallets:
                    payload = {
                        "ok": False,
                        "error": "Give me a wallet address, or try the sample.",
                    }
                elif any(not (w.startswith("0x") and len(w) == 42) for w in wallets):
                    payload = {
                        "ok": False,
                        "error": "That does not look like an Ethereum address. "
                                 "They start with 0x and are 42 characters long.",
                    }
                else:
                    try:
                        sample = int(query.get("n", [DEFAULT_SAMPLE])[0])
                    except ValueError:
                        sample = DEFAULT_SAMPLE
                    sample = max(1, min(sample, MAX_SAMPLE))
                    year = query.get("fy", ["2026-27"])[0]
                    payload = run_wallets(wallets[:3], sample, year)

        except etherscan.EtherscanError as exc:
            payload = {"ok": False, "error": f"Could not read the chain: {exc}"}
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        payload["elapsed_ms"] = int((time.time() - started) * 1000)

        body = json.dumps(payload).encode()
        self.send_response(200 if payload.get("ok") else 400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
