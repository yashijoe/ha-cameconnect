"""Config flow for CAME Connect — Step 1: credentials, Step 2: device."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .came_api import CameConnectClient, CameAuthError, CameConnectionError
from .const import (
    DOMAIN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class CameConnectConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Two-step config flow:
      Step 1 (credentials): client_id, client_secret, username, password → OAuth test
      Step 2 (device):      device_id, device_name → final entry
    """

    VERSION = 1

    def __init__(self) -> None:
        self._credentials: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Step 1 — CAME Connect credentials
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect and validate CAME Connect OAuth credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            client = CameConnectClient(
                hass=self.hass,
                client_id=user_input[CONF_CLIENT_ID].strip(),
                client_secret=user_input[CONF_CLIENT_SECRET].strip(),
                username=user_input[CONF_USERNAME].strip(),
                password=user_input[CONF_PASSWORD],
                entry_id="setup_test",
            )
            try:
                await client.async_test_credentials()
                self._credentials = {
                    CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                    CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
                    CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                return await self.async_step_device()
            except CameAuthError:
                errors["base"] = "invalid_auth"
            except CameConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during CAME credential test")
                errors["base"] = "unknown"
            finally:
                # Clean up temp client: close session and delete the spurious
                # ha_cameconnect_token_setup_test file from hass.storage.
                await client.async_close()
                await client.async_delete_storage()

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): str,
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2 — Device configuration
    # ------------------------------------------------------------------

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect device ID and friendly name."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_id = int(user_input[CONF_DEVICE_ID])
            device_name = user_input[CONF_DEVICE_NAME].strip()

            await self.async_set_unique_id(f"{DOMAIN}_{device_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=device_name,
                data={
                    **self._credentials,
                    CONF_DEVICE_ID: device_id,
                    CONF_DEVICE_NAME: device_name,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_NAME, default="Gate"): str,
                vol.Required(CONF_DEVICE_ID): vol.Coerce(int),
            }
        )

        return self.async_show_form(
            step_id="device",
            data_schema=schema,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Options flow (scan interval)
    # ------------------------------------------------------------------

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CameConnectOptionsFlow(config_entry)


class CameConnectOptionsFlow(config_entries.OptionsFlow):
    """Allow adjusting the polling interval after setup."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Required(
                    "scan_interval",
                    default=self.config_entry.options.get(
                        "scan_interval", DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=2, max=60)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
