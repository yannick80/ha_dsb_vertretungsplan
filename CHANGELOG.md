# Changelog

## 1.2.1

- Card file is served with cache headers (updates still arrive through the version query string). Slow devices such as wall displays and phone apps no longer re-download it on every reload, which could trip the frontend's wait for the custom element and show a "configuration error" card.
- Card: render errors are caught and shown inside the card instead of propagating into Home Assistant's error card; day data from the server is normalised before use.

## 1.2.0

- Card: new option `hide_today_after` (time). From that time on, today is hidden, e.g. once school has started; the card re-checks every minute without a reload.

## 1.1.1

- Card is now loaded by the legacy frontend build as well (older Android WebViews such as the Shelly Wall Display); previously the red "Custom element doesn't exist" card appeared there.
- Card JavaScript no longer uses optional chaining / nullish coalescing so older browsers can parse it.

## 1.1.0

- Card: consecutive lessons with identical substitution are merged into one row (e.g. `5-6. Std`). Can be disabled with the option `merge_lessons`.

## 1.0.1

- Sensor attributes now hold a per-day summary only; the full plan of a school exceeded Home Assistant's 16 kB attribute limit and attributes were no longer recorded.
- The dashboard card fetches entries through the new websocket command `dsb_vertretungsplan/entries`.
- New attribute `classes`: all classes with entries in the preview window. The card shows this list when the class filter matches nothing.
- Markdown template removed (no data source without attributes).

## 1.0.0

- Initial release.
