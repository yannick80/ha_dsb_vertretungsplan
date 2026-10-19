# Changelog

## 1.0.1

- Sensor-Attribute enthalten nur noch eine Zusammenfassung je Tag; der volle Plan einer Schule überschritt die 16-KB-Grenze von Home Assistant, Attribute wurden nicht mehr gespeichert.
- Die Dashboard-Karte holt die Einträge über den neuen WebSocket-Befehl `dsb_vertretungsplan/entries`.
- Neues Attribut `classes`: alle Klassen mit Einträgen im Vorschaufenster. Die Karte zeigt diese Liste an, wenn der Klassenfilter nichts findet.
- Markdown-Vorlage entfernt (ohne Attribute keine Datenbasis).

## 1.0.0

- Erste Veröffentlichung.
