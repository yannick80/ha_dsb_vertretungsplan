"""Shared fixtures for the Home Assistant tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.dsb_vertretungsplan.api import DSBData, DSBItem
from custom_components.dsb_vertretungsplan.parser import DayInfo, SubstitutionEntry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of custom integrations in every test."""
    yield


def make_data(today: date) -> DSBData:
    """Build sample data relative to a given 'today'."""
    tomorrow = date.fromordinal(today.toordinal() + 1)
    data = DSBData()
    data.plans = [
        DSBItem(
            id="1",
            title="subst_001.htm",
            date=datetime(2026, 10, 19, 7, 30),
            date_raw="19.10.2026 07:30",
            url="https://light.dsbcontrol.de/x/subst_001.htm",
            is_html=True,
        )
    ]
    data.plan_days = [today, tomorrow]
    data.infos = [DayInfo(day=today, day_label="heute", text="Kein Mensabetrieb")]
    data.entries = [
        SubstitutionEntry(
            day=today,
            day_label="heute",
            type="Entfall",
            classes="08b",
            lesson="3",
            subject="Ma",
            teacher="Müller",
            raw_text="Entfall 08b 3 Ma Müller",
        ),
        SubstitutionEntry(
            day=today,
            day_label="heute",
            type="Vertretung",
            classes="05a",
            lesson="1",
            subject="De",
            raw_text="Vertretung 05a 1 De",
        ),
        SubstitutionEntry(
            day=tomorrow,
            day_label="morgen",
            type="Raum-Vtr.",
            classes="08abc",
            lesson="6",
            subject="Ph",
            room="Ph1",
            changes={"room": "Ph2"},
            raw_text="Raum-Vtr. 08abc 6 Ph Ph1",
        ),
    ]
    return data


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Patch the DSB client used by the integration and the config flow."""
    with (
        patch("custom_components.dsb_vertretungsplan.DSBClient", autospec=True) as init_cls,
        patch(
            "custom_components.dsb_vertretungsplan.config_flow.DSBClient", autospec=True
        ) as flow_cls,
    ):
        client = init_cls.return_value
        flow_cls.return_value = client
        client.async_login.return_value = "token"
        client.async_get_timetables.return_value = []
        client.async_get_data.return_value = make_data(date.today())
        yield client
