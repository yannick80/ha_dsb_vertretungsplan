# Changelog

## 1.1.1

- Karte wird auch im Legacy-Frontend geladen (ältere Android-WebViews, z. B. Shelly Wall Display); vorher erschien dort die rote Fehlerkarte „Custom element doesn't exist“.
- Karten-JavaScript ohne Optional Chaining / Nullish Coalescing, damit ältere Browser es parsen können.

## 1.1.0

- Karte: aufeinanderfolgende Stunden mit identischer Vertretung werden zu einer Zeile zusammengefasst (z. B. `5-6. Std`). Abschaltbar über die Option `merge_lessons`.

## 1.0.1

- Sensor-Attribute enthalten nur noch eine Zusammenfassung je Tag; der volle Plan einer Schule überschritt die 16-KB-Grenze von Home Assistant, Attribute wurden nicht mehr gespeichert.
- Die Dashboard-Karte holt die Einträge über den neuen WebSocket-Befehl `dsb_vertretungsplan/entries`.
- Neues Attribut `classes`: alle Klassen mit Einträgen im Vorschaufenster. Die Karte zeigt diese Liste an, wenn der Klassenfilter nichts findet.
- Markdown-Vorlage entfernt (ohne Attribute keine Datenbasis).

## 1.0.0

- Erste Veröffentlichung.
