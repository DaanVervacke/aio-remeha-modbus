"""Decode tests anchored to a register dump captured from live hardware.

``tests/fixtures/gtw26_store.json`` holds a raw dump taken from a real
Generation 4 iSystem controller (Modbus unit id 10) via ``async_read_all_raw``.
It anchors the decode layer to register patterns a hand-written fixture does
not produce: the base identity registers answer ``0xFFFF`` instead of
rejecting the read, and unmapped fault codes surface as raw ints.
"""

from datetime import time

import pytest
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw26 import GTW26, ControllerGeneration
from aio_remeha_modbus.gtw26.const import RegisterLayout, Weekday
from aio_remeha_modbus.gtw26.schedule import ComfortPeriod


@pytest.mark.parametrize("remeha_modbus_unit", ["gtw26_store.json"], indirect=True)
@pytest.mark.asyncio
async def test_capture_detects_gen4_isystem(remeha_modbus_unit: MockModbusUnit) -> None:
    """The dump must detect as a Generation 4 controller on the iSystem layout."""
    detection = await GTW26.async_detect(remeha_modbus_unit)

    assert detection.success
    assert detection.device is not None
    assert detection.failure_reason is None
    assert detection.raw_type_code == 24
    assert detection.generation is ControllerGeneration.GENERATION_4
    assert detection.isystem_detected
    assert detection.device.layout is RegisterLayout.ISYSTEM


@pytest.mark.parametrize("remeha_modbus_unit", ["gtw26_store.json"], indirect=True)
@pytest.mark.asyncio
async def test_capture_update_refreshes_every_bundle(
    remeha_modbus_unit: MockModbusUnit,
) -> None:
    """One poll over the real dump must refresh every bundle without failures."""
    detection = await GTW26.async_detect(remeha_modbus_unit)
    report = await detection.device.async_update()

    assert report.failed == {}
    assert report.complete
    assert report.updated == {
        "climate_zone_a",
        "climate_zone_b",
        "climate_zone_c",
        "config",
        "diagnostics",
        "hot_water",
        "identity",
        "outputs",
        "schedules.auxiliary",
        "schedules.circuit_a_p4",
        "schedules.circuit_b_p4",
        "schedules.circuit_c_p4",
        "schedules.hot_water",
        "sensors",
        "settings",
    }


@pytest.mark.parametrize("remeha_modbus_unit", ["gtw26_store.json"], indirect=True)
@pytest.mark.asyncio
async def test_capture_decodes_hand_verified_values(
    remeha_modbus_unit: MockModbusUnit,
) -> None:
    """Spot values pinned against the raw words, not against the decoder's output."""
    detection = await GTW26.async_detect(remeha_modbus_unit)
    device = detection.device
    await device.async_update()

    # Register 601 holds 0x00D2 = 210 tenths.
    assert device.sensors.outdoor_temperature == 21.0
    # Register 602 holds 0x0129 = 297 tenths.
    assert device.sensors.boiler_temperature == 29.7
    # Register 603 holds 0x0263 = 611 tenths.
    assert device.hot_water.temperature == 61.1
    # Register 672 holds 600 tenths.
    assert device.hot_water.comfort_target == 60.0
    # Register 616 holds 240 tenths.
    assert device.climate_zones["B"].room_temperature == 24.0
    # Register 678 holds 750 tenths.
    assert device.settings.boiler_maximum_temperature == 75.0
    # Register 600 holds the raw software version.
    assert device.identity.software_version == 15
    # Register 457 holds 24, the type code naming the D4 controller.
    assert device.identity.controller_type == "D4"
    # Register 465 holds 46, a fault code no fault table maps.
    assert device.sensors.fault == 46


@pytest.mark.parametrize("remeha_modbus_unit", ["gtw26_store.json"], indirect=True)
@pytest.mark.asyncio
async def test_capture_presence_follows_real_sensor_patterns(
    remeha_modbus_unit: MockModbusUnit,
) -> None:
    """Presence on the real dump: zone A has no room sensor but a calculated reading."""
    detection = await GTW26.async_detect(remeha_modbus_unit)
    device = detection.device
    await device.async_update()

    # Register 614 (zone A room temperature) is 0xFFFF on this controller, so
    # zone A counts as present through its calculated temperature alone.
    assert device.climate_zones["A"].room_temperature is None
    assert device.zone_a_present
    assert device.zone_b_present
    assert device.zone_c_present
    assert device.hot_water_present


@pytest.mark.parametrize("remeha_modbus_unit", ["gtw26_store.json"], indirect=True)
@pytest.mark.asyncio
async def test_capture_decodes_real_hot_water_schedule(
    remeha_modbus_unit: MockModbusUnit,
) -> None:
    """The real weekly hot-water program must decode into comfort periods."""
    detection = await GTW26.async_detect(remeha_modbus_unit)
    device = detection.device
    await device.async_update()

    assert device.schedule.get_day("hot_water", Weekday.MONDAY) == [
        ComfortPeriod(start=time(3, 0), end=time(9, 0)),
        ComfortPeriod(start=time(11, 30), end=time(12, 30)),
        ComfortPeriod(start=time(16, 0), end=time(22, 30)),
    ]
