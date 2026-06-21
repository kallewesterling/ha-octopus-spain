"""Transform Octopus (Kraken) raw account data into the integration's shape.

octopy's ``AsyncKrakenGraphQLClient.account_summary()`` returns the raw GraphQL
``account`` object (balance, ledgers, statements). The sensors expect a flatter,
Spain-specific shape — solar wallet, Octopus credit and the last invoice, all in
euros — so the ledger parsing lives here (it used to live in the bundled client).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

SOLAR_WALLET_LEDGER = "SOLAR_WALLET_LEDGER"
ELECTRICITY_LEDGER = "SPAIN_ELECTRICITY_LEDGER"


def _to_date(value: Optional[str]):
    """Parse an ISO-8601 timestamp to a ``date``; ``None`` on missing/invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


def parse_account_summary(account: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw Kraken ``account`` object to the sensor data shape.

    Returns ``{}`` when there is no electricity ledger (nothing to show). Money
    values are stored in cents by the API and converted to euros here.
    """
    if not account:
        return {}

    ledgers = account.get("ledgers", []) or []
    electricity = next(
        (l for l in ledgers if l.get("ledgerType") == ELECTRICITY_LEDGER), None
    )
    solar = next(
        (l for l in ledgers if l.get("ledgerType") == SOLAR_WALLET_LEDGER),
        {"balance": 0},
    )
    if not electricity:
        return {}

    invoices = (electricity.get("statements", {}) or {}).get("edges", []) or []
    if not invoices:
        return {
            "solar_wallet": None,
            "octopus_credit": float(electricity["balance"]) / 100,
            "last_invoice": {
                "amount": None,
                "issued": None,
                "start": None,
                "end": None,
            },
        }

    invoice = invoices[0]["node"]
    try:
        amount = (invoice.get("totalCharges") or {}).get("netTotal")
    except (AttributeError, TypeError):
        amount = None

    return {
        "solar_wallet": float(solar["balance"]) / 100,
        "octopus_credit": float(electricity["balance"]) / 100,
        "last_invoice": {
            "amount": float(amount) / 100 if amount is not None else 0,
            "issued": _to_date(invoice.get("firstIssuedAt")),
            "start": _to_date(invoice.get("startAt")),
            "end": _to_date(invoice.get("endAt")),
        },
    }
