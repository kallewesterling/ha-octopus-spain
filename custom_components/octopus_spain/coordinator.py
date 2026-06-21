from __future__ import annotations

import logging
from datetime import datetime, timedelta, time
from typing import Any, Awaitable, Callable, TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from octopy.aio import AsyncKrakenGraphQLClient
from octopy.exceptions import GraphQLError, HTTPException, OctopyException

from .const import UPDATE_INTERVAL
from .lib.transform import parse_account_summary

_LOGGER = logging.getLogger(__name__)

# Octopus deployment this integration targets. octopy unifies UK/Spain/etc.
# behind a country code; "ES" selects the Spain (oees-kraken) GraphQL endpoint.
COUNTRY = "ES"

_T = TypeVar("_T")


class OctopusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """DataUpdateCoordinator for Octopus Spain accounts (backed by octopy)."""

    def __init__(
        self,
        hass: HomeAssistant,
        email: str | None,
        password: str | None,
        api_key: str | None,
    ) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="Octopus Spain",
            update_interval=timedelta(hours=UPDATE_INTERVAL),
        )
        self._hass = hass
        self._email = email
        self._password = password
        self._api_key = api_key
        self._client: AsyncKrakenGraphQLClient | None = None
        self._data: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    # Auth — reuse HA's shared aiohttp session; octopy sends the token
    # per-request, so the session is never mutated with our credential.
    # ------------------------------------------------------------------ #
    async def _client_or_login(self, relogin: bool = False) -> AsyncKrakenGraphQLClient:
        if relogin or self._client is None:
            session = async_get_clientsession(self._hass)
            self._client = await AsyncKrakenGraphQLClient.login(
                country=COUNTRY,
                api_key=self._api_key or None,
                email=self._email or None,
                password=self._password or None,
                session=session,
            )
        return self._client

    async def _query(
        self, call: Callable[[AsyncKrakenGraphQLClient], Awaitable[_T]]
    ) -> _T:
        """Run a GraphQL call, re-logging-in once if the token has expired."""
        client = await self._client_or_login()
        try:
            return await call(client)
        except (GraphQLError, HTTPException):
            client = await self._client_or_login(relogin=True)
            return await call(client)

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #
    async def _async_update_data(self) -> dict[str, Any]:
        _LOGGER.info("OctopusCoordinator: starting data update")
        try:
            await self._client_or_login(relogin=True)
        except OctopyException as err:
            # Surface as UpdateFailed so HA marks entities unavailable and retries
            # (and converts to ConfigEntryNotReady on the first setup) instead of
            # silently keeping stale data / creating zero sensors.
            self._client = None
            raise UpdateFailed(f"Login failed — check credentials: {err}") from err

        new_data: dict[str, Any] = {}
        try:
            accounts = await self._query(lambda c: c.account_numbers())
        except OctopyException as err:
            raise UpdateFailed(f"Could not list accounts: {err}") from err
        _LOGGER.info(
            "OctopusCoordinator: found %d account(s): %s", len(accounts), accounts
        )
        if not accounts:
            _LOGGER.warning("OctopusCoordinator: no accounts returned by API")

        for account in accounts:
            try:
                raw = await self._query(lambda c, a=account: c.account_summary(a))
                acc = parse_account_summary(raw)
            except OctopyException as err:
                _LOGGER.exception("Failed to fetch account data for %s: %s", account, err)
                acc = {}
            _LOGGER.info(
                "OctopusCoordinator: account %s data keys=%s",
                account,
                list(acc.keys()) if acc else "(empty)",
            )

            if "hourly_consumption" not in acc:
                hourly_consumption: list[dict[str, Any]] = []
                today = dt_util.utcnow().date()
                day_cursor = today - timedelta(days=2)
                while day_cursor <= today:
                    day_start = datetime.combine(day_cursor, time.min, dt_util.UTC)
                    day_end = day_start + timedelta(days=1)
                    fetched = await self.async_fetch_hourly_consumption(
                        account, day_start, day_end
                    )
                    _LOGGER.info(
                        "OctopusCoordinator: account %s day %s → %d measurements",
                        account,
                        day_cursor,
                        len(fetched) if fetched else 0,
                    )
                    if fetched:
                        hourly_consumption.extend(fetched)
                    day_cursor += timedelta(days=1)
                acc["hourly_consumption"] = hourly_consumption

            new_data[account] = acc

        self._data = new_data
        _LOGGER.info(
            "OctopusCoordinator: update complete, data keys=%s", list(new_data.keys())
        )
        return new_data

    async def async_fetch_hourly_consumption(
        self,
        account: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch hourly electricity consumption for a specific range."""
        try:
            return await self._query(
                lambda c: c.hourly_consumption(account, start, end)
            )
        except OctopyException as err:
            _LOGGER.warning(
                "Failed to fetch hourly consumption for %s: %s", account, err
            )
            return []
