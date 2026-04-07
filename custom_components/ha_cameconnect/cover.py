"""Cover platform for CAME Connect — gates and barriers."""
from __future__ import annotations

import logging

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    CONF_DEVICE_NAME,
    CONF_DEVICE_ID,
    CMD_OPEN,
    CMD_CLOSE,
    CMD_STOP,
    CMD_PARTIAL_OPEN,
    CMD_OPEN_CLOSE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CameConnectCover(
                coordinator=data["coordinator"],
                client=data["client"],
                device_id=data["device_id"],
                device_name=entry.data[CONF_DEVICE_NAME],
            )
        ],
        update_before_add=True,
    )


class CameConnectCover(CoordinatorEntity, CoverEntity):
    """CAME Connect gate as a HA Cover entity."""

    _attr_device_class = CoverDeviceClass.GATE
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(self, coordinator, client, device_id: int, device_name: str) -> None:
        super().__init__(coordinator)
        self._client = client
        self._device_id = device_id
        self._device_name = device_name
        self._attr_name = device_name
        self._attr_unique_id = f"{DOMAIN}_cover_{device_id}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "CAME",
            "model": "CAME Connect Gate",
        }

    def _data(self) -> dict:
        return self.coordinator.data or {}

    @property
    def is_open(self) -> bool | None:
        return self._data().get("state") == "open"

    @property
    def is_closed(self) -> bool | None:
        return self._data().get("state") == "closed"

    @property
    def is_opening(self) -> bool:
        return self._data().get("state") == "opening"

    @property
    def is_closing(self) -> bool:
        return self._data().get("state") == "closing"

    @property
    def current_cover_position(self) -> int | None:
        pos = self._data().get("position")
        return int(pos) if pos is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        d = self._data()
        return {
            "moving": d.get("moving"),
            "direction": d.get("direction"),
            "online": d.get("online"),
            "raw_code": d.get("raw_code"),
            "updated_at": d.get("updated_at"),
            "maneuvers": d.get("maneuvers"),
        }

    async def _cmd(self, command_id: int) -> None:
        await self._client.async_send_command(self._device_id, command_id)
        await self.coordinator.async_request_refresh()

    async def async_open_cover(self, **kwargs) -> None:
        await self._cmd(CMD_OPEN)

    async def async_close_cover(self, **kwargs) -> None:
        await self._cmd(CMD_CLOSE)

    async def async_stop_cover(self, **kwargs) -> None:
        await self._cmd(CMD_STOP)

    async def async_open_cover_tilt(self, **kwargs) -> None:
        """Partial open — exposed as tilt for dashboard button compatibility."""
        await self._cmd(CMD_PARTIAL_OPEN)

    async def async_toggle(self, **kwargs) -> None:
        """Open/Close toggle via command 8."""
        await self._cmd(CMD_OPEN_CLOSE)
