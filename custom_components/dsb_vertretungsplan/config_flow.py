"""Config flow for DSB Vertretungsplan."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import DSBAuthError, DSBClient, DSBError
from .const import (
    CONF_DAYS_AHEAD,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    MAX_DAYS_AHEAD,
    MAX_SCAN_INTERVAL_MINUTES,
    MIN_DAYS_AHEAD,
    MIN_SCAN_INTERVAL_MINUTES,
)
from .coordinator import DSBConfigEntry

_LOGGER = logging.getLogger(__name__)

_TEXT = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT))
_PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_USERNAME): _TEXT, vol.Required(CONF_PASSWORD): _PASSWORD}
)
STEP_REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): _PASSWORD})


def _number(minimum: int, maximum: int, unit: str) -> vol.All:
    return vol.All(
        NumberSelector(
            NumberSelectorConfig(
                min=minimum,
                max=maximum,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement=unit,
            )
        ),
        vol.Coerce(int),
    )


def _options_schema(defaults: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_DAYS_AHEAD, default=defaults.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD)
            ): _number(MIN_DAYS_AHEAD, MAX_DAYS_AHEAD, "Tage"),
            vol.Required(
                CONF_SCAN_INTERVAL_MINUTES,
                default=defaults.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES),
            ): _number(MIN_SCAN_INTERVAL_MINUTES, MAX_SCAN_INTERVAL_MINUTES, "min"),
        }
    )


class DSBConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the config flow."""

    VERSION = 1
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: DSBConfigEntry) -> DSBOptionsFlow:
        """Return the options flow."""
        return DSBOptionsFlow()

    async def _async_validate(self, username: str, password: str) -> dict[str, str]:
        """Try to log in. Return a dict of errors (empty on success)."""
        client = DSBClient(username, password, async_get_clientsession(self.hass))
        try:
            await client.async_login()
            # One real call to make sure the token actually works.
            await client.async_get_timetables()
        except DSBAuthError:
            return {"base": "invalid_auth"}
        except DSBError as err:
            _LOGGER.debug("Connection problem while validating: %s", err)
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error while validating credentials")
            return {"base": "unknown"}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First step: credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_configured()

            errors = await self._async_validate(username, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_create_entry(
                    title=f"DSBmobile {username}",
                    data={CONF_USERNAME: username, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    options={
                        CONF_DAYS_AHEAD: DEFAULT_DAYS_AHEAD,
                        CONF_SCAN_INTERVAL_MINUTES: DEFAULT_SCAN_INTERVAL_MINUTES,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(STEP_USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start re-authentication after the credentials stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new password."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await self._async_validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD]
            )
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_SCHEMA,
            description_placeholders={CONF_USERNAME: entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow changing user name and password."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(username.lower())
            self._abort_if_unique_id_mismatch()
            errors = await self._async_validate(username, user_input[CONF_PASSWORD])
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): _TEXT,
                vol.Required(CONF_PASSWORD): _PASSWORD,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)


class DSBOptionsFlow(OptionsFlow):
    """Options: preview window and polling interval. Changing them reloads the entry."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show and store the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_DAYS_AHEAD: int(user_input[CONF_DAYS_AHEAD]),
                    CONF_SCAN_INTERVAL_MINUTES: int(user_input[CONF_SCAN_INTERVAL_MINUTES]),
                }
            )
        return self.async_show_form(
            step_id="init", data_schema=_options_schema(self.config_entry.options)
        )
