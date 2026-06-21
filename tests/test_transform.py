"""Unit tests for the raw-account → sensor-shape transform (no network).

This is the integration-specific logic that used to live in the bundled client's
``account()`` method; octopy now returns the raw GraphQL ``account`` object and
``parse_account_summary`` flattens it.
"""

from custom_components.octopus_spain.lib.transform import parse_account_summary

ELECTRICITY_LEDGER = "SPAIN_ELECTRICITY_LEDGER"
SOLAR_LEDGER = "SOLAR_WALLET_LEDGER"


def _account(
    elec_balance=500,
    solar_balance=200,
    net_total=4500,
    start_at="2026-01-01T00:00:00+00:00",
    end_at="2026-01-31T23:59:59+00:00",
    first_issued_at="2026-02-01T10:00:00+00:00",
):
    """A raw Kraken ``account`` object (what account_summary returns)."""
    return {
        "balance": 1000,
        "ledgers": [
            {
                "ledgerType": ELECTRICITY_LEDGER,
                "balance": elec_balance,
                "statements": {
                    "edges": [
                        {
                            "node": {
                                "id": "stmt-1",
                                "firstIssuedAt": first_issued_at,
                                "startAt": start_at,
                                "endAt": end_at,
                                "totalCharges": {"netTotal": net_total},
                            }
                        }
                    ]
                },
            },
            {
                "ledgerType": SOLAR_LEDGER,
                "balance": solar_balance,
                "statements": {"edges": []},
            },
        ],
    }


def test_returns_credit_and_invoice():
    result = parse_account_summary(_account(elec_balance=500, solar_balance=200, net_total=4500))
    assert result["octopus_credit"] == 5.0
    assert result["solar_wallet"] == 2.0
    assert result["last_invoice"]["amount"] == 45.0
    assert str(result["last_invoice"]["start"]) == "2026-01-01"
    assert str(result["last_invoice"]["end"]) == "2026-01-31"
    assert str(result["last_invoice"]["issued"]) == "2026-02-01"


def test_no_statements_returns_none_invoice():
    account = {
        "balance": 0,
        "ledgers": [
            {"ledgerType": ELECTRICITY_LEDGER, "balance": 300, "statements": {"edges": []}}
        ],
    }
    result = parse_account_summary(account)
    assert result["octopus_credit"] == 3.0
    assert result["last_invoice"]["amount"] is None


def test_missing_electricity_ledger_returns_empty():
    account = {
        "balance": 0,
        "ledgers": [
            {"ledgerType": SOLAR_LEDGER, "balance": 100, "statements": {"edges": []}}
        ],
    }
    assert parse_account_summary(account) == {}


def test_empty_account_returns_empty():
    assert parse_account_summary({}) == {}


def test_net_total_zero():
    result = parse_account_summary(_account(net_total=0))
    assert result["last_invoice"]["amount"] == 0.0


def test_net_total_missing():
    account = _account()
    account["ledgers"][0]["statements"]["edges"][0]["node"]["totalCharges"] = {}
    result = parse_account_summary(account)
    assert result["last_invoice"]["amount"] == 0
