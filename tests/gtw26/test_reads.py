import pytest
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw26 import GTW26, HeatingMode, HotWaterMode, HotWaterPriority
from aio_remeha_modbus.gtw26.const import (
    BASE_WINDOWS,
    SCHEDULE_BASES,
    ControllerGeneration,
    RegisterLayout,
)


def _seed(unit: MockModbusUnit) -> None:
    unit.holding.update(
        {
            3: 400,
            4: 14,
            5: 30,
            7: 205,
            102: 175,
            14: 550,
            17: 0x58,
            18: 210,
            27: 0xFFFF,
            30: 0xFFFF,
            31: 0xFFFF,
            32: 0xFFFF,
            33: 0xFFFF,
            59: 550,
            60: 0,
            62: 500,
            75: 650,
            110: 25,
            427: 0x38,
            453: 0xFFFF,
            455: 3000,
            456: 15,
            457: 3,
            459: 505,
            462: 700,
            463: 42,
            465: 0xFFFF,
            116: 0x0005,
            121: 800,
            467: 0x8000 | 120,
            470: 195,
            471: 250,
        }
    )


def base_gtw26(
    unit, *, variant=ControllerGeneration.GENERATION_3, force_circuit_a=False, force_circuit_b=False
):
    device = GTW26(
        "test",
        unit,
        layout=RegisterLayout.BASE,
        generation=variant,
        force_zone_a=force_circuit_a,
        force_zone_b=force_circuit_b,
    )
    device._build_base_components()
    from modbus_connection.model import ComponentGroup

    device._pool = ComponentGroup(unit, list(device._bundles.values()))
    device._poll_group = device._pool
    device._setup_complete = True
    return device


def isystem_gtw26(
    unit,
    *,
    variant=ControllerGeneration.GENERATION_4,
    force_circuit_a=False,
    force_circuit_b=False,
    force_circuit_c=False,
):
    device = GTW26(
        "test",
        unit,
        layout=RegisterLayout.ISYSTEM,
        generation=variant,
        force_zone_a=force_circuit_a,
        force_zone_b=force_circuit_b,
        force_zone_c=force_circuit_c,
    )
    device._build_isystem_components()
    from modbus_connection.model import ComponentGroup

    read_once = {"config", *(f"schedules.{name}" for name in SCHEDULE_BASES)}
    device._pool = ComponentGroup(
        unit, [component for name, component in device._bundles.items() if name not in read_once]
    )
    device._read_once = frozenset(read_once)
    device._pending_once = {name: device._bundles[name] for name in read_once}
    device._poll_group = device._pool
    device.config._on_written = device._invalidate_read_once
    for program in device.schedule.bundles().values():
        program._on_day_written = device._invalidate_read_once
    device._setup_complete = True
    return device


@pytest.mark.asyncio
async def test_reads_decode_across_bundles(mock_modbus_unit):
    _seed(mock_modbus_unit)
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()

    assert diematic.sensors.outdoor_temperature == 20.5
    assert diematic.sensors.mean_outside_temperature == 17.5
    assert diematic.sensors.boiler_temperature == 65.0
    assert diematic.settings.primary_boiler_temperature == 80.0
    assert diematic.sensors.return_temperature is None
    assert diematic.sensors.water_pressure == 1.5
    assert diematic.sensors.fan_speed == 3000
    assert diematic.sensors.pump_power == 42
    assert diematic.sensors.burner_active is True
    assert diematic.sensors.hot_water_pump_active is True
    assert diematic.sensors.fault is None
    assert diematic.sensors.sensor_faults == 5

    assert diematic.hot_water.temperature == 50.0
    assert diematic.hot_water.temperature_dpsm == 50.5
    assert diematic.hot_water.mode is HotWaterMode.TEMP
    assert diematic.hot_water.priority is HotWaterPriority.TOTAL
    assert diematic.service.burner_start_count == 0.0
    assert diematic.service.burner_runtime_hours == 0.0
    assert diematic.hot_water.comfort_target == 55.0

    assert diematic.sensors.calculated_boiler_temperature == 70.0
    assert diematic.sensors.outdoor_temperature_bus == 19.5
    assert diematic.sensors.instantaneous_power == 25.0
    assert diematic.sensors.solar_temperature == -12.0

    assert diematic.climate_zones["A"].mode is HeatingMode.AUTO
    assert diematic.climate_zones["A"].room_temperature == 21.0
    assert diematic.climate_zones["A"].pump_active is True

    assert diematic.identity.year == 25


@pytest.mark.asyncio
async def test_base_pooled_reads_stay_inside_windows(mock_modbus_unit):
    _seed(mock_modbus_unit)
    diematic = base_gtw26(mock_modbus_unit)

    await diematic.async_update()

    blocks = [
        (event.address, event.count)
        for event in mock_modbus_unit.read_events
        if event.register_type == "holding"
    ]
    assert blocks
    for start, count in blocks:
        end = start + count - 1
        assert (
            sum(
                window_start <= start and end <= window_end
                for window_start, window_end in BASE_WINDOWS
            )
            == 1
        )
    for window_start, window_end in BASE_WINDOWS:
        assert any(
            window_start <= start and end <= window_end
            for start, count in blocks
            for end in (start + count - 1,)
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, HotWaterPriority.TOTAL),
        (1, HotWaterPriority.SLIDING),
        (2, HotWaterPriority.NONE),
        (3, 3),
    ],
)
@pytest.mark.asyncio
async def test_base_hot_water_priority_decodes_low_byte(mock_modbus_unit, raw, expected):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[60] = raw
    diematic = base_gtw26(mock_modbus_unit)

    await diematic.async_update()

    assert diematic.hot_water.priority == expected


@pytest.mark.asyncio
async def test_fork_registers_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({9: 0x8032, 19: 3, 28: 3, 30: 100, 31: 420, 33: 246})
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.settings.frost_threshold == -5.0
    assert diematic.climate_zones["A"].ambient_influence == 3
    assert diematic.climate_zones["B"].ambient_influence == 3
    assert diematic.climate_zones["B"].min_temperature == 10.0
    assert diematic.climate_zones["B"].max_temperature == 42.0
    assert diematic.climate_zones["B"].supply_temperature == 24.6


@pytest.mark.asyncio
async def test_boiler_type_decodes_controller_name(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[457] = 24
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.identity.controller_type == "D4"
    mock_modbus_unit.holding[457] = 999
    await diematic.async_update()
    assert diematic.identity.controller_type == 999


@pytest.mark.asyncio
async def test_known_alarm_code_decodes_to_label(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[465] = 0x100D
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.sensors.fault == "DEF.ALLUMAGE 14"


@pytest.mark.asyncio
async def test_unknown_alarm_code_surfaces_as_raw_int(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[465] = 0x7777
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.sensors.fault == 0x7777


@pytest.mark.asyncio
async def test_absent_integer_sensors_read_none(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[463] = 0xFFFF
    mock_modbus_unit.holding[455] = 0xFFFF
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.sensors.pump_power is None
    assert diematic.sensors.fan_speed is None


@pytest.mark.asyncio
async def test_smoke_temp_out_of_range_reads_none(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[454] = 0x8CCC
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.sensors.flue_gas_temperature is None
    mock_modbus_unit.holding[454] = 800
    await diematic.async_update()
    assert diematic.sensors.flue_gas_temperature == 80.0


@pytest.mark.asyncio
async def test_dpsm_boiler_temp_decodes(mock_modbus_unit):
    mock_modbus_unit.holding[452] = 281
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.sensors.boiler_temperature_dpsm == 28.1


@pytest.mark.asyncio
async def test_circuit_presence_follows_room_temp(mock_modbus_unit):
    _seed(mock_modbus_unit)
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.zone_a_present is True
    assert diematic.zone_b_present is False


@pytest.mark.asyncio
async def test_hot_water_presence_follows_temperature(mock_modbus_unit):
    _seed(mock_modbus_unit)
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.hot_water_present is True

    mock_modbus_unit.holding[62] = 0xFFFF
    mock_modbus_unit.holding[459] = 505
    await diematic.async_update()
    assert diematic.hot_water_present is True

    mock_modbus_unit.holding[459] = 0xFFFF
    await diematic.async_update()
    assert diematic.hot_water_present is False


@pytest.mark.asyncio
async def test_hot_water_zero_temperature_counts_as_present(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[62] = 0
    mock_modbus_unit.holding[459] = 0xFFFF
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_update()
    assert diematic.hot_water_present is True


@pytest.mark.asyncio
async def test_force_circuit_b_overrides_absent_sensor(mock_modbus_unit):
    _seed(mock_modbus_unit)
    diematic = base_gtw26(mock_modbus_unit, force_circuit_b=True)
    await diematic.async_update()
    assert diematic.zone_b_present is True


def test_base_layout_rejects_force_zone_c(mock_modbus_unit: MockModbusUnit) -> None:
    with pytest.raises(ValueError, match="force_zone_c"):
        GTW26("test", mock_modbus_unit, layout=RegisterLayout.BASE, force_zone_c=True)
