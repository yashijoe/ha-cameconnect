"""Sensor platform for CAME Connect — gate status."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_DEVICE_NAME


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CameConnectSensor(
                coordinator=data["coordinator"],
                device_id=data["device_id"],
                device_name=entry.data[CONF_DEVICE_NAME],
            )
        ],
        update_before_add=True,
    )


class CameConnectSensor(CoordinatorEntity, SensorEntity):
    """Raw gate status sensor — all proxy attributes exposed."""

    _attr_icon = "mdi:gate"

    def __init__(self, coordinator, device_id: int, device_name: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._attr_name = f"{device_name} Status"
        self._attr_unique_id = f"{DOMAIN}_sensor_{device_id}"

    @property
    def device_info(self) -> dict:
        return {
            "identifiers": {(DOMAIN, self._device_id)},
            "name": self._device_name,
            "manufacturer": "CAME",
            "model": "CAME Connect Gate",
        }

    @property
    def native_value(self) -> str:
        return (self.coordinator.data or {}).get("state", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data or {}
        return {
            "position": d.get("position"),
            "moving": d.get("moving"),
            "direction": d.get("direction"),
            "online": d.get("online"),
            "raw_code": d.get("raw_code"),
            "updated_at": d.get("updated_at"),
            "maneuvers": d.get("maneuvers"),
        }
