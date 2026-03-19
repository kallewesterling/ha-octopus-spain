"""Live integration tests — hit the real Octopus Spain API.

These tests are skipped automatically unless credentials are present in .env.test.
Copy .env.test.example to .env.test and fill in your API key (or email + password).

Run only live tests:    pytest -m live -v
Run only unit tests:    pytest -m "not live" -v
"""
import pytest
from datetime import datetime, timedelta, timezone

from custom_components.octopus_spain.lib.octopus_spain import GRAPH_QL_ENDPOINT
from python_graphql_client import GraphqlClient

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Shared session state — login once, reuse across all live tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
async def authed_client(live_client):
    """Log in once and return the authenticated client."""
    result = await live_client.login()
    assert result is True, "Login failed — check credentials in .env.test"
    return live_client


@pytest.fixture(scope="session")
async def accounts(authed_client):
    accs = await authed_client.accounts()
    assert accs, "No accounts returned from API"
    return accs


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLiveLogin:
    async def test_login_succeeds(self, authed_client):
        assert authed_client._token is not None


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

class TestLiveAccounts:
    async def test_returns_at_least_one_account(self, accounts):
        assert isinstance(accounts, list)
        assert len(accounts) > 0
        for acc in accounts:
            assert acc.startswith("A-"), f"Unexpected account format: {acc}"


# ---------------------------------------------------------------------------
# Account data
# ---------------------------------------------------------------------------

class TestLiveAccount:
    async def test_account_data_shape(self, authed_client, accounts):
        data = await authed_client.account(accounts[0])
        assert isinstance(data, dict), f"Expected dict, got {type(data)}"
        assert "octopus_credit" in data, (
            f"Missing octopus_credit — account() returned empty dict, "
            f"check logs for GraphQL errors"
        )
        assert isinstance(data["octopus_credit"], float)

    async def test_last_invoice_shape(self, authed_client, accounts):
        data = await authed_client.account(accounts[0])
        assert "last_invoice" in data
        inv = data["last_invoice"]
        assert "amount" in inv
        assert "start" in inv
        assert "end" in inv
        if inv["start"] is not None:
            assert hasattr(inv["start"], "year"), "start should be a date object"
        if inv["end"] is not None:
            assert hasattr(inv["end"], "year"), "end should be a date object"


# ---------------------------------------------------------------------------
# Hourly consumption
# ---------------------------------------------------------------------------

class TestLiveHourlyConsumption:
    async def test_returns_list(self, authed_client, accounts):
        tz = timezone.utc
        end = datetime.now(tz)
        start = end - timedelta(days=2)
        result = await authed_client.hourly_consumption(accounts[0], start=start, end=end)

        assert isinstance(result, list)
        for m in result:
            assert "value" in m
            assert "startAt" in m
            assert "endAt" in m
            assert "unit" in m


# ---------------------------------------------------------------------------
# Schema introspection — discover real field names on statement types
# ---------------------------------------------------------------------------

class TestLiveSchemaIntrospection:
    async def test_statement_type_fields(self, authed_client):
        """Print available fields on StatementBillingDocumentType.

        Run this test when the account() query breaks to find correct field names:
            pytest -m live -k test_statement_type_fields -v -s
        """
        query = """
            query {
              __type(name: "StatementBillingDocumentType") {
                name
                fields {
                  name
                  type {
                    name
                    kind
                    ofType { name kind }
                  }
                }
              }
            }
        """
        from python_graphql_client import GraphqlClient
        from custom_components.octopus_spain.lib.octopus_spain import GRAPH_QL_ENDPOINT

        client = GraphqlClient(
            endpoint=GRAPH_QL_ENDPOINT,
            headers={"authorization": authed_client._token},
        )
        response = await client.execute_async(query)
        assert "errors" not in response, f"Introspection errors: {response.get('errors')}"

        type_data = response.get("data", {}).get("__type")
        assert type_data is not None, "StatementBillingDocumentType not found in schema"

        fields = {f["name"]: f["type"] for f in (type_data.get("fields") or [])}
        print(f"\nStatementBillingDocumentType fields: {sorted(fields.keys())}")

        # These are the fields we care about — fail with a helpful message if missing
        for field in ("totalCharges",):
            assert field in fields, (
                f"Expected field '{field}' not found. "
                f"Available: {sorted(fields.keys())}"
            )
