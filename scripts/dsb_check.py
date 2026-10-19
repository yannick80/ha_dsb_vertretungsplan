#!/usr/bin/env python3
"""Check DSBmobile credentials and show what the integration would parse.

Runs outside Home Assistant. Needs: pip install aiohttp beautifulsoup4

    python3 scripts/dsb_check.py USER PASSWORD [KLASSE]

Prints the published plans, the parsed substitution entries (optionally
filtered by class) and saves the raw HTML of each plan next to the script
as plan_<n>.html so the parser can be adapted if a school uses an unusual
layout.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
from pathlib import Path
import sys

import aiohttp

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "dsb_vertretungsplan"


PACKAGE = "custom_components.dsb_vertretungsplan"


def _load(name: str):
    """Load one module of the integration without importing its __init__.py
    (which needs Home Assistant). The package is faked so that relative
    imports such as ``from .parser import ...`` keep working."""
    if PACKAGE not in sys.modules:
        root = type(sys)("custom_components")
        root.__path__ = [str(COMPONENT.parent)]
        pkg = type(sys)(PACKAGE)
        pkg.__path__ = [str(COMPONENT)]
        sys.modules["custom_components"] = root
        sys.modules[PACKAGE] = pkg
    full_name = f"{PACKAGE}.{name}"
    spec = importlib.util.spec_from_file_location(full_name, COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_load("parser")
api = _load("api")


async def main(username: str, password: str, class_filter: str) -> int:
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")
    async with aiohttp.ClientSession() as session:
        client = api.DSBClient(username, password, session)
        try:
            await client.async_login()
        except api.DSBAuthError as err:
            print(f"LOGIN FEHLGESCHLAGEN (Zugangsdaten): {err}")
            return 1
        except api.DSBConnectionError as err:
            print(f"DSB NICHT ERREICHBAR: {err}")
            return 1
        print("Login OK")

        try:
            data = await client.async_get_data()
        except api.DSBError as err:
            print(f"ABRUF FEHLGESCHLAGEN: {err}")
            return 1

        print(f"\nPläne ({len(data.plans)}):")
        for index, plan in enumerate(data.plans, 1):
            print(
                f"  [{index}] {plan.title!r} vom {plan.date_raw} html={plan.is_html}\n      {plan.url}"
            )
            if plan.is_html:
                try:
                    async with session.get(plan.url) as resp:
                        raw = await resp.read()
                    out = Path(__file__).with_name(f"plan_{index}.html")
                    out.write_bytes(raw)
                    print(f"      gespeichert als {out.name}")
                except aiohttp.ClientError as err:
                    print(f"      Download fehlgeschlagen: {err}")

        if data.plan_errors:
            print(f"\nFehler beim Laden: {data.plan_errors}")

        print(f"\nTage im Plan: {[d.isoformat() for d in data.plan_days]}")
        print(f"Hinweise: {[i.text for i in data.infos]}")

        entries = [e for e in data.entries if e.matches_class(class_filter)]
        print(
            f"\nEinträge{' für ' + class_filter if class_filter else ''}: {len(entries)} von {len(data.entries)}"
        )
        for entry in entries:
            changes = f"  (vorher: {entry.changes})" if entry.changes else ""
            print(
                f"  {entry.day} | {entry.lesson:>5} | {entry.type:<16} | {entry.classes:<10} {entry.class_list} | "
                f"{entry.subject:<6} | {entry.room:<6} | {entry.substitute:<8} | {entry.teacher:<8} | {entry.text}{changes}"
            )

        print(f"\nNachrichten: {len(data.news)}, Dokumente: {len(data.documents)}")
        print(f"Planstand: {data.plan_timestamp}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")))
