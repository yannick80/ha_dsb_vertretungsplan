"""Sensors for DSB Vertretungsplan."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_DAYS,
    ATTR_DAYS_AHEAD,
    ATTR_DOCUMENTS,
    ATTR_ENTRIES,
    ATTR_NEWS,
    ATTR_PLAN_DAYS,
    ATTR_PLANS,
)
from .coordinator import DSBConfigEntry, DSBCoordinator
from .entity import DSBEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class DSBSensorDescription(SensorEntityDescription):
    """Describes a DSB sensor."""

    value_fn: Callable[[DSBCoordinator], Any]
    attributes_fn: Callable[[DSBCoordinator], dict[str, Any]] | None = None


def _plan_attributes(coordinator: DSBCoordinator) -> dict[str, Any]:
    """Attributes of the main sensor: the whole school, next N days.

    `entries` is a flat list for simple templates, `days` the same data
    grouped by day including plan days without entries. Each entry carries
    `class_list` (e.g. "08abc" -> ["08a", "08b", "08c"]) so a card can
    filter with `'08b' in e.class_list`.
    """
    first, last = coordinator.window()
    return {
        ATTR_DAYS_AHEAD: coordinator.days_ahead,
        "from": first.isoformat(),
        "to": last.isoformat(),
        ATTR_PLAN_DAYS: [d.isoformat() for d in coordinator.plan_days()],
        ATTR_ENTRIES: [e.as_dict() for e in coordinator.entries()],
        ATTR_DAYS: coordinator.grouped(),
    }


def _plans_attributes(coordinator: DSBCoordinator) -> dict[str, Any]:
    data = coordinator.data
    return {
        ATTR_PLANS: [p.as_dict() for p in data.plans],
        ATTR_PLAN_DAYS: [d.isoformat() for d in data.plan_days],
        "errors": dict(data.plan_errors),
    }


SENSORS: tuple[DSBSensorDescription, ...] = (
    DSBSensorDescription(
        key="plan",
        translation_key="plan",
        icon="mdi:school-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: len(c.entries()),
        attributes_fn=_plan_attributes,
    ),
    DSBSensorDescription(
        key="plan_updated",
        translation_key="plan_updated",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.plan_updated_at,
    ),
    DSBSensorDescription(
        key="plans",
        translation_key="plans",
        icon="mdi:file-table-box-multiple-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: len(c.data.plans),
        attributes_fn=_plans_attributes,
    ),
    DSBSensorDescription(
        key="news",
        translation_key="news",
        icon="mdi:newspaper-variant-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: len(c.data.news),
        attributes_fn=lambda c: {ATTR_NEWS: [n.as_dict() for n in c.data.news]},
    ),
    DSBSensorDescription(
        key="documents",
        translation_key="documents",
        icon="mdi:file-document-multiple-outline",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: len(c.data.documents),
        attributes_fn=lambda c: {ATTR_DOCUMENTS: [d.as_dict() for d in c.data.documents]},
    ),
    DSBSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.last_success_at,
    ),
)


class DSBSensor(DSBEntity, SensorEntity):
    """A DSB sensor."""

    entity_description: DSBSensorDescription

    def __init__(self, coordinator: DSBCoordinator, description: DSBSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the state."""
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional attributes."""
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DSBConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    async_add_entities(DSBSensor(entry.runtime_data, description) for description in SENSORS)
