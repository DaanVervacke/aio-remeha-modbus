from datetime import datetime, time

import pytest

from aio_remeha_modbus.gtw26 import (
    GTW26,
    HeatingMode,
    HotWaterMode,
    HotWaterPriority,
    NightMode,
)
from aio_remeha_modbus.gtw26.const import SCHEDULE_BASES, ControllerGeneration, RegisterLayout
from aio_remeha_modbus.gtw26.schedule import ScheduleDayField, WeekProgram
from aio_remeha_modbus.helpers.gtw26 import decode_day


@pytest.mark.asyncio
async def test_hot_water_setpoint_snaps_and_writes(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.hot_water.write("comfort_target", 53.4)
    assert mock_modbus_unit.holding[59] == 530


@pytest.mark.asyncio
async def test_hot_water_pump_delay_writes_register_61(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.hot_water.write("pump_delay", 3)
    assert mock_modbus_unit.holding[61] == 3


@pytest.mark.asyncio
async def test_isystem_legionella_protection_writes_register_268(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.hot_water.write("legionella_protection", 1)
    assert mock_modbus_unit.holding[268] == 1


@pytest.mark.asyncio
async def test_settings_boiler_max_writes(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.settings.write("boiler_maximum_temperature", 75)
    assert mock_modbus_unit.holding[71] == 750


@pytest.mark.asyncio
async def test_settings_ext_frost_threshold_writes_positive_value(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.settings.write("frost_threshold", 5)
    assert mock_modbus_unit.holding[9] == 50


@pytest.mark.asyncio
async def test_settings_ext_frost_threshold_rejects_negative_value(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="between 0 and 10"):
        await diematic.settings.write("frost_threshold", -5)
    assert 9 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_circuit_slope_writes(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.climate_zones["A"].write("heating_curve_slope", 1.5)
    assert mock_modbus_unit.holding[20] == 15


@pytest.mark.asyncio
async def test_circuit_slope_clamps_high(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.climate_zones["A"].write("heating_curve_slope", 5)
    assert mock_modbus_unit.holding[20] == 40


@pytest.mark.asyncio
async def test_summer_winter_snaps_and_clamps(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.settings.write("summer_winter_temperature", 22.3)
    assert mock_modbus_unit.holding[8] == 225
    await diematic.settings.write("summer_winter_temperature", 40)
    assert mock_modbus_unit.holding[8] == 305


@pytest.mark.asyncio
async def test_set_clock_writes_blocks_with_marker(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_set_clock(datetime(2026, 9, 4, 14, 5))
    assert mock_modbus_unit.holding[4] == 0xFF00 | 14
    assert mock_modbus_unit.holding[5] == 0xFF00 | 5
    assert mock_modbus_unit.holding[6] == 0xFF00 | 5
    assert mock_modbus_unit.holding[108] == 0xFF00 | 4
    assert mock_modbus_unit.holding[109] == 0xFF00 | 9
    assert mock_modbus_unit.holding[110] == 0xFF00 | 26


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


def test_schedule_day_encode_matches_verified_window():
    words = ScheduleDayField(0).encode([(time(8, 0), time(9, 0))])
    assert words == [0x0000, 0xC000, 0x0000]


def test_schedule_day_encode_round_trips():
    periods = [(time(6, 0), time(8, 0)), (time(16, 0), time(0, 0))]
    assert decode_day(ScheduleDayField(0).encode(periods)) == periods


@pytest.mark.asyncio
async def test_isystem_set_day_writes_three_words(mock_modbus_unit):
    program = WeekProgram(mock_modbus_unit, base_offset=147)
    await program.async_set_day(1, [(time(8, 0), time(9, 0))])
    assert [mock_modbus_unit.holding[a] for a in range(147, 150)] == [0x0, 0xC000, 0x0]


@pytest.mark.parametrize("schedule, base", SCHEDULE_BASES.items())
@pytest.mark.parametrize("weekday", range(1, 8))
@pytest.mark.asyncio
async def test_isystem_set_day_writes_requested_three_register_block(
    mock_modbus_unit, schedule, base, weekday
):
    mock_modbus_unit.holding.update({231: 0x2000, 232: 0x2023, 233: 0x2038})
    boiler = isystem_gtw26(mock_modbus_unit)

    await boiler.schedule.async_set_day(schedule, weekday, [(time(8, 0), time(9, 0))])

    start = base + 3 * (weekday - 1)
    assert [mock_modbus_unit.holding[address] for address in range(start, start + 3)] == [
        0x0000,
        0xC000,
        0x0000,
    ]
    assert [mock_modbus_unit.holding[address] for address in range(231, 234)] == [
        0x2000,
        0x2023,
        0x2038,
    ]


@pytest.mark.asyncio
async def test_isystem_schedules_set_day_facade_writes(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.schedule.async_set_day("circuit_b_p4", 1, [(time(8, 0), time(9, 0))])
    assert [mock_modbus_unit.holding[a] for a in range(147, 150)] == [0x0, 0xC000, 0x0]


@pytest.mark.asyncio
async def test_isystem_schedules_set_day_rejects_unknown_schedule(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="unknown schedule"):
        await boiler.schedule.async_set_day("nope", 1, [])


@pytest.mark.asyncio
async def test_isystem_schedules_read_paths_reject_unknown_schedule(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="unknown schedule"):
        boiler.schedule.get_week("nope")
    with pytest.raises(ValueError, match="unknown schedule"):
        boiler.schedule.get_day("nope", 1)
    with pytest.raises(ValueError, match="unknown schedule"):
        await boiler.schedule.async_update("nope")


@pytest.mark.asyncio
async def test_isystem_set_day_rejects_bad_weekday(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="weekday"):
        await boiler.schedule.async_set_day("circuit_b_p4", 0, [])


def test_schedule_day_encode_rejects_reversed_period():
    with pytest.raises(ValueError, match="invalid comfort period"):
        ScheduleDayField(0).encode([(time(9, 0), time(8, 0))])


@pytest.mark.asyncio
async def test_isystem_set_clock_writes_plain_block(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_set_clock(datetime(2026, 9, 4, 14, 5))
    written = [mock_modbus_unit.holding[a] for a in range(679, 685)]
    assert written == [14, 5, 5, 4, 9, 26]


@pytest.mark.asyncio
async def test_hot_water_setpoint_clamps_high(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.hot_water.write("comfort_target", 200)
    assert mock_modbus_unit.holding[59] == 800


@pytest.mark.asyncio
async def test_zone_setpoint_half_degree_step(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.climate_zones["A"].write("comfort_target", 20.3)
    assert mock_modbus_unit.holding[14] == 205


@pytest.mark.asyncio
async def test_setting_heating_mode_preserves_hot_water_bits(mock_modbus_unit):
    mock_modbus_unit.holding[17] = 0x58
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_set_heating_mode("A", HeatingMode.TEMP_DAY)
    word = mock_modbus_unit.holding[17]
    assert word & 0x2F == int(HeatingMode.TEMP_DAY)
    assert word & 0x50 == int(HotWaterMode.TEMP)


@pytest.mark.asyncio
async def test_setting_hot_water_mode_preserves_heating_bits(mock_modbus_unit):
    mock_modbus_unit.holding[17] = 0x58
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    word = mock_modbus_unit.holding[17]
    assert word & 0x50 == int(HotWaterMode.PERM)
    assert word & 0x2F == int(HeatingMode.AUTO)


@pytest.mark.asyncio
async def test_base_hot_water_mode_mirrors_into_registers_17_and_26(mock_modbus_unit):
    mock_modbus_unit.holding[17] = 0x01
    mock_modbus_unit.holding[26] = 0x08
    diematic = base_gtw26(mock_modbus_unit)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    assert mock_modbus_unit.holding[17] & 0x50 == int(HotWaterMode.PERM)
    assert mock_modbus_unit.holding[26] & 0x50 == int(HotWaterMode.PERM)
    assert mock_modbus_unit.holding[17] & 0x2F == 0x01
    assert mock_modbus_unit.holding[26] & 0x2F == 0x08


@pytest.mark.asyncio
async def test_base_hot_water_mode_reads_both_before_writing_either(mock_modbus_unit):
    mock_modbus_unit.holding[17] = 0x01
    mock_modbus_unit.holding[26] = 0x08
    reads_seen_at_first_write: list[int] = []
    writes: list[int] = []

    def record(event):
        if not writes:
            reads_seen_at_first_write.extend(e.address for e in mock_modbus_unit.read_events)
        writes.append(event.address)

    mock_modbus_unit.on_write(record)
    diematic = base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_3)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    assert reads_seen_at_first_write == [17, 26]
    assert writes == [17, 26]


@pytest.mark.asyncio
async def test_isystem_hot_water_mode_writes_single_register(mock_modbus_unit):
    mock_modbus_unit.holding[659] = 0x08
    boiler = isystem_gtw26(mock_modbus_unit)
    writes: list[int] = []
    mock_modbus_unit.on_write(lambda e: writes.append(e.address))
    await boiler.async_set_hot_water_mode(HotWaterMode.PERM)
    assert writes == [659]
    assert mock_modbus_unit.holding[659] & 0x50 == int(HotWaterMode.PERM)


@pytest.mark.asyncio
async def test_isystem_circuit_slope_writes_and_clamps(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones["B"].write("heating_curve_slope", 0.9)
    assert mock_modbus_unit.holding[661] == 9
    await boiler.climate_zones["C"].write("heating_curve_slope", 5)
    assert mock_modbus_unit.holding[669] == 40


@pytest.mark.asyncio
async def test_isystem_circuit_min_max_write_plain(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones["B"].write("min_temperature", 12.0)
    await boiler.climate_zones["B"].write("max_temperature", 63.0)
    assert mock_modbus_unit.holding[662] == 120
    assert mock_modbus_unit.holding[663] == 630
    await boiler.climate_zones["C"].write("min_temperature", 15.0)
    await boiler.climate_zones["C"].write("max_temperature", 55.0)
    assert mock_modbus_unit.holding[670] == 150
    assert mock_modbus_unit.holding[671] == 550


@pytest.mark.asyncio
async def test_diematic3_does_not_nudge_panel(mock_modbus_unit):
    diematic = base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_3)
    await diematic.async_set_heating_mode("A", HeatingMode.AUTO)
    assert 13 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_diematic4_nudges_panel(mock_modbus_unit, monkeypatch):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("aio_remeha_modbus.gtw26.gtw26.asyncio.sleep", _no_sleep)
    diematic = base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)
    await diematic.async_set_heating_mode("A", HeatingMode.AUTO)
    assert mock_modbus_unit.holding[13] == 0


@pytest.mark.parametrize("field", ["outdoor_temperature"])
@pytest.mark.asyncio
async def test_reading_field_is_not_writable(mock_modbus_unit, field):
    diematic = base_gtw26(mock_modbus_unit)
    with pytest.raises(AttributeError):
        await diematic.sensors.write(field, 10)


@pytest.mark.parametrize(
    ("regulator_type", "designation"),
    [
        (base_gtw26, "A"),
        (base_gtw26, "B"),
        (isystem_gtw26, "A"),
        (isystem_gtw26, "B"),
        (isystem_gtw26, "C"),
    ],
)
@pytest.mark.parametrize("mode", [HeatingMode.HOLIDAY, 33, 7, 0x58])
@pytest.mark.asyncio
async def test_unsupported_heating_mode_rejected_before_io(
    mock_modbus_unit, regulator_type, designation, mode
):
    boiler = regulator_type(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError):
        await boiler.async_set_heating_mode(designation, mode)
    assert mock_modbus_unit.read_events == []
    assert writes == []


@pytest.mark.parametrize("regulator_type", [base_gtw26, isystem_gtw26])
@pytest.mark.asyncio
async def test_unknown_hot_water_mode_rejected_before_io(mock_modbus_unit, regulator_type):
    boiler = regulator_type(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError):
        await boiler.async_set_hot_water_mode(64)
    assert mock_modbus_unit.read_events == []
    assert writes == []


@pytest.mark.parametrize(("regulator_type", "address"), [(base_gtw26, 17), (isystem_gtw26, 659)])
@pytest.mark.parametrize("mode", list(HotWaterMode))
@pytest.mark.asyncio
async def test_hot_water_write_preserves_holiday(mock_modbus_unit, regulator_type, address, mode):
    mock_modbus_unit.holding[address] = 0xA1
    boiler = regulator_type(mock_modbus_unit)
    await boiler.async_set_hot_water_mode(mode)
    assert mock_modbus_unit.holding[address] == 0xA1 | int(mode)


@pytest.mark.parametrize("mode", [mode for mode in HeatingMode if mode is not HeatingMode.HOLIDAY])
@pytest.mark.asyncio
async def test_known_heating_modes_preserve_unknown_hot_water_bits(mock_modbus_unit, mode):
    mock_modbus_unit.holding[659] = 0xC8
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_set_heating_mode("B", mode)
    assert mock_modbus_unit.holding[659] == 0xC0 | int(mode)


@pytest.mark.asyncio
async def test_isystem_hot_water_pump_delay_clamps_and_writes_register_61(
    mock_modbus_unit,
):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.hot_water.write("pump_delay", 3)
    assert mock_modbus_unit.holding[61] == 3
    await boiler.hot_water.write("pump_delay", 40)
    assert mock_modbus_unit.holding[61] == 15


@pytest.mark.asyncio
async def test_isystem_hot_water_priority_writes_register_674(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.hot_water.write("priority", HotWaterPriority.SLIDING)
    assert mock_modbus_unit.holding[674] == 1


@pytest.mark.parametrize(
    ("field", "value", "address", "raw"),
    [
        ("anticipation_a", 0.14, 282, 1),
        ("anticipation_b", 20, 283, 100),
        ("anticipation_c", 0.0, 284, 0),
        ("zone_a_min", 31.2, 298, 310),
        ("zone_a_min", 5, 298, 100),
        ("zone_a_max", 74.0, 299, 740),
        ("zone_a_max", 200, 299, 1200),
    ],
)
@pytest.mark.asyncio
async def test_isystem_config_writes_snap_and_clamp(mock_modbus_unit, field, value, address, raw):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.config.write(field, value)
    assert mock_modbus_unit.holding[address] == raw


@pytest.mark.asyncio
async def test_isystem_outdoor_antifreeze_is_read_only(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    with pytest.raises(AttributeError):
        await boiler.settings.write("outdoor_antifreeze", 5)


@pytest.mark.asyncio
async def test_isystem_config_write_rearms_cached_read(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    mock_modbus_unit.holding[298] = 300
    first = await boiler.async_update()
    assert "config" in first.updated
    assert "config" not in (await boiler.async_update()).updated

    await boiler.config.write("zone_a_min", 31.0)
    report = await boiler.async_update()
    assert "config" in report.updated
    assert boiler.config.zone_a_min == 31.0


@pytest.mark.asyncio
async def test_isystem_night_mode_and_heating_pump_delay_write(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.settings.write("night_mode", NightMode.STOP)
    assert mock_modbus_unit.holding[10] == 0
    await boiler.settings.write("heating_pump_delay", 20)
    assert mock_modbus_unit.holding[11] == 15


@pytest.mark.parametrize(
    ("bundle", "field", "value", "address", "raw"),
    [
        ("config", "building_inertia", 4, 264, 4),
        ("config", "building_inertia", 30, 264, 10),
        ("config", "bandwidth", 12.4, 266, 120),
        ("config", "bandwidth", 2, 266, 40),
    ],
)
@pytest.mark.asyncio
async def test_isystem_panel_and_tuning_writes(
    mock_modbus_unit, bundle, field, value, address, raw
):
    boiler = isystem_gtw26(mock_modbus_unit)
    await getattr(boiler, bundle).write(field, value)
    assert mock_modbus_unit.holding[address] == raw


@pytest.mark.parametrize("field", ["min_running_time", "burner_temporisation", "pump_postrun"])
@pytest.mark.asyncio
async def test_isystem_psu_settings_stay_read_only(mock_modbus_unit, field):
    boiler = isystem_gtw26(mock_modbus_unit)
    with pytest.raises(AttributeError):
        await boiler.config.write(field, 1)


@pytest.mark.parametrize(
    ("circuit", "field", "value", "address", "raw"),
    [
        ("climate_zone_b", "reduced_target", 4, 657, 50),
        ("climate_zone_b", "reduced_target", 9.2, 657, 90),
        ("climate_zone_a", "reduced_target", 35, 651, 300),
        ("climate_zone_b", "min_temperature", 5, 662, 100),
        ("climate_zone_c", "min_temperature", 40, 670, 300),
        ("climate_zone_b", "max_temperature", 120, 663, 950),
        ("climate_zone_c", "max_temperature", 42.3, 671, 500),
    ],
)
@pytest.mark.asyncio
async def test_isystem_circuit_limits_clamp(mock_modbus_unit, circuit, field, value, address, raw):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones[circuit[-1].upper()].write(field, value)
    assert mock_modbus_unit.holding[address] == raw
