"""Data update coordinator for DSB Vertretungsplan."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import DSBAuthError, DSBClient, DSBData, DSBError
from .const import (
    ATTR_DATE,
    ATTR_DAY_LABEL,
    ATTR_ENTRIES,
    ATTR_INFO,
    CONF_DAYS_AHEAD,
    CONF_SCAN_INTERVAL_MINUTES,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_SCAN_INTERVAL_MINUTES,
    DOMAIN,
)
from .parser import SubstitutionEntry

_LOGGER = logging.getLogger(__name__)

type DSBConfigEntry = ConfigEntry[DSBCoordinator]


class DSBCoordinator(DataUpdateCoordinator[DSBData]):
    """Fetch the substitution plan on a schedule.

    The plan is loaded once per DSB account; filtering by class happens on
    the dashboard or through the get_entries action. On failure the previous
    data is kept and the entities become unavailable. An empty plan
    (holidays) is valid data, not a failure.
    """

    config_entry: DSBConfigEntry

    def __init__(self, hass: HomeAssistant, entry: DSBConfigEntry, client: DSBClient) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL_MINUTES, DEFAULT_SCAN_INTERVAL_MINUTES)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self.days_ahead: int = int(entry.options.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
        self.last_success_at: datetime | None = None

    async def _async_update_data(self) -> DSBData:
        try:
            data = await self.client.async_get_data()
        except DSBAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except DSBError as err:
            raise UpdateFailed(str(err)) from err
        self.last_success_at = dt_util.utcnow()
        return data

    # ---------------------------------------------------------------- helpers

    @property
    def today(self) -> date:
        """Return today's date in the Home Assistant time zone."""
        return dt_util.now().date()

    @property
    def plan_updated_at(self) -> datetime | None:
        """Return the upload time of the newest plan as an aware datetime."""
        if self.data is None or (stamp := self.data.plan_timestamp) is None:
            return None
        return stamp.replace(tzinfo=dt_util.get_default_time_zone())

    def window(self, days: int | None = None) -> tuple[date, date]:
        """Return (first, last) day of the preview window."""
        first = self.today
        last = first + timedelta(days=(days or self.days_ahead) - 1)
        return first, last

    def entries(self, class_filter: str = "", days: int | None = None) -> list[SubstitutionEntry]:
        """Return entries inside the preview window, optionally for one class."""
        if self.data is None:
            return []
        first, last = self.window(days)
        return [
            e
            for e in self.data.entries
            if e.day is not None
            and first <= e.day <= last
            and (not class_filter or e.matches_class(class_filter))
        ]

    def plan_days(self, days: int | None = None) -> list[date]:
        """Return the days inside the window for which a plan page exists."""
        if self.data is None:
            return []
        first, last = self.window(days)
        return [d for d in self.data.plan_days if first <= d <= last]

    def grouped(self, class_filter: str = "", days: int | None = None) -> list[dict[str, Any]]:
        """Return the window grouped by day, including plan days without entries.

        Every plan day inside the window appears, so a dashboard can show
        "keine Vertretungen" for a day explicitly instead of hiding it.
        """
        infos = self.data.infos if self.data else []
        labels: dict[date | None, str] = {}
        if self.data is not None:
            for entry in self.data.entries:
                labels.setdefault(entry.day, entry.day_label)
            for info in infos:
                labels.setdefault(info.day, info.day_label)

        groups: dict[date, list[SubstitutionEntry]] = {d: [] for d in self.plan_days(days)}
        for entry in self.entries(class_filter, days):
            groups.setdefault(entry.day, []).append(entry)  # type: ignore[arg-type]

        return [
            {
                ATTR_DATE: day.isoformat(),
                ATTR_DAY_LABEL: labels.get(day) or day.strftime("%d.%m.%Y"),
                "count": len(items),
                ATTR_INFO: [i.text for i in infos if i.day == day],
                ATTR_ENTRIES: [e.as_dict() for e in items],
            }
            for day, items in sorted(groups.items())
        ]
