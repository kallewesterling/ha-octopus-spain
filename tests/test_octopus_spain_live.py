"""Live integration tests — hit the real Octopus Spain API via octopy.

Skipped automatically unless credentials are present in .env.test. Copy
.env.test.example to .env.test and fill in your API key (or email + password).

Run only live tests:    pytest -m live -v
Run only unit tests:    pytest -m "not live" -v
"""

from datetime import datetime, timedelta, timezone

import pytest

# Needs the octopy async client; skip cleanly if the [async] extra is absent.
pytest.importorskip("octopy.aio")
from octopy.aio import AsyncKrakenGraphQLClient  # noqa: E402

from custom_components.octopus_spain.lib.transform import (  # noqa: E402
    parse_account_summary,
)

pytestmark = pytest.mark.live

COUNTRY = "ES"


@pytest.fixture(scope="session")
async def authed_client(live_config):
    """Log in once and return the authenticated async client."""
    client = await AsyncKrakenGraphQLClient.login(country=COUNTRY, **live_config)
    assert client.token, "Login failed — check credentials in .env.test"
    yield client
    await client.close()


@pytest.fixture(scope="session")
async def accounts(authed_client):
    accs = await authed_client.account_numbers()
    assert accs, "No accounts returned from API"
    return accs


class TestLiveLogin:
    async def test_login_succeeds(self, authed_client):
        assert authed_client.token is not None


class TestLiveAccounts:
    async def test_returns_at_least_one_account(self, accounts):
        assert isinstance(accounts, list)
        assert len(accounts) > 0
        for acc in accounts:
            assert acc.startswith("A-"), f"Unexpected account format: {acc}"


class TestLiveAccount:
    async def test_account_data_shape(self, authed_client, accounts):
        data = parse_account_summary(await authed_client.account_summary(accounts[0]))
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"
        assert "octopus_credit" in data, (
            "Missing octopus_credit — transform returned empty, check the ledgers"
        )
        assert isinstance(data["octopus_credit"], float)

    async def test_last_invoice_shape(self, authed_client, accounts):
        data = parse_account_summary(await authed_client.account_summary(accounts[0]))
        assert "last_invoice" in data
        inv = data["last_invoice"]
        assert "amount" in inv
        assert "start" in inv
        assert "end" in inv
        if inv["start"] is not None:
            assert hasattr(inv["start"], "year"), "start should be a date object"
        if inv["end"] is not None:
            assert hasattr(inv["end"], "year"), "end should be a date object"


class TestLiveHourlyConsumption:
    async def test_returns_list(self, authed_client, accounts):
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=2)
        result = await authed_client.hourly_consumption(accounts[0], start, end)

        assert isinstance(result, list)
        for m in result:
            assert {"value", "startAt", "endAt", "unit"} <= set(m)
