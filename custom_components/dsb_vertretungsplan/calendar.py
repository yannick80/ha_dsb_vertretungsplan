"""Calendar entity for DSB Vertretungsplan.

One school-wide calendar; every substitution entry is an all-day event on
its day with the class in the summary, so the calendar card and calendar
triggers can be used as well.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import DSBConfigEntry, DSBCoordinator
from .entity import DSBEntity
from .parser import SubstitutionEntry

PARALLEL_UPDATES = 0


def _summary(entry: SubstitutionEntry) -> str:
    parts: list[str] = []
    if entry.classes:
        parts.append(entry.classes)
    if entry.lesson:
        parts.append(f"{entry.lesson}. Std")
    if entry.type:
        parts.append(entry.type)
    if entry.subject:
        subject = entry.subject
        if old := entry.changes.get("subject"):
            subject = f"{old} → {subject}"
        parts.append(subject)
    return " · ".join(parts) or entry.raw_text


def _description(entry: SubstitutionEntry) -> str:
    lines: list[str] = []
    if entry.substitute:
        lines.append(f"Vertretung: {entry.substitute}")
    if entry.teacher:
        teacher = entry.teacher
        if old := entry.changes.get("teacher"):
            teacher = f"{old} → {teacher}"
        lines.append(f"Lehrkraft: {teacher}")
    if entry.room:
        room = entry.room
        if old := entry.changes.get("room"):
            room = f"{old} → {room}"
        lines.append(f"Raum: {room}")
    if entry.text:
        lines.append(entry.text)
    return "\n".join(lines)


def _to_event(entry: SubstitutionEntry) -> CalendarEvent | None:
    if entry.day is None:
        return None
    digest = hashlib.sha1(entry.raw_text.encode()).hexdigest()[:12]
    return CalendarEvent(
        start=entry.day,
        end=entry.day + timedelta(days=1),
        summary=_summary(entry),
        description=_description(entry) or None,
        location=entry.room or None,
        uid=f"{entry.day.isoformat()}-{digest}",
    )


class DSBCalendar(DSBEntity, CalendarEntity):
    """Calendar with one all-day event per substitution."""

    _attr_icon = "mdi:calendar-text"

    def __init__(self, coordinator: DSBCoordinator) -> None:
        super().__init__(coordinator, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        today = self.coordinator.today
        for entry in self.coordinator.data.entries if self.coordinator.data else []:
            if entry.day is not None and entry.day >= today:
                if (event := _to_event(entry)) is not None:
                    return event
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events between the two dates."""
        start = dt_util.as_local(start_date).date()
        end = dt_util.as_local(end_date).date()
        events: list[CalendarEvent] = []
        for entry in self.coordinator.data.entries if self.coordinator.data else []:
            if entry.day is None or entry.day < start or entry.day > end:
                continue
            if (event := _to_event(entry)) is not None:
                events.append(event)
        return events


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DSBConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendar."""
    async_add_entities([DSBCalendar(entry.runtime_data)])
