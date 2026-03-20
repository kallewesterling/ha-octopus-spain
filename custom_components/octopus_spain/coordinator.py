from __future__ import annotations

import logging
from datetime import datetime, timedelta, time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import UPDATE_INTERVAL
from .lib.octopus_spain import OctopusSpain

_LOGGER = logging.getLogger(__name__)


class OctopusCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """DataUpdateCoordinator for Octopus Spain accounts."""

    def __init__(self, hass: HomeAssistant, email: str | None, password: str | None, api_key: str | None) -> None:
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name="Octopus Spain",
            update_interval=timedelta(hours=UPDATE_INTERVAL),
        )
        self._api = OctopusSpain(email, password, api_key)
        self._data: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        _LOGGER.info("OctopusCoordinator: starting data update")
        login_ok = await self._api.login()
        if not login_ok:
            _LOGGER.warning("OctopusCoordinator: login failed — check credentials in integration config")
            return self._data
        _LOGGER.info("OctopusCoordinator: login succeeded")
        self._data = {}
        accounts = await self._api.accounts()
        _LOGGER.info("OctopusCoordinator: found %d account(s): %s", len(accounts), accounts)
        if not accounts:
            _LOGGER.warning("OctopusCoordinator: no accounts returned by API")
        for account in accounts:
            try:
                acc = await self._api.account(account)
            except Exception as err:  # pylint: disable=broad-except
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
                start_day = today - timedelta(days=2)
                day_cursor = start_day
                while day_cursor <= today:
                    day_start = datetime.combine(day_cursor, time.min, dt_util.UTC)
                    day_end = day_start + timedelta(days=1)
                    fetched = await self._api.hourly_consumption(
                        account, start=day_start, end=day_end
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
            self._data[account] = acc
        _LOGGER.info("OctopusCoordinator: update complete, data keys=%s", list(self._data.keys()))
        return self._data

    async def async_fetch_hourly_consumption(
        self,
        account: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch hourly consumption for a specific range."""
        return await self._api.hourly_consumption(account, start=start, end=end)
