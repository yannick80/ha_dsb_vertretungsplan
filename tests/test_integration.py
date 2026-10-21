"""Integration tests: config flow, entities, action, error handling.

Run with:  pytest tests/   (needs pytest-homeassistant-custom-component)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.dsb_vertretungsplan.api import DSBAuthError, DSBConnectionError
from custom_components.dsb_vertretungsplan.const import (
    CONF_DAYS_AHEAD,
    CONF_SCAN_INTERVAL_MINUTES,
    DOMAIN,
    SERVICE_GET_ENTRIES,
)

PLAN = "sensor.dsbmobile_123456_substitution_plan"


def _entry(days_ahead: int = 3) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="DSBmobile 123456",
        unique_id="123456",
        data={CONF_USERNAME: "123456", CONF_PASSWORD: "secret"},
        options={CONF_DAYS_AHEAD: days_ahead, CONF_SCAN_INTERVAL_MINUTES: 30},
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_config_flow_success(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: " 123456 ", CONF_PASSWORD: "secret"}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "DSBmobile 123456"
    assert result["data"] == {CONF_USERNAME: "123456", CONF_PASSWORD: "secret"}
    assert result["options"] == {CONF_DAYS_AHEAD: 3, CONF_SCAN_INTERVAL_MINUTES: 30}
    assert result["result"].unique_id == "123456"


@pytest.mark.parametrize(
    ("error", "expected"),
    [(DSBAuthError("nope"), "invalid_auth"), (DSBConnectionError("down"), "cannot_connect")],
)
async def test_config_flow_errors(
    hass: HomeAssistant, mock_client: AsyncMock, error: Exception, expected: str
) -> None:
    mock_client.async_login.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: "123456", CONF_PASSWORD: "x"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_plan_sensor(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    await _setup(hass, _entry())
    state = hass.states.get(PLAN)
    assert state is not None
    assert state.state == "3"  # all entries of the next 3 days, whole school
    attrs = state.attributes
    assert attrs["days_ahead"] == 3
    assert "entries" not in attrs  # kept small, see websocket command
    assert attrs["classes"] == ["05a", "08a", "08b", "08c"]
    assert len(attrs["days"]) == 2
    assert attrs["days"][0]["count"] == 2
    assert attrs["days"][0]["info"] == ["Kein Mensabetrieb"]
    assert "entries" not in attrs["days"][0]
    assert attrs["days"][1]["count"] == 1

    calendar = hass.states.get("calendar.dsbmobile_123456_substitution_plan")
    assert calendar.state == "on"
    assert calendar.attributes["message"] == "08b · 3. Std · Entfall · Ma"

    assert hass.states.get("sensor.dsbmobile_123456_plans").state == "1"
    expected = dt_util.as_utc(datetime(2026, 10, 19, 7, 30, tzinfo=dt_util.get_default_time_zone()))
    assert hass.states.get("sensor.dsbmobile_123456_plan_updated").state == expected.isoformat()


async def test_days_ahead_option_limits_window(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    await _setup(hass, _entry(days_ahead=1))
    state = hass.states.get(PLAN)
    assert state.state == "2"
    assert len(state.attributes["days"]) == 1


async def test_get_entries_action(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    await _setup(hass, _entry())

    result = await hass.services.async_call(
        DOMAIN, SERVICE_GET_ENTRIES, {"class_name": "8b"}, blocking=True, return_response=True
    )
    assert result["count"] == 2  # "08b" today and "08abc" tomorrow
    assert result["entries"][1]["class_list"] == ["08a", "08b", "08c"]
    assert result["entries"][1]["changes"] == {"room": "Ph2"}
    assert [e["classes"] for e in result["entries"]] == ["08b", "08abc"]
    assert [d["count"] for d in result["days"]] == [1, 1]

    result = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_ENTRIES,
        {"class_name": "05a", "days_ahead": 1},
        blocking=True,
        return_response=True,
    )
    assert result["count"] == 1
    assert len(result["days"]) == 1

    result = await hass.services.async_call(
        DOMAIN, SERVICE_GET_ENTRIES, {}, blocking=True, return_response=True
    )
    assert result["count"] == 3


async def test_get_entries_without_entry(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = _entry()
    await _setup(hass, entry)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_GET_ENTRIES, {}, blocking=True, return_response=True
        )


async def test_update_failure_keeps_data_and_marks_unavailable(
    hass: HomeAssistant, mock_client: AsyncMock, freezer: FrozenDateTimeFactory
) -> None:
    await _setup(hass, _entry())
    assert hass.states.get(PLAN).state == "3"

    # Next poll fails: the sensor must NOT fall back to 0.
    mock_client.async_get_data.side_effect = DSBConnectionError("timeout")
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(PLAN).state == STATE_UNAVAILABLE

    # Recovery.
    mock_client.async_get_data.side_effect = None
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get(PLAN).state == "3"


async def test_auth_failure_starts_reauth(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    mock_client.async_get_data.side_effect = DSBAuthError("bad")
    entry = _entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == "reauth"


async def test_options_reload(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = _entry()
    await _setup(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_DAYS_AHEAD: 1, CONF_SCAN_INTERVAL_MINUTES: 10}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_DAYS_AHEAD: 1, CONF_SCAN_INTERVAL_MINUTES: 10}
    assert hass.states.get(PLAN).state == "2"
    assert entry.runtime_data.update_interval == timedelta(minutes=10)


async def test_unload(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    entry = _entry()
    await _setup(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_card_is_served_and_registered(
    hass: HomeAssistant, mock_client: AsyncMock, hass_client
) -> None:
    """The bundled Lovelace card is served by HA and loaded as extra module."""
    from homeassistant.components.frontend import DATA_EXTRA_JS_URL_ES5, DATA_EXTRA_MODULE_URL

    from custom_components.dsb_vertretungsplan.const import CARD_URL

    await _setup(hass, _entry())
    urls = {u.split("?")[0] for u in hass.data[DATA_EXTRA_MODULE_URL].urls}
    assert CARD_URL in urls
    legacy_urls = {u.split("?")[0] for u in hass.data[DATA_EXTRA_JS_URL_ES5].urls}
    assert CARD_URL in legacy_urls  # older WebViews get the legacy frontend build

    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert "Cache-Control" in response.headers
    body = await response.text()
    assert "customElements.define(CARD_TAG, DsbVertretungsplanCard)" in body
    assert hass.states.get(PLAN).attributes["plan_updated"] is not None


async def test_websocket_entries(
    hass: HomeAssistant, mock_client: AsyncMock, hass_ws_client
) -> None:
    """The card's websocket command returns filtered entries."""
    await _setup(hass, _entry())
    ws = await hass_ws_client(hass)

    await ws.send_json(
        {"id": 1, "type": "dsb_vertretungsplan/entries", "entity_id": PLAN, "class_name": "8b"}
    )
    msg = await ws.receive_json()
    assert msg["success"]
    assert msg["result"]["count"] == 2
    assert [d["count"] for d in msg["result"]["days"]] == [1, 1]
    assert msg["result"]["classes"] == ["05a", "08a", "08b", "08c"]
    assert msg["result"]["plan_updated"] is not None

    await ws.send_json({"id": 2, "type": "dsb_vertretungsplan/entries", "entity_id": "sensor.nope"})
    msg = await ws.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_attributes_stay_small_for_big_school(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """Even hundreds of entries must not push attributes over HA's 16 kB limit."""
    import json
    from datetime import date

    from custom_components.dsb_vertretungsplan.parser import SubstitutionEntry

    data = mock_client.async_get_data.return_value
    today = date.today()
    data.entries = [
        SubstitutionEntry(
            day=today,
            day_label="heute",
            type="Vertretung",
            classes=f"{g:02d}{c}",
            lesson=str(i % 10),
            subject="Mathematik",
            room="A123",
            substitute="Mustermann",
            teacher="Musterfrau",
            text="Aufgaben stehen in Moodle bereit",
            changes={"room": "B456", "subject": "Deutsch"},
            columns={"Art": "Vertretung", "Klasse(n)": f"{g:02d}{c}"},
            raw_text="Vertretung ...",
        )
        for i, (g, c) in enumerate(
            (g, c) for g in range(5, 13) for c in "abcdef" for _ in range(10)
        )
    ]
    await _setup(hass, _entry())
    state = hass.states.get(PLAN)
    assert state.state == "480"
    assert len(json.dumps(dict(state.attributes))) < 4000
