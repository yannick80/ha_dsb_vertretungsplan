"""DSB Vertretungsplan integration for Home Assistant.

Loads the substitution plan ("Vertretungsplan") published through DSBmobile
once per account and exposes it as one school-wide sensor plus a calendar.
Filtering by class is done on the dashboard (the bundled Lovelace card or
the attribute `class_list`) or via the `dsb_vertretungsplan.get_entries`
action.
"""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import DSBClient
from .const import (
    ATTR_CLASS,
    CARD_FILENAME,
    CARD_URL,
    ATTR_CONFIG_ENTRY,
    ATTR_DAYS,
    ATTR_DAYS_AHEAD,
    ATTR_ENTRIES,
    DOMAIN,
    MAX_DAYS_AHEAD,
    MIN_DAYS_AHEAD,
    SERVICE_GET_ENTRIES,
)
from .coordinator import DSBConfigEntry, DSBCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

GET_ENTRIES_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CLASS, default=""): cv.string,
        vol.Optional(ATTR_DAYS_AHEAD): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_DAYS_AHEAD, max=MAX_DAYS_AHEAD)
        ),
        vol.Optional(ATTR_CONFIG_ENTRY): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Lovelace card and the integration level action."""
    await _async_register_card(hass)

    @callback
    def _coordinator_for(call: ServiceCall) -> DSBCoordinator:
        entries: list[DSBConfigEntry] = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.state is ConfigEntryState.LOADED
        ]
        if entry_id := call.data.get(ATTR_CONFIG_ENTRY):
            entries = [e for e in entries if e.entry_id == entry_id]
        if not entries:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_config_entry"
            )
        return entries[0].runtime_data

    async def _get_entries(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator_for(call)
        class_filter: str = call.data[ATTR_CLASS]
        days: int | None = call.data.get(ATTR_DAYS_AHEAD)
        entries = coordinator.entries(class_filter, days)
        first, last = coordinator.window(days)
        return {
            "class_name": class_filter,
            "from": first.isoformat(),
            "to": last.isoformat(),
            "count": len(entries),
            ATTR_ENTRIES: [e.as_dict() for e in entries],
            ATTR_DAYS: coordinator.grouped(class_filter, days),
        }

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ENTRIES,
        _get_entries,
        schema=GET_ENTRIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled dashboard card and load it on every dashboard.

    The card lives in www/ next to this file. Serving it from the
    integration means no manual resource entry and no separate HACS
    frontend repository; the version query string busts browser caches
    after an update.
    """
    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card_path), cache_headers=False)]
    )
    version = (await async_get_integration(hass, DOMAIN)).version or "0"
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")


async def async_setup_entry(hass: HomeAssistant, entry: DSBConfigEntry) -> bool:
    """Set up DSB Vertretungsplan from a config entry."""
    client = DSBClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        async_get_clientsession(hass),
    )
    coordinator = DSBCoordinator(hass, entry, client)
    # Raises ConfigEntryNotReady on connection problems (HA retries later)
    # and ConfigEntryAuthFailed on bad credentials (HA starts re-auth).
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DSBConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: DSBConfigEntry) -> None:
    """Reload the entry when options (days ahead, interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
