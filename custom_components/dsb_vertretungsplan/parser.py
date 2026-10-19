"""Parser for Untis substitution plan HTML files as published via DSBmobile.

This module is intentionally free of Home Assistant imports so it can be
unit tested and used from a plain Python script.

Untis "Vertretungsplan" HTML exports look roughly like this::

    <div class="mon_title">19.10.2026 Montag</div>
    <table class="info"> ... Nachrichten zum Tag ... </table>
    <table class="mon_list">
      <tr><th>Art</th><th>Klasse(n)</th><th>Stunde</th>...</tr>
      <tr><td>Entfall</td><td>08b</td><td>3</td>...</tr>
    </table>
    <div class="mon_title">20.10.2026 Dienstag</div>
    ...

A single file can contain several days. Columns differ between schools, so
the parser maps columns by their header text instead of their position.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_WS_RE = re.compile(r"\s+")
_CLASS_RE = re.compile(r"^(\d{1,2})([a-zäöü]*)$")

# Header text (lower-cased, whitespace collapsed) -> canonical field name.
# Order matters: the first matching pattern wins.
_HEADER_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("art", "typ", "type"), "type"),
    (("klasse", "klassen", "klasse(n)", "class", "classes"), "classes"),
    (("stunde", "std", "std.", "stunde(n)", "lesson", "period"), "lesson"),
    (("(fach)", "fach", "subject"), "subject"),
    (("raum", "räume", "(raum)", "room"), "room"),
    (("vertreter", "vertr.", "vertretung", "vertr. von", "substitute"), "substitute"),
    (("(lehrer)", "lehrer", "(le.)", "(le.) nach", "le.", "teacher"), "teacher"),
    (("text", "info", "bemerkung", "bemerkungen", "hinweis", "note"), "text"),
)


@dataclass
class SubstitutionEntry:
    """One row of a substitution plan."""

    day: date | None
    day_label: str
    type: str = ""
    classes: str = ""
    lesson: str = ""
    subject: str = ""
    room: str = ""
    substitute: str = ""
    teacher: str = ""
    text: str = ""
    # Old (struck-through / "before") values, keyed by canonical field name.
    changes: dict[str, str] = field(default_factory=dict)
    # Every column of the row keyed by its header text, with the new value.
    columns: dict[str, str] = field(default_factory=dict)
    # Plain text of the row, used for free text filtering.
    raw_text: str = ""

    @property
    def class_tokens(self) -> list[str]:
        """Return the individual class names of the row, lower-cased."""
        return [t for t in re.split(r"[,;/\s]+", self.classes.lower()) if t]

    @property
    def class_list(self) -> list[str]:
        """Return every single class this row concerns, normalised.

        Untis merges parallel classes: "08abc" means 08a, 08b and 08c. Grades
        are zero-padded to two digits so "8b" and "08b" both become "08b".
        Tokens that do not look like a class ("Q1", "Lehrer") are kept as is.
        """
        result: list[str] = []
        for token in self.class_tokens:
            match = _CLASS_RE.match(token)
            if match is None:
                if token not in result:
                    result.append(token)
                continue
            grade, letters = f"{int(match.group(1)):02d}", match.group(2)
            for name in [f"{grade}{ch}" for ch in letters] or [grade]:
                if name not in result:
                    result.append(name)
        return result

    def matches_class(self, class_filter: str) -> bool:
        """Return True if this entry concerns the given class (case-insensitive).

        "08b", "8b" and "08abc" all match a filter of "08b"; a bare grade
        such as "08" matches every class of that grade.
        """
        needle = normalize_class(class_filter)
        if not needle:
            return True
        class_list = self.class_list
        if needle in class_list:
            return True
        if _CLASS_RE.match(needle) and needle.isdigit():
            return any(name.startswith(needle) for name in class_list)
        if needle in self.classes.lower():
            return True
        if not self.classes:
            # Some schools leave the class column empty and put it in the text.
            return needle in self.raw_text.lower()
        return False

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation for state attributes."""
        return {
            "date": self.day.isoformat() if self.day else None,
            "day_label": self.day_label,
            "type": self.type,
            "classes": self.classes,
            "class_list": self.class_list,
            "lesson": self.lesson,
            "subject": self.subject,
            "room": self.room,
            "substitute": self.substitute,
            "teacher": self.teacher,
            "text": self.text,
            "changes": dict(self.changes),
            "columns": dict(self.columns),
        }


@dataclass
class DayInfo:
    """Free text information published for a day ("Nachrichten zum Tag")."""

    day: date | None
    day_label: str
    text: str

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation."""
        return {
            "date": self.day.isoformat() if self.day else None,
            "day_label": self.day_label,
            "text": self.text,
        }


@dataclass
class ParsedPlan:
    """Result of parsing one HTML plan file."""

    entries: list[SubstitutionEntry] = field(default_factory=list)
    infos: list[DayInfo] = field(default_factory=list)
    # Days for which a page exists in the plan, even if it has no entries.
    days: list[date] = field(default_factory=list)


def normalize_class(value: str) -> str:
    """Normalise a class name for comparisons: lower-case, grade zero-padded."""
    value = _clean(value).lower()
    match = _CLASS_RE.match(value)
    if match is None:
        return value
    return f"{int(match.group(1)):02d}{match.group(2)}"


def _clean(text: str) -> str:
    return _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()


def parse_day_label(label: str) -> date | None:
    """Extract a date from a day header such as '16.4.2026 Donnerstag'."""
    match = _DATE_RE.search(label)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _canonical_field(header: str) -> str | None:
    key = _clean(header).lower()
    if not key:
        return None
    for names, canonical in _HEADER_MAP:
        if key in names:
            return canonical
    # Fuzzy fallback on the most common stems.
    for names, canonical in _HEADER_MAP:
        if any(key.startswith(n.rstrip(".")) for n in names if len(n) > 2):
            return canonical
    return None


def _split_cell(cell: Tag) -> tuple[str, str]:
    """Return (new_value, old_value) of a table cell.

    Untis marks replaced values either with ``<s>old</s> new`` or, in plain
    text exports, as ``old?new``.
    """
    old_parts: list[str] = []
    new_parts: list[str] = []
    for child in cell.children:
        if isinstance(child, Tag):
            if child.name in ("s", "strike", "del"):
                text = _clean(child.get_text(" "))
                if text:
                    old_parts.append(text)
                continue
            text = _clean(child.get_text(" "))
        else:
            text = _clean(str(child))
        if text:
            new_parts.append(text)

    new_value = _clean(" ".join(new_parts))
    old_value = _clean(" ".join(old_parts))

    if not old_value and "?" in new_value:
        # Untis plain text notation: "Ma?De" means Ma was replaced by De.
        before, _, after = new_value.partition("?")
        before, after = before.strip(), after.strip()
        if before and after:
            old_value, new_value = before, after

    if new_value in ("---", "-", "+"):
        new_value = ""
    return new_value, old_value


def _parse_header(row: Tag) -> list[str]:
    cells = row.find_all(["th", "td"])
    return [_clean(c.get_text(" ")) for c in cells]


def parse_plan_html(html: str) -> ParsedPlan:
    """Parse an Untis substitution plan HTML document."""
    soup = BeautifulSoup(html, "html.parser")
    result = ParsedPlan()

    current_day: date | None = None
    current_label = ""
    seen_days: set[date] = set()

    for element in soup.find_all(["div", "table"]):
        if not isinstance(element, Tag):
            continue
        classes = element.get("class") or []

        if element.name == "div" and "mon_title" in classes:
            current_label = _clean(element.get_text(" "))
            current_day = parse_day_label(current_label)
            if current_day and current_day not in seen_days:
                seen_days.add(current_day)
                result.days.append(current_day)
            continue

        if element.name != "table":
            continue

        if "info" in classes:
            _parse_info_table(element, current_day, current_label, result)
        elif "mon_list" in classes:
            _parse_list_table(element, current_day, current_label, result)

    # Some exports have no CSS classes at all: fall back to "any table with
    # a header row that looks like a substitution table".
    if not result.entries and not soup.find("table", class_="mon_list"):
        for table in soup.find_all("table"):
            header_row = table.find("tr")
            if header_row is None:
                continue
            headers = _parse_header(header_row)
            if any(_canonical_field(h) == "classes" for h in headers):
                _parse_list_table(table, current_day, current_label, result)

    return result


def _parse_info_table(table: Tag, day: date | None, label: str, result: ParsedPlan) -> None:
    for row in table.find_all("tr"):
        if row.find("th"):
            continue
        text = _clean(row.get_text(" "))
        if not text or text.lower().startswith("nachrichten zum tag"):
            continue
        result.infos.append(DayInfo(day=day, day_label=label, text=text))


def _parse_list_table(table: Tag, day: date | None, label: str, result: ParsedPlan) -> None:
    headers: list[str] = []
    for row in table.find_all("tr"):
        if row.find("th"):
            headers = _parse_header(row)
            continue
        cells = row.find_all("td")
        if not cells:
            continue
        if not headers:
            # Header rows without <th>: treat the first row as header if it
            # contains a known column name.
            candidate = _parse_header(row)
            if any(_canonical_field(h) == "classes" for h in candidate):
                headers = candidate
                continue

        raw_text = _clean(row.get_text(" "))
        if not raw_text:
            continue

        # Day separator rows inside the table (rare Untis layout).
        if len(cells) == 1 and parse_day_label(raw_text):
            label = raw_text
            day = parse_day_label(raw_text)
            if day and day not in result.days:
                result.days.append(day)
            continue

        entry = SubstitutionEntry(day=day, day_label=label, raw_text=raw_text)
        for index, cell in enumerate(cells):
            header = headers[index] if index < len(headers) else f"col{index + 1}"
            new_value, old_value = _split_cell(cell)
            entry.columns[header] = f"{old_value} → {new_value}" if old_value else new_value
            canonical = _canonical_field(header)
            if canonical is None:
                continue
            setattr(entry, canonical, new_value)
            if old_value:
                entry.changes[canonical] = old_value

        result.entries.append(entry)
