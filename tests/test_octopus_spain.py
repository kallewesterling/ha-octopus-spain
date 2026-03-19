"""Unit tests for OctopusSpain — all API calls are mocked."""
import pytest
from unittest.mock import AsyncMock, patch

from custom_components.octopus_spain.lib.octopus_spain import OctopusSpain

MOCK_TOKEN = "fake-token"
ACCOUNT_NUMBER = "A-TESTACCOUNT"

ELECTRICITY_LEDGER = "SPAIN_ELECTRICITY_LEDGER"
SOLAR_LEDGER = "SOLAR_WALLET_LEDGER"


@pytest.fixture
def client():
    c = OctopusSpain(email=None, password=None, apikey="fake-key")
    c._token = MOCK_TOKEN
    return c


def _patch_execute(return_value):
    return patch(
        "custom_components.octopus_spain.lib.octopus_spain.GraphqlClient.execute_async",
        new=AsyncMock(return_value=return_value),
    )


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

class TestLogin:
    async def test_login_success(self):
        c = OctopusSpain(email=None, password=None, apikey="my-key")
        with _patch_execute({"data": {"obtainKrakenToken": {"token": "tok123"}}}):
            result = await c.login()
        assert result is True
        assert c._token == "tok123"

    async def test_login_failure_returns_false(self):
        c = OctopusSpain(email=None, password=None, apikey="bad-key")
        with _patch_execute({"errors": [{"message": "Invalid credentials"}]}):
            result = await c.login()
        assert result is False
        assert c._token is None


# ---------------------------------------------------------------------------
# account()
# ---------------------------------------------------------------------------

def _account_response(
    elec_balance=500,
    solar_balance=200,
    net_total=4500,
    start_at="2026-01-01T00:00:00+00:00",
    end_at="2026-01-31T23:59:59+00:00",
    first_issued_at="2026-02-01T10:00:00+00:00",
):
    return {
        "data": {
            "account": {
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
        }
    }


class TestAccount:
    async def test_returns_credit_and_invoice(self, client):
        with _patch_execute(_account_response(elec_balance=500, solar_balance=200, net_total=4500)):
            result = await client.account(ACCOUNT_NUMBER)

        assert result["octopus_credit"] == 5.0
        assert result["solar_wallet"] == 2.0
        assert result["last_invoice"]["amount"] == 45.0
        assert str(result["last_invoice"]["start"]) == "2026-01-01"
        assert str(result["last_invoice"]["end"]) == "2026-01-31"
        assert str(result["last_invoice"]["issued"]) == "2026-02-01"

    async def test_no_statements_returns_none_invoice(self, client):
        response = {
            "data": {
                "account": {
                    "balance": 0,
                    "ledgers": [
                        {
                            "ledgerType": ELECTRICITY_LEDGER,
                            "balance": 300,
                            "statements": {"edges": []},
                        }
                    ],
                }
            }
        }
        with _patch_execute(response):
            result = await client.account(ACCOUNT_NUMBER)

        assert result["octopus_credit"] == 3.0
        assert result["last_invoice"]["amount"] is None

    async def test_missing_electricity_ledger_returns_empty(self, client):
        response = {
            "data": {
                "account": {
                    "balance": 0,
                    "ledgers": [
                        {"ledgerType": SOLAR_LEDGER, "balance": 100, "statements": {"edges": []}}
                    ],
                }
            }
        }
        with _patch_execute(response):
            result = await client.account(ACCOUNT_NUMBER)

        assert result == {}

    async def test_graphql_error_returns_empty(self, client):
        with _patch_execute({"errors": [{"message": "Some API error"}]}):
            result = await client.account(ACCOUNT_NUMBER)

        assert result == {}

    async def test_net_total_zero(self, client):
        with _patch_execute(_account_response(net_total=0)):
            result = await client.account(ACCOUNT_NUMBER)

        assert result["last_invoice"]["amount"] == 0.0

    async def test_net_total_missing(self, client):
        response = _account_response()
        response["data"]["account"]["ledgers"][0]["statements"]["edges"][0]["node"][
            "totalCharges"
        ] = {}
        with _patch_execute(response):
            result = await client.account(ACCOUNT_NUMBER)

        assert result["last_invoice"]["amount"] == 0


# ---------------------------------------------------------------------------
# hourly_consumption()
# ---------------------------------------------------------------------------

def _measurement_edge(value="0.5", start="2026-01-01T10:00:00+00:00", end="2026-01-01T11:00:00+00:00"):
    return {
        "node": {
            "value": value,
            "unit": "kWh",
            "startAt": start,
            "endAt": end,
        }
    }


def _consumption_response(edges):
    return {
        "data": {
            "account": {
                "properties": [
                    {"measurements": {"edges": edges}}
                ]
            }
        }
    }


class TestHourlyConsumption:
    async def test_returns_measurements(self, client):
        edges = [
            _measurement_edge("0.5", "2026-01-01T10:00:00+00:00", "2026-01-01T11:00:00+00:00"),
            _measurement_edge("0.7", "2026-01-01T11:00:00+00:00", "2026-01-01T12:00:00+00:00"),
        ]
        with _patch_execute(_consumption_response(edges)):
            result = await client.hourly_consumption(ACCOUNT_NUMBER)

        assert len(result) == 2
        assert result[0]["value"] == "0.5"
        assert result[1]["value"] == "0.7"

    async def test_empty_edges_returns_empty_list(self, client):
        with _patch_execute(_consumption_response([])):
            result = await client.hourly_consumption(ACCOUNT_NUMBER)

        assert result == []

    async def test_graphql_error_returns_empty_list(self, client):
        with _patch_execute({"errors": [{"message": "bad query"}]}):
            result = await client.hourly_consumption(ACCOUNT_NUMBER)

        assert result == []

    async def test_no_properties_returns_empty_list(self, client):
        with _patch_execute({"data": {"account": {"properties": []}}}):
            result = await client.hourly_consumption(ACCOUNT_NUMBER)

        assert result == []
