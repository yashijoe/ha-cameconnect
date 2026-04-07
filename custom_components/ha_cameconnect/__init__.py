"""CAME Connect integration for Home Assistant — standalone, no add-on required."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .came_api import CameConnectClient, CameAuthError, CameConnectionError
from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_ID,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.COVER, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up CAME Connect from a config entry."""
    client = CameConnectClient(
        hass=hass,
        client_id=entry.data[CONF_CLIENT_ID],
        client_secret=entry.data[CONF_CLIENT_SECRET],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        entry_id=entry.entry_id,
    )

    device_id: int = entry.data[CONF_DEVICE_ID]
    scan_interval: int = entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL)

    async def async_fetch_status() -> dict:
        try:
            return await client.async_get_status(device_id)
        except CameAuthError as err:
            raise UpdateFailed(f"CAME authentication error: {err}") from err
        except CameConnectionError as err:
            raise UpdateFailed(f"CAME connection error: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_{device_id}",
        update_method=async_fetch_status,
        update_interval=timedelta(seconds=scan_interval),
    )

    # First refresh — raises ConfigEntryNotReady on failure
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "device_id": device_id,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Close dedicated session on unload
    entry.async_on_unload(client.async_close)
    # Reload when options change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
