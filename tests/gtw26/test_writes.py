from datetime import datetime, time

import pytest
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw08.errors import RemehaApiError
from aio_remeha_modbus.gtw26 import (
    HeatingMode,
    HotWaterMode,
    HotWaterPriority,
    NightMode,
)
from aio_remeha_modbus.gtw26.const import (
    SCHEDULE_BASES,
    ControllerGeneration,
    RegisterLayout,
    Weekday,
)
from aio_remeha_modbus.gtw26.schedule import ComfortPeriod, ScheduleDayField, WeekProgram
from aio_remeha_modbus.helpers.gtw26 import decode_day
from tests.gtw26.conftest import Gtw26Factory, LayoutGtw26Factory


@pytest.mark.asyncio
async def test_hot_water_setpoint_snaps_and_writes(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.hot_water.write("comfort_target", 53.4)
    assert mock_modbus_unit.holding[59] == 530


@pytest.mark.asyncio
async def test_hot_water_pump_delay_writes_register_61(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.hot_water.write("pump_delay", 3)
    assert mock_modbus_unit.holding[61] == 3


@pytest.mark.parametrize("value", [-1, 16, 40])
@pytest.mark.asyncio
async def test_base_hot_water_pump_delay_rejects_out_of_range(
    mock_modbus_unit: MockModbusUnit,
    value: int,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError, match="between 0 and 15"):
        await diematic.hot_water.write("pump_delay", value)
    assert writes == []
    assert 61 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_isystem_legionella_protection_writes_register_268(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.hot_water.write("legionella_protection", 1)
    assert mock_modbus_unit.holding[268] == 1


@pytest.mark.asyncio
async def test_settings_boiler_max_writes(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.settings.write("boiler_maximum_temperature", 75)
    assert mock_modbus_unit.holding[71] == 750


@pytest.mark.parametrize(
    ("field", "value", "address"),
    [
        pytest.param("boiler_minimum_temperature", 20.0, 70, id="min-below"),
        pytest.param("boiler_minimum_temperature", 55.0, 70, id="min-above"),
        pytest.param("boiler_maximum_temperature", 40.0, 71, id="max-below"),
        pytest.param("boiler_maximum_temperature", 100.0, 71, id="max-above"),
    ],
)
@pytest.mark.asyncio
async def test_settings_boiler_temperatures_reject_out_of_range(
    mock_modbus_unit: MockModbusUnit,
    field: str,
    value: float,
    address: int,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError, match="must be between"):
        await diematic.settings.write(field, value)
    assert writes == []
    assert address not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_settings_ext_frost_threshold_writes_positive_value(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.settings.write("frost_threshold", 5)
    assert mock_modbus_unit.holding[9] == 50


@pytest.mark.asyncio
async def test_settings_ext_frost_threshold_rejects_negative_value(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="between 0 and 10"):
        await diematic.settings.write("frost_threshold", -5)
    assert 9 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_circuit_slope_writes(mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.climate_zones["A"].write("heating_curve_slope", 1.5)
    assert mock_modbus_unit.holding[20] == 15


@pytest.mark.asyncio
async def test_circuit_slope_clamps_high(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.climate_zones["A"].write("heating_curve_slope", 5)
    assert mock_modbus_unit.holding[20] == 40


@pytest.mark.asyncio
async def test_summer_winter_snaps_and_clamps(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.settings.write("summer_winter_temperature", 22.3)
    assert mock_modbus_unit.holding[8] == 225
    await diematic.settings.write("summer_winter_temperature", 40)
    assert mock_modbus_unit.holding[8] == 305


@pytest.mark.asyncio
async def test_set_clock_writes_blocks_with_marker(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.async_set_clock(datetime(2026, 9, 4, 14, 5))
    assert mock_modbus_unit.holding[4] == 0xFF00 | 14
    assert mock_modbus_unit.holding[5] == 0xFF00 | 5
    assert mock_modbus_unit.holding[6] == 0xFF00 | 5
    assert mock_modbus_unit.holding[108] == 0xFF00 | 4
    assert mock_modbus_unit.holding[109] == 0xFF00 | 9
    assert mock_modbus_unit.holding[110] == 0xFF00 | 26


def test_schedule_day_encode_matches_verified_window():
    words = ScheduleDayField(0).encode([(time(8, 0), time(9, 0))])
    assert words == [0x0000, 0xC000, 0x0000]


def test_schedule_day_encode_round_trips():
    periods = [(time(6, 0), time(8, 0)), (time(16, 0), time(0, 0))]
    assert decode_day(ScheduleDayField(0).encode(periods)) == periods


@pytest.mark.asyncio
async def test_isystem_set_day_writes_three_words(mock_modbus_unit: MockModbusUnit):
    program = WeekProgram(mock_modbus_unit, base_offset=147)
    await program.async_set_day(Weekday.MONDAY, [ComfortPeriod(time(8, 0), time(9, 0))])
    assert [mock_modbus_unit.holding[a] for a in range(147, 150)] == [0x0, 0xC000, 0x0]


@pytest.mark.parametrize("schedule, base", SCHEDULE_BASES.items())
@pytest.mark.parametrize("weekday", list(Weekday))
@pytest.mark.asyncio
async def test_isystem_set_day_writes_requested_three_register_block(
    mock_modbus_unit: MockModbusUnit,
    schedule: str,
    base: int,
    weekday: Weekday,
    isystem_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding.update({231: 0x2000, 232: 0x2023, 233: 0x2038})
    boiler = await isystem_gtw26(mock_modbus_unit)

    await boiler.schedule.async_set_day(schedule, weekday, [ComfortPeriod(time(8, 0), time(9, 0))])

    start = base + 3 * int(weekday)
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
async def test_isystem_schedules_set_day_facade_writes(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.schedule.async_set_day(
        "circuit_b_p4", Weekday.MONDAY, [ComfortPeriod(time(8, 0), time(9, 0))]
    )
    assert [mock_modbus_unit.holding[a] for a in range(147, 150)] == [0x0, 0xC000, 0x0]


@pytest.mark.asyncio
async def test_isystem_schedules_set_day_rejects_unknown_schedule(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="unknown schedule"):
        await boiler.schedule.async_set_day("nope", Weekday.MONDAY, [])


@pytest.mark.asyncio
async def test_isystem_schedules_read_paths_reject_unknown_schedule(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="unknown schedule"):
        boiler.schedule.get_week("nope")
    with pytest.raises(ValueError, match="unknown schedule"):
        boiler.schedule.get_day("nope", Weekday.MONDAY)
    with pytest.raises(ValueError, match="unknown schedule"):
        await boiler.schedule.async_update("nope")


@pytest.mark.asyncio
async def test_isystem_set_day_rejects_bad_weekday(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    with pytest.raises(ValueError, match="Weekday"):
        await boiler.schedule.async_set_day("circuit_b_p4", 7, [])


def test_schedule_day_encode_rejects_reversed_period():
    with pytest.raises(ValueError, match="invalid comfort period"):
        ScheduleDayField(0).encode([(time(9, 0), time(8, 0))])


@pytest.mark.asyncio
async def test_isystem_set_clock_writes_plain_block(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.async_set_clock(datetime(2026, 9, 4, 14, 5))
    written = [mock_modbus_unit.holding[a] for a in range(679, 685)]
    assert written == [14, 5, 5, 4, 9, 26]


@pytest.mark.asyncio
async def test_hot_water_setpoint_clamps_high(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.hot_water.write("comfort_target", 200)
    assert mock_modbus_unit.holding[59] == 800
    assert diematic.hot_water.comfort_target == 80.0


@pytest.mark.asyncio
async def test_zone_setpoint_half_degree_step(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.climate_zones["A"].write("comfort_target", 20.3)
    assert mock_modbus_unit.holding[14] == 205
    assert diematic.climate_zones["A"].comfort_target == 20.5


@pytest.mark.asyncio
async def test_setting_heating_mode_preserves_hot_water_bits(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[17] = 0x58
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.async_set_heating_mode("A", HeatingMode.TEMP_DAY)
    word = mock_modbus_unit.holding[17]
    assert word & 0x2F == int(HeatingMode.TEMP_DAY)
    assert word & 0x50 == int(HotWaterMode.TEMP)


@pytest.mark.asyncio
async def test_setting_hot_water_mode_preserves_heating_bits(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[17] = 0x58
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    word = mock_modbus_unit.holding[17]
    assert word & 0x50 == int(HotWaterMode.PERM)
    assert word & 0x2F == int(HeatingMode.AUTO)


@pytest.mark.asyncio
async def test_base_hot_water_mode_mirrors_into_registers_17_and_26(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[17] = 0x01
    mock_modbus_unit.holding[26] = 0x08
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    assert mock_modbus_unit.holding[17] & 0x50 == int(HotWaterMode.PERM)
    assert mock_modbus_unit.holding[26] & 0x50 == int(HotWaterMode.PERM)
    assert mock_modbus_unit.holding[17] & 0x2F == 0x01
    assert mock_modbus_unit.holding[26] & 0x2F == 0x08


@pytest.mark.asyncio
async def test_base_hot_water_mode_reads_both_before_writing_either(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[17] = 0x01
    mock_modbus_unit.holding[26] = 0x08
    reads_seen_at_first_write: list[int] = []
    writes: list[int] = []

    def record(event):
        if not writes:
            reads_seen_at_first_write.extend(e.address for e in mock_modbus_unit.read_events)
        writes.append(event.address)

    mock_modbus_unit.on_write(record)
    diematic = await base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_3)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    assert reads_seen_at_first_write == [17, 26]
    assert writes == [17, 26]


@pytest.mark.asyncio
async def test_isystem_hot_water_mode_writes_single_register(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[659] = 0x08
    boiler = await isystem_gtw26(mock_modbus_unit)
    writes: list[int] = []
    mock_modbus_unit.on_write(lambda e: writes.append(e.address))
    await boiler.async_set_hot_water_mode(HotWaterMode.PERM)
    assert writes == [659]
    assert mock_modbus_unit.holding[659] & 0x50 == int(HotWaterMode.PERM)


@pytest.mark.asyncio
async def test_isystem_circuit_slope_writes_and_clamps(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones["B"].write("heating_curve_slope", 0.9)
    assert mock_modbus_unit.holding[661] == 9
    await boiler.climate_zones["C"].write("heating_curve_slope", 5)
    assert mock_modbus_unit.holding[669] == 40


@pytest.mark.asyncio
async def test_isystem_circuit_min_max_write_plain(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones["B"].write("min_temperature", 12.0)
    await boiler.climate_zones["B"].write("max_temperature", 63.0)
    assert mock_modbus_unit.holding[662] == 120
    assert mock_modbus_unit.holding[663] == 630
    await boiler.climate_zones["C"].write("min_temperature", 15.0)
    await boiler.climate_zones["C"].write("max_temperature", 55.0)
    assert mock_modbus_unit.holding[670] == 150
    assert mock_modbus_unit.holding[671] == 550


@pytest.mark.asyncio
async def test_diematic3_does_not_nudge_panel(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_3)
    await diematic.async_set_heating_mode("A", HeatingMode.AUTO)
    assert 13 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_diematic4_nudges_panel(
    mock_modbus_unit: MockModbusUnit,
    monkeypatch: pytest.MonkeyPatch,
    base_gtw26: Gtw26Factory,
):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("aio_remeha_modbus.gtw26.gtw26.asyncio.sleep", _no_sleep)
    diematic = await base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)
    await diematic.async_set_heating_mode("A", HeatingMode.AUTO)
    assert mock_modbus_unit.holding[13] == 0


@pytest.mark.parametrize("field", ["outdoor_temperature"])
@pytest.mark.asyncio
async def test_reading_field_is_not_writable(
    mock_modbus_unit: MockModbusUnit,
    field: str,
    base_gtw26: Gtw26Factory,
):
    diematic = await base_gtw26(mock_modbus_unit)
    with pytest.raises(AttributeError):
        await diematic.sensors.write(field, 10)


@pytest.mark.parametrize(
    ("layout", "designation"),
    [
        pytest.param(RegisterLayout.BASE, "A", id="base-a"),
        pytest.param(RegisterLayout.BASE, "B", id="base-b"),
        pytest.param(RegisterLayout.ISYSTEM, "A", id="isystem-a"),
        pytest.param(RegisterLayout.ISYSTEM, "B", id="isystem-b"),
        pytest.param(RegisterLayout.ISYSTEM, "C", id="isystem-c"),
    ],
)
@pytest.mark.asyncio
async def test_holiday_heating_mode_is_read_only(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
    designation: str,
):
    boiler = await gtw26(mock_modbus_unit, layout, variant=ControllerGeneration.GENERATION_4)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(
        RemehaApiError, check=lambda e: e.translation_key == "heating_mode_read_only"
    ):
        await boiler.async_set_heating_mode(designation, HeatingMode.HOLIDAY)
    assert mock_modbus_unit.read_events == []
    assert writes == []


@pytest.mark.parametrize(
    ("layout", "designation"),
    [
        pytest.param(RegisterLayout.BASE, "A", id="base-a"),
        pytest.param(RegisterLayout.BASE, "B", id="base-b"),
        pytest.param(RegisterLayout.ISYSTEM, "A", id="isystem-a"),
        pytest.param(RegisterLayout.ISYSTEM, "B", id="isystem-b"),
        pytest.param(RegisterLayout.ISYSTEM, "C", id="isystem-c"),
    ],
)
@pytest.mark.parametrize("mode", [7, 0x58])
@pytest.mark.asyncio
async def test_unsupported_heating_mode_rejected_before_io(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
    designation: str,
    mode: int,
):
    boiler = await gtw26(mock_modbus_unit, layout, variant=ControllerGeneration.GENERATION_4)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError):
        await boiler.async_set_heating_mode(designation, mode)
    assert mock_modbus_unit.read_events == []
    assert writes == []


@pytest.mark.parametrize("layout", [RegisterLayout.BASE, RegisterLayout.ISYSTEM])
@pytest.mark.asyncio
async def test_unknown_hot_water_mode_rejected_before_io(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
):
    boiler = await gtw26(mock_modbus_unit, layout, variant=ControllerGeneration.GENERATION_4)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError):
        await boiler.async_set_hot_water_mode(64)
    assert mock_modbus_unit.read_events == []
    assert writes == []


@pytest.mark.parametrize(
    ("layout", "address"),
    [
        pytest.param(RegisterLayout.BASE, 17, id="base"),
        pytest.param(RegisterLayout.ISYSTEM, 659, id="isystem"),
    ],
)
@pytest.mark.parametrize("mode", list(HotWaterMode))
@pytest.mark.asyncio
async def test_hot_water_write_preserves_holiday(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
    address: int,
    mode: HotWaterMode,
):
    mock_modbus_unit.holding[address] = 0xA1
    boiler = await gtw26(mock_modbus_unit, layout)
    await boiler.async_set_hot_water_mode(mode)
    assert mock_modbus_unit.holding[address] == 0xA1 | int(mode)


@pytest.mark.parametrize("mode", [mode for mode in HeatingMode if mode is not HeatingMode.HOLIDAY])
@pytest.mark.asyncio
async def test_known_heating_modes_preserve_unknown_hot_water_bits(
    mock_modbus_unit: MockModbusUnit,
    mode: HeatingMode,
    isystem_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[659] = 0xC8
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.async_set_heating_mode("B", mode)
    assert mock_modbus_unit.holding[659] == 0xC0 | int(mode)


@pytest.mark.asyncio
async def test_isystem_hot_water_pump_delay_clamps_and_writes_register_61(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.hot_water.write("pump_delay", 3)
    assert mock_modbus_unit.holding[61] == 3
    await boiler.hot_water.write("pump_delay", 40)
    assert mock_modbus_unit.holding[61] == 15
    assert boiler.hot_water.pump_delay == 15


@pytest.mark.asyncio
async def test_isystem_hot_water_priority_writes_register_674(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
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
async def test_isystem_config_writes_snap_and_clamp(
    mock_modbus_unit: MockModbusUnit,
    field: str,
    value: float,
    address: int,
    raw: int,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.config.write(field, value)
    assert mock_modbus_unit.holding[address] == raw


@pytest.mark.asyncio
async def test_isystem_outdoor_antifreeze_is_read_only(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    with pytest.raises(AttributeError):
        await boiler.settings.write("outdoor_antifreeze", 5)


@pytest.mark.asyncio
async def test_isystem_config_write_rearms_cached_read(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    mock_modbus_unit.holding[298] = 300
    first = await boiler.async_update()
    assert "config" in first.updated
    assert "config" not in (await boiler.async_update()).updated

    await boiler.config.write("zone_a_min", 31.0)
    report = await boiler.async_update()
    assert "config" in report.updated
    assert boiler.config.zone_a_min == 31.0


@pytest.mark.asyncio
async def test_isystem_night_mode_and_heating_pump_delay_write(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
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
    mock_modbus_unit: MockModbusUnit,
    bundle: str,
    field: str,
    value: float,
    address: int,
    raw: int,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await getattr(boiler, bundle).write(field, value)
    assert mock_modbus_unit.holding[address] == raw


@pytest.mark.parametrize("field", ["min_running_time", "burner_temporisation", "pump_postrun"])
@pytest.mark.asyncio
async def test_isystem_psu_settings_stay_read_only(
    mock_modbus_unit: MockModbusUnit,
    field,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
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
async def test_isystem_circuit_limits_clamp(
    mock_modbus_unit: MockModbusUnit,
    circuit: str,
    field: str,
    value: float,
    address: int,
    raw: int,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones[circuit[-1].upper()].write(field, value)
    assert mock_modbus_unit.holding[address] == raw


@pytest.mark.parametrize(
    ("bundle", "field", "address"),
    [
        pytest.param("settings", "night_mode", 10, id="night_mode"),
        pytest.param("hot_water", "priority", 674, id="priority"),
        pytest.param("hot_water", "legionella_protection", 268, id="legionella_protection"),
    ],
)
@pytest.mark.asyncio
async def test_isystem_enum_writes_reject_non_members(
    mock_modbus_unit: MockModbusUnit,
    bundle: str,
    field: str,
    address: int,
    isystem_gtw26: Gtw26Factory,
):
    boiler = await isystem_gtw26(mock_modbus_unit)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(ValueError, match="is not a valid"):
        await getattr(boiler, bundle).write(field, 99)
    assert writes == []
    assert address not in mock_modbus_unit.holding


@pytest.mark.parametrize("layout", [RegisterLayout.BASE, RegisterLayout.ISYSTEM])
@pytest.mark.asyncio
async def test_unknown_zone_designation_rejected_before_io(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
):
    boiler = await gtw26(mock_modbus_unit, layout, variant=ControllerGeneration.GENERATION_4)
    writes = []
    mock_modbus_unit.on_write(writes.append)
    with pytest.raises(
        RemehaApiError, check=lambda e: e.translation_key == "unknown_zone_designation"
    ):
        await boiler.async_set_heating_mode("D", HeatingMode.AUTO)
    assert mock_modbus_unit.read_events == []
    assert writes == []


@pytest.mark.asyncio
async def test_setting_heating_mode_updates_zone_and_hot_water_cache(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[17] = 0x58
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.async_set_heating_mode("A", HeatingMode.TEMP_DAY)
    assert diematic.climate_zones["A"].mode is HeatingMode.TEMP_DAY
    assert diematic.hot_water.mode is HotWaterMode.TEMP


@pytest.mark.asyncio
async def test_setting_hot_water_mode_updates_zone_and_hot_water_cache(
    mock_modbus_unit: MockModbusUnit,
    base_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[17] = 0x58
    mock_modbus_unit.holding[26] = 0x58
    diematic = await base_gtw26(mock_modbus_unit)
    await diematic.async_set_hot_water_mode(HotWaterMode.PERM)
    assert diematic.hot_water.mode is HotWaterMode.PERM
    assert diematic.climate_zones["A"].mode is HeatingMode.AUTO
    assert diematic.climate_zones["B"].mode is HeatingMode.AUTO


@pytest.mark.asyncio
async def test_isystem_heating_mode_write_updates_zone_and_hot_water_cache(
    mock_modbus_unit: MockModbusUnit,
    isystem_gtw26: Gtw26Factory,
):
    mock_modbus_unit.holding[659] = 0xC8
    boiler = await isystem_gtw26(mock_modbus_unit)
    await boiler.async_set_heating_mode("B", HeatingMode.PERM_DAY)
    assert boiler.climate_zones["B"].mode is HeatingMode.PERM_DAY
    assert boiler.climate_zones["B"].permanent_derogation is True
    assert boiler.climate_zones["B"].derogation_until_end is False
    assert boiler.hot_water.mode == 0x40


@pytest.mark.parametrize("layout", [RegisterLayout.BASE, RegisterLayout.ISYSTEM])
@pytest.mark.asyncio
async def test_set_clock_updates_identity_cache(
    mock_modbus_unit: MockModbusUnit,
    gtw26: LayoutGtw26Factory,
    layout: RegisterLayout,
):
    boiler = await gtw26(mock_modbus_unit, layout)
    await boiler.async_set_clock(datetime(2026, 9, 4, 14, 5))
    assert boiler.identity.hour == 14
    assert boiler.identity.minute == 5
    assert boiler.identity.weekday == 5
    assert boiler.identity.day == 4
    assert boiler.identity.month == 9
    assert boiler.identity.year == 26
