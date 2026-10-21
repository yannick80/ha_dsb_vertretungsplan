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
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace import LOVELACE_DATA
from homeassistant.components.lovelace.const import CONF_RESOURCE_TYPE_WS
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_ID,
    CONF_PASSWORD,
    CONF_TYPE,
    CONF_URL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
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
        return _entries_response(coordinator, call.data[ATTR_CLASS], call.data.get(ATTR_DAYS_AHEAD))

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_ENTRIES,
        _get_entries,
        schema=GET_ENTRIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    websocket_api.async_register_command(hass, ws_get_entries)
    return True


def _entries_response(
    coordinator: DSBCoordinator, class_filter: str, days: int | None
) -> dict[str, Any]:
    """Build the payload shared by the action and the websocket command."""
    entries = coordinator.entries(class_filter, days)
    first, last = coordinator.window(days)
    return {
        "class_name": class_filter,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "count": len(entries),
        "classes": coordinator.classes_in_window(days),
        "plan_updated": (
            coordinator.plan_updated_at.isoformat() if coordinator.plan_updated_at else None
        ),
        ATTR_ENTRIES: [e.as_dict() for e in entries],
        ATTR_DAYS: coordinator.grouped(class_filter, days),
    }


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/entries",
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional(ATTR_CLASS, default=""): cv.string,
        vol.Optional(ATTR_DAYS_AHEAD): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_DAYS_AHEAD, max=MAX_DAYS_AHEAD)
        ),
    }
)
@callback
def ws_get_entries(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Return the entries behind a plan sensor; used by the bundled card."""
    registry_entry = er.async_get(hass).async_get(msg["entity_id"])
    entry = (
        hass.config_entries.async_get_entry(registry_entry.config_entry_id)
        if registry_entry and registry_entry.config_entry_id
        else None
    )
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        connection.send_error(msg["id"], "not_found", "Entity is not a loaded DSB plan sensor")
        return
    connection.send_result(
        msg["id"],
        _entries_response(entry.runtime_data, msg[ATTR_CLASS], msg.get(ATTR_DAYS_AHEAD)),
    )


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve the bundled dashboard card and make every dashboard load it.

    The card lives in www/ next to this file. It is registered as a
    Lovelace *resource* (the same mechanism HACS uses): the frontend loads
    resources deliberately before it builds the cards, so slow devices do
    not hit "Custom element doesn't exist". Only when resources are managed
    in YAML (no storage collection) the card falls back to a plain extra
    script tag, which the frontend loads without waiting for it.
    """
    card_path = Path(__file__).parent / "www" / CARD_FILENAME
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card_path), cache_headers=True)]
    )
    version = (await async_get_integration(hass, DOMAIN)).version or "0"
    url = f"{CARD_URL}?v={version}"

    if await _async_register_lovelace_resource(hass, url):
        return
    _LOGGER.debug("Lovelace resources not in storage mode, using extra script tag")
    add_extra_js_url(hass, url)
    add_extra_js_url(hass, url, es5=True)


async def _async_register_lovelace_resource(hass: HomeAssistant, url: str) -> bool:
    """Create or update the Lovelace resource entry for the card.

    Returns False when resources are not managed in storage mode.
    """
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != "storage":
        return False
    resources = lovelace.resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    ours = [
        item
        for item in resources.async_items()
        if str(item.get(CONF_URL, "")).split("?", 1)[0] == CARD_URL
    ]
    if not ours:
        _LOGGER.info("Registering dashboard card resource %s", url)
        await resources.async_create_item({CONF_RESOURCE_TYPE_WS: "module", CONF_URL: url})
        return True
    first, *duplicates = ours
    # Stored items carry the type under "type"; create/update expect "res_type".
    if first.get(CONF_URL) != url or first.get(CONF_TYPE) != "module":
        _LOGGER.info("Updating dashboard card resource to %s", url)
        await resources.async_update_item(
            first[CONF_ID], {CONF_RESOURCE_TYPE_WS: "module", CONF_URL: url}
        )
    for item in duplicates:
        await resources.async_delete_item(item[CONF_ID])
    return True


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
