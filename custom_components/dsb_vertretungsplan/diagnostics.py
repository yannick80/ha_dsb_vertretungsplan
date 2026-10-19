"""Diagnostics support for DSB Vertretungsplan."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import DSBConfigEntry

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD, "url"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DSBConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    payload: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": {
            "days_ahead": coordinator.days_ahead,
            "last_update_success": coordinator.last_update_success,
            "last_success_at": (
                coordinator.last_success_at.isoformat() if coordinator.last_success_at else None
            ),
            "update_interval": str(coordinator.update_interval),
        },
    }
    if data is not None:
        payload["data"] = {
            "plans": [p.as_dict() for p in data.plans],
            "plan_days": [d.isoformat() for d in data.plan_days],
            "plan_errors": data.plan_errors,
            "entries": [e.as_dict() for e in data.entries],
            "infos": [i.as_dict() for i in data.infos],
            "news": [n.as_dict() for n in data.news],
            "documents": [d.as_dict() for d in data.documents],
        }
    return async_redact_data(payload, TO_REDACT)
