import asyncio

import pytest
from modbus_connection import (
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
    ServerDeviceBusyError,
)
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw26 import HeatingMode, HotWaterMode
from aio_remeha_modbus.gtw26.const import RegisterLayout
from aio_remeha_modbus.helpers.modbus import RetryingModbusUnit
from tests.gtw26.conftest import Gtw26Factory, LayoutGtw26Factory


def _seed(unit: MockModbusUnit) -> None:
    unit.holding.update({7: 205, 75: 650, 18: 210, 59: 550, 62: 500})


def _seed_isystem(unit: MockModbusUnit) -> None:
    unit.holding.update({601: 205, 602: 650, 614: 210, 126: 0x0180})


@pytest.mark.asyncio
async def test_partial_failure_keeps_stale_and_reports(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    _seed(mock_modbus_unit)
    diematic = await base_gtw26(mock_modbus_unit)
    first = await diematic.async_update()
    assert first.complete
    assert diematic.sensors.boiler_temperature == 65.0

    mock_modbus_unit.fail_read(75, IllegalDataAddressError())
    report = await diematic.async_update()

    assert not report.complete
    assert "sensors" in report.failed
    assert "sensors" not in report.updated
    assert "climate_zone_a" in report.updated
    assert diematic.sensors.boiler_temperature == 65.0


@pytest.mark.asyncio
async def test_dead_link_raises(mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory):
    _seed(mock_modbus_unit)
    diematic = await base_gtw26(mock_modbus_unit)
    mock_modbus_unit.fail_requests(ModbusConnectionError("link down"))
    with pytest.raises(ModbusConnectionError):
        await diematic.async_update()


@pytest.mark.asyncio
async def test_connection_error_during_individual_fallback_raises(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    _seed(mock_modbus_unit)
    diematic = await base_gtw26(mock_modbus_unit)
    attempts = 0

    async def failing(address: int, count: int) -> list[int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise IllegalDataAddressError
        raise ModbusConnectionError("link down")

    mock_modbus_unit.read_holding_registers = failing
    with pytest.raises(ModbusConnectionError):
        await diematic.async_update()


@pytest.mark.asyncio
async def test_connection_error_during_read_once_poll_raises(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    boiler = await isystem_gtw26(mock_modbus_unit)
    mock_modbus_unit.fail_read(126, ModbusConnectionError("link down"))
    with pytest.raises(ModbusConnectionError):
        await boiler.async_update()


@pytest.mark.asyncio
async def test_regulator_configures_message_spacing(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
    isystem_gtw26: Gtw26Factory,
):
    _seed(mock_modbus_unit)
    await base_gtw26(mock_modbus_unit)
    assert mock_modbus_unit.message_spacing == 0.05

    _seed_isystem(mock_modbus_unit)
    await isystem_gtw26(mock_modbus_unit)
    assert mock_modbus_unit.message_spacing == 0.05


@pytest.mark.parametrize("error", [ModbusTimeoutError(), ServerDeviceBusyError()])
@pytest.mark.asyncio
async def test_pooled_read_fails_on_timeout_busy_then_falls_back(
    mock_modbus_unit: MockModbusUnit,
    error: ModbusError,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(601, error)
    boiler = await isystem_gtw26(mock_modbus_unit)
    report = await boiler.async_update()

    assert "sensors" in report.failed
    assert "sensors" not in report.updated
    assert "climate_zone_a" in report.updated


@pytest.mark.asyncio
async def test_pooled_read_recovers_with_retrying_unit(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    retrying_unit = RetryingModbusUnit(mock_modbus_unit)
    boiler = await isystem_gtw26(retrying_unit)
    original = mock_modbus_unit.read_holding_registers
    attempts = 0

    async def flaky(address: int, count: int) -> list[int]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ModbusTimeoutError
        return await original(address, count)

    mock_modbus_unit.read_holding_registers = flaky
    report = await boiler.async_update()

    # Verify that RetryingModbusUnit retried the failing read
    assert report.complete
    assert attempts > 1  # First attempt fails, subsequent attempts succeed


@pytest.mark.asyncio
async def test_isystem_schedules_read_once(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    boiler = await isystem_gtw26(mock_modbus_unit)
    first = await boiler.async_update()
    assert "schedules.circuit_a_p4" in first.updated

    mock_modbus_unit.fail_read(126, IllegalDataAddressError())
    second = await boiler.async_update()
    assert "schedules.circuit_a_p4" not in second.failed
    assert "schedules.circuit_a_p4" not in second.updated


@pytest.mark.asyncio
async def test_isystem_read_once_retries_until_success(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(126, IllegalDataAddressError())
    boiler = await isystem_gtw26(mock_modbus_unit)
    first = await boiler.async_update()
    assert "schedules.circuit_a_p4" in first.failed
    assert "schedules.circuit_a_p4" not in first.updated
    assert "schedules.hot_water" in first.updated

    mock_modbus_unit.fail_read(126, None)
    second = await boiler.async_update()
    assert "schedules.circuit_a_p4" in second.updated


@pytest.mark.asyncio
async def test_isystem_config_retries_until_success_and_then_latches(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(247, IllegalDataAddressError())
    boiler = await isystem_gtw26(mock_modbus_unit)

    first = await boiler.async_update()
    assert "config" in first.failed
    assert "config" not in first.updated

    mock_modbus_unit.fail_read(247, None)
    second = await boiler.async_update()
    assert "config" in second.updated

    third = await boiler.async_update()
    assert "config" not in third.failed
    assert "config" not in third.updated


@pytest.mark.asyncio
async def test_isystem_partial_failure_keeps_stale_and_reports(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    _seed_isystem(mock_modbus_unit)
    boiler = await isystem_gtw26(mock_modbus_unit)
    first = await boiler.async_update()
    assert first.complete
    assert boiler.sensors.boiler_temperature == 65.0

    mock_modbus_unit.holding[602] = 660
    mock_modbus_unit.fail_read(601, IllegalDataAddressError())
    report = await boiler.async_update()

    assert not report.complete
    assert "sensors" in report.failed
    assert "sensors" not in report.updated
    assert boiler.sensors.boiler_temperature == 65.0


@pytest.mark.asyncio
async def test_read_raw_dumps_registers(mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory):
    _seed(mock_modbus_unit)
    diematic = await base_gtw26(mock_modbus_unit)
    raw = await diematic.async_read_all_raw()
    assert raw["holding"][75] == 650


@pytest.mark.parametrize(
    ("layout", "mode_address", "temp_address"),
    [
        pytest.param(RegisterLayout.BASE, 17, 75, id="base"),
        pytest.param(RegisterLayout.ISYSTEM, 653, 602, id="isystem"),
    ],
)
@pytest.mark.asyncio
async def test_poll_keeps_holiday_and_unknown_modes(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
    mode_address: int,
    temp_address: int,
):
    mock_modbus_unit.holding.update({mode_address: 0x71, temp_address: 650})
    boiler = await gtw26(mock_modbus_unit, layout)
    first = await boiler.async_update()
    assert first.complete
    assert boiler.climate_zones["A"].mode is HeatingMode.HOLIDAY
    assert boiler.sensors.boiler_temperature == 65.0

    mock_modbus_unit.holding.update({mode_address: 0x57, temp_address: 660})
    second = await boiler.async_update()
    assert second.complete
    assert {"climate_zone_a", "sensors"} <= second.updated
    assert type(boiler.climate_zones["A"].mode) is int
    assert boiler.climate_zones["A"].mode == 7
    assert boiler.sensors.boiler_temperature == 66.0

    mock_modbus_unit.holding[mode_address] = 0x58
    await boiler.async_update()
    assert boiler.climate_zones["A"].mode is HeatingMode.AUTO


@pytest.mark.asyncio
async def test_isystem_unknown_hot_water_and_active_modes(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding.update({659: 0x48, 640: 6, 641: 6})
    boiler = await isystem_gtw26(mock_modbus_unit)
    report = await boiler.async_update()
    assert report.complete
    assert boiler.climate_zones["B"].mode is HeatingMode.AUTO
    assert boiler.hot_water.mode == 64
    assert boiler.hot_water.active_mode == 6
    assert boiler.diagnostics.aux_active_mode == 6

    mock_modbus_unit.holding[659] = 0x58
    await boiler.async_update()
    assert boiler.hot_water.mode is HotWaterMode.TEMP


@pytest.mark.asyncio
async def test_concurrent_mode_writes_are_serialised(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[659] = 0x08
    boiler = await isystem_gtw26(mock_modbus_unit)
    original_read = mock_modbus_unit.read_holding_registers
    original_write = mock_modbus_unit.write_registers

    async def yielding_read(address: int, count: int) -> list[int]:
        await asyncio.sleep(0)
        return await original_read(address, count)

    async def yielding_write(address: int, values: list[int]) -> None:
        await asyncio.sleep(0)
        await original_write(address, values)

    mock_modbus_unit.read_holding_registers = yielding_read
    mock_modbus_unit.write_registers = yielding_write
    await asyncio.gather(
        boiler.async_set_heating_mode("B", HeatingMode.TEMP_DAY),
        boiler.async_set_hot_water_mode(HotWaterMode.PERM),
    )
    word = mock_modbus_unit.holding[659]
    assert word & 0x2F == int(HeatingMode.TEMP_DAY)
    assert word & 0x50 == int(HotWaterMode.PERM)
