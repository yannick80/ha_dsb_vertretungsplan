"""Base entity and device description for DSB Vertretungsplan."""

from __future__ import annotations

from homeassistant.const import CONF_USERNAME
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL_ACCOUNT
from .coordinator import DSBCoordinator


def account_device_info(coordinator: DSBCoordinator) -> DeviceInfo:
    """Device representing the DSBmobile account (one per school login)."""
    entry = coordinator.config_entry
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"DSBmobile {entry.data[CONF_USERNAME]}",
        manufacturer=MANUFACTURER,
        model=MODEL_ACCOUNT,
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://www.dsbmobile.de/",
    )


class DSBEntity(CoordinatorEntity[DSBCoordinator]):
    """Entity attached to the account device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DSBCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = account_device_info(coordinator)
