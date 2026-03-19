import os
import pytest
import aiohttp
from dotenv import load_dotenv

from custom_components.octopus_spain.lib.octopus_spain import OctopusSpain

load_dotenv(".env.test")


@pytest.fixture(autouse=True, scope="session")
def patch_aiohttp_dns():
    """Force aiohttp to use the stdlib threaded resolver.

    aiodns has a signature incompatibility with Python 3.12 that breaks DNS
    resolution in tests. When aiodns is present aiohttp picks it up automatically,
    so we patch TCPConnector.__init__ to always inject ThreadedResolver instead.
    """
    original_init = aiohttp.TCPConnector.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs.setdefault("resolver", aiohttp.ThreadedResolver())
        original_init(self, *args, **kwargs)

    aiohttp.TCPConnector.__init__ = _patched_init
    yield
    aiohttp.TCPConnector.__init__ = original_init


def _live_client() -> OctopusSpain:
    """Return a client configured from environment variables, or None."""
    apikey = os.getenv("OCTOPUS_APIKEY")
    email = os.getenv("OCTOPUS_EMAIL")
    password = os.getenv("OCTOPUS_PASSWORD")
    if not apikey and not (email and password):
        return None
    return OctopusSpain(email=email, password=password, apikey=apikey)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires real API credentials in .env.test")


def pytest_collection_modifyitems(config, items):
    """Skip live tests automatically when credentials are not available."""
    if _live_client() is not None:
        return
    skip = pytest.mark.skip(reason="No credentials found in .env.test — skipping live tests")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def live_client():
    """Session-scoped client — login happens once for the whole test session."""
    client = _live_client()
    if client is None:
        pytest.skip("No credentials found in .env.test")
    return client
