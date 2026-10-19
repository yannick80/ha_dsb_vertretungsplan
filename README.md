# DSB Vertretungsplan für Home Assistant

Custom Integration, die den über **DSBmobile** veröffentlichten Untis-Vertretungsplan in Home Assistant bereitstellt. Der Plan wird **einmal pro Schul-Zugang** geladen; die Klasse wird erst im Dashboard oder in Automationen gefiltert. So reichen ein Zugang und ein Sensor für mehrere Kinder an derselben Schule.

Die Integration ist eine Neuentwicklung mit dem Ziel, sich so zu verhalten, wie Home Assistant es erwartet:

- **Mobile-API statt Web-Scraping.** Dieselbe tokenbasierte API wie die DSBmobile-App (`mobileapi.dsbcontrol.de`). Kein ASP.NET-Login-Formular, kein Flackern zwischen echten Daten und „keine Vertretungen“.
- **DataUpdateCoordinator mit echter Fehlerbehandlung.** Verbindungsprobleme werden als `UpdateFailed` gemeldet, die letzten gültigen Daten bleiben erhalten und die Entitäten werden `unavailable` statt still auf 0 zu springen. Ein leerer Plan (Ferien) ist ein gültiger Zustand.
- **Re-Auth, Reconfigure, Optionen ohne Neustart, Diagnostics-Export, Übersetzungen (de/en).**
- **Robuster Untis-Parser.** Spalten werden anhand der Kopfzeile erkannt, `<s>alt</s> neu` und `alt?neu` als Änderung, Sammelklassen wie `08abc` werden zu `08a, 08b, 08c` aufgelöst, mehrere Tage pro Datei werden unterstützt.

## Installation

**HACS:** drei Punkte → Benutzerdefinierte Repositories → URL dieses Repositories, Kategorie *Integration* → installieren → Home Assistant neu starten.

**Manuell:** Ordner `custom_components/dsb_vertretungsplan` nach `<config>/custom_components/` kopieren und neu starten.

Die alte Integration `dsbmobile` kann parallel installiert bleiben; die Domains kollidieren nicht.

## Einrichtung

**Einstellungen → Geräte & Dienste → Integration hinzufügen → „DSB Vertretungsplan“**, Benutzer-ID und Passwort wie in der DSBmobile-App eingeben. Unter **Konfigurieren** lassen sich später einstellen:

| Option            | Standard | Bedeutung                                                   |
|-------------------|----------|-------------------------------------------------------------|
| Vorschau in Tagen | 3        | Der Sensor enthält Einträge von heute bis in N Tagen        |
| Abfrageintervall  | 30 min   | Wie oft DSB abgefragt wird (Minimum 5 min)                  |

## Entitäten

Alle Entitäten hängen am Gerät „DSBmobile *Benutzer-ID*“.

| Entität                                   | Zustand                                  | Attribute                                                     |
|-------------------------------------------|------------------------------------------|---------------------------------------------------------------|
| `sensor.dsbmobile_<id>_vertretungsplan`   | Anzahl Einträge (alle Klassen, N Tage)   | `entries` (flach), `days` (nach Tag gruppiert), `plan_days`, `from`, `to`, `days_ahead` |
| `calendar.dsbmobile_<id>_vertretungsplan` | nächster Eintrag als Ganztagstermin      | für Kalender-Karte und Kalender-Trigger                       |
| `sensor.dsbmobile_<id>_planstand`         | Zeitpunkt der letzten Plan-Veröffentlichung |                                                            |
| `sensor.dsbmobile_<id>_nachrichten`       | Anzahl News                              | `news`                                                        |
| `sensor.dsbmobile_<id>_dokumente`         | Anzahl Dokumente                         | `documents`                                                   |
| `sensor.dsbmobile_<id>_plane`             | Anzahl Pläne (Diagnose)                  | `plans`, `plan_days`, `errors`                                |
| `sensor.dsbmobile_<id>_letzte_abfrage`    | letzte erfolgreiche Abfrage (Diagnose)   |                                                               |

`days` enthält **jeden Plantag im Fenster**, auch solche ohne Einträge (`count: 0`). So kann eine Kachel „Keine Vertretungen“ für einen Tag ausdrücklich anzeigen, statt ihn zu verschweigen. Jeder Eintrag sieht so aus:

```yaml
date: "2026-10-19"
day_label: "19.10.2026 Montag"
type: "Vertretung"              # Art
classes: "08abc"                # Spalte Klasse(n), wie von Untis geliefert
class_list: ["08a", "08b", "08c"]   # aufgelöst und normalisiert, für Filter
lesson: "5"
subject: "En"
room: "B202"
substitute: "Schmidt"           # Vertr. von / Vertreter
teacher: "Meier"                # (Le.) nach / Lehrer
text: ""
changes: { subject: "De", room: "A101" }   # alte Werte bei Änderungen
columns: { "Art": "Vertretung", "(Fach)": "De → En", ... }   # alle Spalten roh
```

## Dashboard-Kachel pro Kind

Die Kachel filtert selbst nach Klasse. Für das zweite Kind die Karte kopieren und nur die erste Zeile ändern; beide lesen denselben Sensor, es gibt keinen zweiten Abruf. Die Vorlage liegt auch in [`examples/kachel.yaml`](examples/kachel.yaml).

```yaml
type: markdown
content: >-
  {% set klasse = '08b' %}
  {% set sensor = 'sensor.dsbmobile_123456_vertretungsplan' %}
  {% set icons = {'Entfall': '🔴', 'Vertretung': '🔵', 'Verlegung': '🟡',
                  'Raum-Vtr.': '🟠', 'Betreuung': '🟢', 'Statt-Vertretung': '🟣'} %}
  ## 🎒 Klasse {{ klasse }}
  {% if is_state(sensor, 'unavailable') %}
  ⚠️ DSBmobile ist gerade nicht erreichbar.
  {% else %}
  {% set days = state_attr(sensor, 'days') or [] %}
  {% if days | count == 0 %}
  _Kein Plan veröffentlicht._
  {% endif %}
  {% for day in days %}
  {% set eintraege = day.entries | selectattr('class_list', 'contains', klasse | lower) | list %}
  **{{ day.day_label }}**
  {% if eintraege | count == 0 %}
  ✅ Keine Vertretungen
  {% endif %}
  {% for e in eintraege %}
  {{ icons.get(e.type, '⚫') }} **{{ e.lesson }}. Std** {{ e.subject }}
  {%- if e.changes.subject %} (statt {{ e.changes.subject }}){% endif %}
  {%- if e.room %} · {{ e.room }}{% endif %}
  {%- if e.substitute %} · {{ e.substitute }}{% endif %}
  {%- if e.text %} · _{{ e.text }}_{% endif %}
  {% endfor %}
  {% for hinweis in day.info %}
  ℹ️ {{ hinweis }}
  {% endfor %}

  {% endfor %}
  {% endif %}
```

Die Klasse in `klasse` wird klein geschrieben und zweistellig verglichen (`08b`); `8b` als Eingabe funktioniert über `'0' ~ klasse` oder einfach die Schreibweise `08b`.

## Aktion `dsb_vertretungsplan.get_entries`

Liefert die Einträge der kommenden Tage, optional für eine Klasse, als Rückgabewert. Praktisch für Benachrichtigungen pro Kind:

```yaml
triggers:
  - trigger: time
    at: "06:45:00"
actions:
  - action: dsb_vertretungsplan.get_entries
    data:
      class_name: "08b"
      days_ahead: 1
    response_variable: plan
  - if:
      - condition: template
        value_template: "{{ plan.count > 0 }}"
    then:
      - action: notify.mobile_app_handy
        data:
          title: "Vertretungsplan 08b heute"
          message: >-
            {% for e in plan.entries -%}
            {{ e.lesson }}. Std {{ e.type }} {{ e.subject }}{{ ' (' ~ e.text ~ ')' if e.text }}
            {% endfor %}
```

Rückgabe: `class_name`, `from`, `to`, `count`, `entries` (flach) und `days` (gruppiert, wie beim Sensor). Mit `days_ahead` lässt sich das Fenster pro Aufruf überschreiben; `config_entry` ist nur bei mehreren DSB-Zugängen nötig.

## Fehlersuche

Ohne Home Assistant prüfen, ob Login und Parser mit der eigenen Schule funktionieren (läuft ab Python 3.9):

```bash
python3 -m pip install aiohttp beautifulsoup4
python3 scripts/dsb_check.py BENUTZER PASSWORT 08b
```

Das Skript zeigt alle Pläne, die erkannten Einträge samt `class_list` und speichert das rohe HTML als `scripts/plan_<n>.html`. Falls die Spalten der Schule nicht erkannt werden, hilft diese Datei beim Anpassen von `parser.py` (Tabelle `_HEADER_MAP`).

Debug-Protokoll in Home Assistant:

```yaml
logger:
  logs:
    custom_components.dsb_vertretungsplan: debug
```

**Geräte & Dienste → DSB Vertretungsplan → Diagnose herunterladen** liefert alle abgerufenen Daten (Zugangsdaten und URLs geschwärzt).

## Tests

```bash
pip install -r requirements-test.txt
pytest tests/
```
