"""Unit tests for the Untis HTML parser (no Home Assistant needed).

Run with:  pytest tests/
"""

from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import sys

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "dsb_vertretungsplan"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


parser = _load("parser")

SAMPLE = """
<html><head><meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1"></head><body>
<div class="mon_head"><table><tr><td>Schule</td><td>Stand: 19.10.2026 07:30</td></tr></table></div>
<div class="mon_title">19.10.2026 Montag</div>
<table class="info">
  <tr><th>Nachrichten zum Tag</th></tr>
  <tr><td class="info">Heute kein Mensabetrieb.</td></tr>
</table>
<table class="mon_list">
  <tr><th>Art</th><th>Klasse(n)</th><th>Stunde</th><th>(Fach)</th><th>Raum</th><th>Vertr. von</th><th>(Le.) nach</th><th>Text</th></tr>
  <tr><td>Entfall</td><td>08b</td><td>3</td><td>Ma</td><td>---</td><td>&nbsp;</td><td>Müller</td><td>entfällt</td></tr>
  <tr><td>Vertretung</td><td>08a, 08b</td><td>5</td><td><s>De</s> En</td><td><s>A101</s> B202</td><td>Schmidt</td><td>Meier</td><td></td></tr>
  <tr><td>Raum-Vtr.</td><td>05a</td><td>1 - 2</td><td>Sp</td><td>Halle?R12</td><td></td><td></td><td></td></tr>
</table>
<div class="mon_title">20.10.2026 Dienstag</div>
<table class="mon_list">
  <tr><th>Art</th><th>Klasse(n)</th><th>Stunde</th><th>(Fach)</th><th>Raum</th><th>Vertr. von</th><th>(Le.) nach</th><th>Text</th></tr>
  <tr><td>Verlegung</td><td>08abc</td><td>6</td><td>Ph</td><td>Ph1</td><td></td><td></td><td>auf Mo verlegt</td></tr>
</table>
<div class="mon_title">21.10.2026 Mittwoch</div>
<table class="mon_list">
  <tr><th>Art</th><th>Klasse(n)</th><th>Stunde</th></tr>
</table>
</body></html>
"""


def test_days_and_counts():
    plan = parser.parse_plan_html(SAMPLE)
    assert plan.days == [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)]
    assert len(plan.entries) == 4
    assert [i.text for i in plan.infos] == ["Heute kein Mensabetrieb."]
    assert plan.infos[0].day == date(2026, 10, 19)


def test_column_mapping_and_changes():
    plan = parser.parse_plan_html(SAMPLE)
    first = plan.entries[0]
    assert first.day == date(2026, 10, 19)
    assert first.day_label == "19.10.2026 Montag"
    assert first.type == "Entfall"
    assert first.classes == "08b"
    assert first.lesson == "3"
    assert first.subject == "Ma"
    assert first.room == ""  # "---" is normalised to empty
    assert first.teacher == "Müller"
    assert first.text == "entfällt"

    second = plan.entries[1]
    assert second.subject == "En"
    assert second.changes == {"subject": "De", "room": "A101"}
    assert second.room == "B202"
    assert second.columns["(Fach)"] == "De → En"
    assert second.substitute == "Schmidt"

    third = plan.entries[2]
    assert third.room == "R12"
    assert third.changes["room"] == "Halle"
    assert third.lesson == "1 - 2"


def test_class_matching():
    plan = parser.parse_plan_html(SAMPLE)
    by_class = lambda cls: [e for e in plan.entries if e.matches_class(cls)]  # noqa: E731
    assert len(by_class("08b")) == 3  # 08b, "08a, 08b", "08abc"
    assert len(by_class("08B")) == 3
    assert len(by_class("8b")) == 3
    assert len(by_class("08a")) == 2  # "08a, 08b" and "08abc"
    assert len(by_class("05a")) == 1
    assert len(by_class("")) == 4
    assert len(by_class("10c")) == 0


def test_class_list():
    plan = parser.parse_plan_html(SAMPLE)
    assert plan.entries[0].class_list == ["08b"]
    assert plan.entries[1].class_list == ["08a", "08b"]
    assert plan.entries[3].class_list == ["08a", "08b", "08c"]
    assert parser.SubstitutionEntry(None, "", classes="5a, Q1").class_list == ["05a", "q1"]
    assert parser.SubstitutionEntry(None, "", classes="07").class_list == ["07"]
    assert parser.normalize_class(" 8B ") == "08b"


def test_table_without_css_classes():
    html = """
    <div class="mon_title">3.11.2026 Dienstag</div>
    <table><tr><td>Klasse</td><td>Stunde</td><td>Fach</td><td>Lehrer</td></tr>
    <tr><td>7c</td><td>2</td><td>Bio</td><td>Krause</td></tr></table>
    """
    plan = parser.parse_plan_html(html)
    assert len(plan.entries) == 1
    assert plan.entries[0].classes == "7c"
    assert plan.entries[0].teacher == "Krause"
    assert plan.entries[0].day == date(2026, 11, 3)


def test_day_label_parsing():
    assert parser.parse_day_label("16.4.2026 Donnerstag") == date(2026, 4, 16)
    assert parser.parse_day_label("Donnerstag, 16.04.2026") == date(2026, 4, 16)
    assert parser.parse_day_label("Donnerstag") is None
    assert parser.parse_day_label("31.2.2026") is None


def test_empty_plan():
    plan = parser.parse_plan_html("<html><body><p>Keine Vertretungen</p></body></html>")
    assert plan.entries == []
    assert plan.days == []
