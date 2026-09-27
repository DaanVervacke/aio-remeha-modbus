from datetime import time

import pytest
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw26 import (
    GTW26,
    ActiveMode,
    AuxiliaryInput,
    AuxiliaryOutputType,
    AuxiliaryType,
    CircuitType,
    HeatingMode,
    HotWaterMode,
    HotWaterPriority,
    Language,
    NightMode,
)
from aio_remeha_modbus.gtw26.const import (
    ISYSTEM_WINDOWS,
    SCHEDULE_BASES,
    ControllerGeneration,
    RegisterLayout,
)


def _seed(unit: MockModbusUnit) -> None:
    unit.holding.update(
        {
            8: 190,
            653: 0x08,
            659: 0x58,
            427: 0x38,
            457: 24,
            465: 0xFFFF,
            600: 412,
            601: 205,
            602: 650,
            603: 500,
            605: 0xFFFF,
            607: 0xFFFF,
            609: 3000,
            613: 34,
            614: 210,
            616: 0xFFFF,
            617: 0xFFFF,
            618: 225,
            620: 700,
            621: 0xFFFF,
            622: 100,
            623: 110,
            624: 120,
            662: 0xFFFF,
            663: 0xFFFF,
            650: 550,
            672: 550,
            684: 26,
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
async def test_isystem_reads_decode_across_bundles(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()

    assert boiler.sensors.outdoor_temperature == 20.5
    assert boiler.sensors.boiler_temperature == 65.0
    assert boiler.sensors.return_temperature is None
    assert boiler.sensors.fan_speed == 3000
    assert boiler.sensors.instantaneous_power == 34
    assert boiler.sensors.auxiliary_1_temperature == 10.0
    assert boiler.sensors.auxiliary_2_temperature == 11.0
    assert boiler.sensors.universal_temperature == 12.0
    assert boiler.climate_zones["A"].supply_temperature is None
    assert boiler.sensors.burner_active is True
    assert boiler.sensors.hot_water_pump_active is True
    assert boiler.sensors.fault is None

    assert boiler.hot_water.temperature == 50.0
    assert boiler.hot_water.mode is HotWaterMode.TEMP
    assert boiler.hot_water.comfort_target == 55.0
    assert boiler.hot_water.legionella_protection == 0
    assert boiler.outputs.primary == 0
    assert boiler.outputs.secondary == 0
    assert boiler.outputs.dhw_pump_active is False

    assert boiler.climate_zones["A"].mode is HeatingMode.AUTO
    assert boiler.climate_zones["A"].room_temperature == 21.0
    assert boiler.climate_zones["C"].room_temperature == 22.5

    assert boiler.identity.software_version == 412
    assert boiler.identity.controller_type == "D4"
    assert boiler.identity.year == 26


@pytest.mark.asyncio
async def test_isystem_parity_registers_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({605: 247, 654: 3, 660: 3, 662: 100, 663: 420})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.climate_zones["A"].ambient_influence == 3
    assert boiler.climate_zones["B"].ambient_influence == 3
    assert boiler.climate_zones["B"].supply_temperature == 24.7
    assert boiler.climate_zones["B"].min_temperature == 10.0
    assert boiler.climate_zones["B"].max_temperature == 42.0


@pytest.mark.asyncio
async def test_isystem_research_registers_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update(
        {
            604: 800,
            610: 8,
            661: 8,
            668: 3,
            669: 7,
            670: 100,
            671: 500,
            677: 200,
            678: 750,
        }
    )
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.sensors.flue_gas_temperature == 80.0
    assert boiler.sensors.water_pressure == 0.8
    assert boiler.climate_zones["B"].heating_curve_slope == 0.8
    assert boiler.climate_zones["C"].ambient_influence == 3
    assert boiler.climate_zones["C"].heating_curve_slope == 0.7
    assert boiler.climate_zones["C"].min_temperature == 10.0
    assert boiler.climate_zones["C"].max_temperature == 50.0
    assert boiler.settings.boiler_minimum_temperature == 20.0
    assert boiler.settings.boiler_maximum_temperature == 75.0


@pytest.mark.asyncio
async def test_isystem_b_valve_commands_decode_independently(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    circuit = boiler.climate_zones["B"]
    assert circuit.valve_opening is None
    assert circuit.valve_closing is None
    for raw, opening, closing in (
        (0x0001, False, True),
        (0x0012, True, False),
        (0x0011, False, True),
        (0xFFFC, False, False),
        (0xFFFF, True, True),
    ):
        mock_modbus_unit.holding[428] = raw
        await boiler.async_update()
        assert circuit.valve_opening is opening
        assert circuit.valve_closing is closing


@pytest.mark.asyncio
async def test_isystem_derogation_bits_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({659: 0x02 | 0x40, 667: 0x08 | 0x80})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.climate_zones["B"].mode is HeatingMode.PERM_NIGHT
    assert boiler.climate_zones["B"].permanent_derogation is True
    assert boiler.climate_zones["B"].all_circuits_derogation is False
    assert boiler.climate_zones["C"].permanent_derogation is False
    assert boiler.climate_zones["C"].all_circuits_derogation is True


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (0x04, True),
        (0x02, True),
        (0x08, False),
        (0x24, False),
        (0x22, False),
        (0x01, None),
        (0x21, None),
        (0x00, None),
        (0x06, None),
        (0xFFFF, None),
        (0x8CCC, None),
    ],
)
@pytest.mark.parametrize("other_bits", [0x00, 0x10, 0x40, 0x50, 0x80, 0xFFD0])
@pytest.mark.asyncio
async def test_permanent_derogation_uses_only_known_heating_modes(
    mock_modbus_unit, mode, expected, other_bits
):
    boiler = isystem_gtw26(mock_modbus_unit)
    for circuit, address in (
        (boiler.climate_zones["A"], 653),
        (boiler.climate_zones["B"], 659),
        (boiler.climate_zones["C"], 667),
    ):
        assert circuit.permanent_derogation is None
        mock_modbus_unit.holding[address] = mode | other_bits
        await circuit.async_update()
        assert circuit.permanent_derogation is expected
        mock_modbus_unit.holding[address] = 0x08 | other_bits
        await circuit.async_update()
        assert circuit.permanent_derogation is False


@pytest.mark.asyncio
async def test_isystem_config_and_diagnostics_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update(
        {
            263: 5,
            266: 120,
            276: 0x8010,
            289: 350,
            291: 150,
            272: 2,
            296: 1,
            297: 2,
            360: 5,
            298: 300,
            305: 5200,
            473: 1,
            644: 5,
            712: 255,
            744: 3,
            745: 1,
            746: 4,
        }
    )
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.settings.language is Language.SPANISH
    assert boiler.config.bandwidth == 12.0
    assert boiler.config.pump_postrun == 4
    assert boiler.config.zone_b_calibration == -1.6
    assert boiler.config.footprint_a_day == 35.0
    assert boiler.config.footprint_b_day is None
    assert boiler.climate_zones["A"].circuit_type is CircuitType.DIRECT
    assert boiler.climate_zones["B"].circuit_type is CircuitType.THREE_WAY_VALVE
    assert boiler.climate_zones["C"].circuit_type is CircuitType.SWIMMING_POOL
    assert boiler.config.zone_a_min == 30.0
    assert boiler.config.max_fan_speed == 5200
    assert boiler.config.modulated_power == 1
    assert boiler.diagnostics.boiler_active_mode == 5
    assert boiler.diagnostics.pcu_block == 255
    assert boiler.diagnostics.auxiliary_1_type is AuxiliaryType.DHW_LOAD
    assert boiler.diagnostics.auxiliary_2_type is AuxiliaryOutputType.VM_PUMP
    assert boiler.diagnostics.auxiliary_3_type is AuxiliaryOutputType.FAILURE


@pytest.mark.asyncio
async def test_isystem_config_sentinels_decode_as_missing_values(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({282: 101, 289: 150})
    boiler = isystem_gtw26(mock_modbus_unit)

    await boiler.async_update()

    assert boiler.config.anticipation_a is None
    assert boiler.config.footprint_a_day is None


@pytest.mark.asyncio
async def test_isystem_unknown_fault_and_diagnostics_values_stay_raw(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update(
        {
            465: 0x7777,
            641: 0x07,
            644: 0xFFFF,
            710: 0x8CCC,
            712: 0x1234,
        }
    )
    boiler = isystem_gtw26(mock_modbus_unit)

    await boiler.async_update()

    assert boiler.sensors.fault == 0x7777
    assert boiler.diagnostics.aux_active_mode == 6
    assert boiler.diagnostics.boiler_active_mode == 0xFFFF
    assert boiler.diagnostics.pcu_state == 0x8CCC
    assert boiler.diagnostics.pcu_block == 0x1234


@pytest.mark.asyncio
async def test_isystem_outputs_decode_documented_secondary_bits(mock_modbus_unit):
    mock_modbus_unit.holding.update({474: 0x8000, 475: 0x2001, 735: 0x4000})
    boiler = isystem_gtw26(mock_modbus_unit)

    await boiler.async_update()

    assert boiler.outputs.primary == 0x8000
    assert boiler.outputs.secondary == 0x2001
    assert boiler.outputs.dhw_pump_active is True
    assert boiler.outputs.circuit_a_pump_active is False
    assert boiler.outputs.phone_output_active is True
    assert boiler.outputs.boiler_state == 0x4000


@pytest.mark.asyncio
async def test_isystem_dhw_priority_decodes(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({674: 1})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.diagnostics.dhw_priority is HotWaterPriority.SLIDING
    mock_modbus_unit.holding.update({674: 9})
    await boiler.async_update()
    assert boiler.diagnostics.dhw_priority == 9


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0x08, False), (0x24, True), (0x04, False), (0x01, None)],
)
@pytest.mark.asyncio
async def test_isystem_derogation_until_end_decodes(mock_modbus_unit, raw, expected):
    boiler = isystem_gtw26(mock_modbus_unit)
    mock_modbus_unit.holding[659] = raw
    await boiler.climate_zones["B"].async_update()
    assert boiler.climate_zones["B"].derogation_until_end is expected


@pytest.mark.asyncio
async def test_isystem_active_mode_decodes(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({637: 0, 638: 4, 639: 4, 640: 2, 641: 0})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.climate_zones["A"].active_mode is ActiveMode.ANTIFREEZE
    assert boiler.climate_zones["B"].active_mode is ActiveMode.DAY
    assert boiler.climate_zones["C"].active_mode is ActiveMode.DAY
    assert boiler.hot_water.active_mode is ActiveMode.NIGHT
    assert boiler.diagnostics.aux_active_mode is ActiveMode.ANTIFREEZE


@pytest.mark.asyncio
async def test_isystem_circuit_presence_follows_room_temp(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.zone_a_present is True
    assert boiler.zone_b_present is False
    assert boiler.zone_c_present is True


@pytest.mark.asyncio
async def test_isystem_hot_water_presence_follows_temperature(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.hot_water_present is True

    mock_modbus_unit.holding[603] = 0xFFFF
    await boiler.async_update()
    assert boiler.hot_water_present is False


@pytest.mark.asyncio
async def test_isystem_hot_water_zero_temperature_counts_as_present(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[603] = 0
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.hot_water_present is True


@pytest.mark.asyncio
async def test_isystem_heating_mode_writes_to_zone_b_register(mock_modbus_unit):
    mock_modbus_unit.holding[659] = 0x58
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.set_heating_mode("B", HeatingMode.TEMP_NIGHT)
    word = mock_modbus_unit.holding[659]
    assert word & 0x2F == int(HeatingMode.TEMP_NIGHT)
    assert word & 0x50 == int(HotWaterMode.TEMP)
    assert 17 not in mock_modbus_unit.holding
    assert 26 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_isystem_hot_water_mode_writes_to_zone_b_register(mock_modbus_unit):
    mock_modbus_unit.holding[659] = 0x08
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.set_hot_water_mode(HotWaterMode.PERM)
    word = mock_modbus_unit.holding[659]
    assert word & 0x50 == int(HotWaterMode.PERM)
    assert word & 0x2F == int(HeatingMode.AUTO)


@pytest.mark.asyncio
async def test_isystem_circuit_c_mode_writes_to_667(mock_modbus_unit):
    mock_modbus_unit.holding[667] = 0x08
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.set_heating_mode("C", HeatingMode.TEMP_DAY)
    assert mock_modbus_unit.holding[667] & 0x2F == int(HeatingMode.TEMP_DAY)


@pytest.mark.asyncio
async def test_isystem_mode_write_does_not_nudge_panel(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)
    await boiler.set_heating_mode("B", HeatingMode.AUTO)
    assert 13 not in mock_modbus_unit.holding


@pytest.mark.asyncio
async def test_isystem_setpoint_snaps_and_writes(mock_modbus_unit):
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.climate_zones["A"].write("comfort_target", 20.3)
    assert mock_modbus_unit.holding[650] == 205


@pytest.mark.asyncio
async def test_isystem_schedule_decodes_comfort_ranges(mock_modbus_unit):
    mock_modbus_unit.holding.update(
        {
            126: 0x000F,
            127: 0x8000,
            128: 0,
            131: 0x000F,
            147: 0x0003,
            148: 0xFFFF,
            149: 0xFF00,
            189: 0x03FF,
            190: 0xC180,
            191: 0xFFF8,
            210: 0x000F,
            211: 0xFFFF,
            212: 0xFFF0,
        }
    )
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    week = boiler.schedule.get_week("circuit_a_p4")
    assert week[1] == [(time(6, 0), time(8, 30))]
    assert week[2] == [(time(22, 0), time(0, 0))]
    assert week[3] == []
    assert boiler.schedule.get_week("circuit_b_p4")[1] == [(time(7, 0), time(20, 0))]
    assert boiler.schedule.get_week("hot_water")[1] == [
        (time(3, 0), time(9, 0)),
        (time(11, 30), time(12, 30)),
        (time(16, 0), time(22, 30)),
    ]
    assert boiler.schedule.get_week("auxiliary")[1] == [(time(6, 0), time(22, 0))]
    assert boiler.schedule.get_week("circuit_c_p4")[7] == []


@pytest.mark.parametrize("schedule, base", SCHEDULE_BASES.items())
@pytest.mark.asyncio
async def test_isystem_schedule_decodes_all_on_and_all_off_days(mock_modbus_unit, schedule, base):
    mock_modbus_unit.holding.update(
        {
            base: 0xFFFF,
            base + 1: 0xFFFF,
            base + 2: 0xFFFF,
            base + 3: 0,
            base + 4: 0,
            base + 5: 0,
        }
    )
    boiler = isystem_gtw26(mock_modbus_unit)

    await boiler.schedule.async_update(schedule)

    assert boiler.schedule.get_week(schedule) == {
        1: [(time(0, 0), time(0, 0))],
        2: [],
        3: [],
        4: [],
        5: [],
        6: [],
        7: [],
    }
    assert boiler.schedule.get_day(schedule, 1) == [(time(0, 0), time(0, 0))]
    assert boiler.schedule.get_day(schedule, 2) == []


@pytest.mark.parametrize("schedule, base", SCHEDULE_BASES.items())
@pytest.mark.asyncio
async def test_isystem_schedule_decodes_adjacent_days_independently(
    mock_modbus_unit, schedule, base
):
    mock_modbus_unit.holding.update(
        {
            base: 0x8000,
            base + 1: 0,
            base + 2: 0,
            base + 3: 0x4000,
            base + 4: 0,
            base + 5: 0,
        }
    )
    boiler = isystem_gtw26(mock_modbus_unit)

    await boiler.schedule.async_update(schedule)

    week = boiler.schedule.get_week(schedule)
    assert week[1] == [(time(0, 0), time(0, 30))]
    assert week[2] == [(time(0, 30), time(1, 0))]
    assert all(not week[day] for day in range(3, 8))


@pytest.mark.asyncio
async def test_isystem_schedule_reads_one_day_per_request(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()

    blocks = [
        (event.address, event.count)
        for event in mock_modbus_unit.read_events
        if event.register_type == "holding"
    ]
    for base in SCHEDULE_BASES.values():
        assert all(blocks.count((base + 3 * day, 3)) == 1 for day in range(7))


@pytest.mark.asyncio
async def test_isystem_set_day_refreshes_cached_schedule(mock_modbus_unit):
    mock_modbus_unit.holding.update({147: 0x0000, 148: 0xC000, 149: 0x0000})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.schedule.get_week("circuit_b_p4")[1] == [(time(8, 0), time(9, 0))]

    await boiler.schedule.set_day("circuit_b_p4", 1, [(time(10, 0), time(11, 0))])
    await boiler.async_update()

    assert boiler.schedule.get_week("circuit_b_p4")[1] == [(time(10, 0), time(11, 0))]


@pytest.mark.asyncio
async def test_isystem_pooled_and_read_once_reads_stay_inside_windows(
    mock_modbus_unit,
):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()

    schedule_days = {(base + 3 * day, 3) for base in SCHEDULE_BASES.values() for day in range(7)}
    blocks = [
        (event.address, event.count)
        for event in mock_modbus_unit.read_events
        if event.register_type == "holding" and (event.address, event.count) not in schedule_days
    ]
    assert blocks
    for start, count in blocks:
        end = start + count - 1
        assert any(
            window_start <= start and end <= window_end
            for window_start, window_end in ISYSTEM_WINDOWS
        )


@pytest.mark.asyncio
async def test_isystem_each_window_read_without_crossing_gaps(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()

    schedule_days = {(base + 3 * day, 3) for base in SCHEDULE_BASES.values() for day in range(7)}
    blocks = [
        (event.address, event.count)
        for event in mock_modbus_unit.read_events
        if event.register_type == "holding" and (event.address, event.count) not in schedule_days
    ]
    assert blocks
    for start, count in blocks:
        end = start + count - 1
        assert (
            sum(
                window_start <= start and end <= window_end
                for window_start, window_end in ISYSTEM_WINDOWS
            )
            == 1
        )
    for window_start, window_end in ISYSTEM_WINDOWS:
        assert any(
            window_start <= start and end <= window_end
            for start, count in blocks
            for end in (start + count - 1,)
        )


@pytest.mark.asyncio
async def test_isystem_group_planning_uses_declared_windows(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    for component in (
        boiler.sensors,
        boiler.hot_water,
        boiler.climate_zones["A"],
        boiler.climate_zones["B"],
        boiler.climate_zones["C"],
        boiler.settings,
        boiler.config,
        boiler.diagnostics,
        boiler.identity,
    ):
        assert component.register_ranges == ISYSTEM_WINDOWS
        assert component._resolved_ranges().for_space("holding") == ISYSTEM_WINDOWS
    assert boiler._poll_group._ranges.for_space("holding") == ISYSTEM_WINDOWS


@pytest.mark.parametrize("schedule, base", SCHEDULE_BASES.items())
@pytest.mark.asyncio
async def test_isystem_schedule_reads_all_days_as_three_register_blocks(
    mock_modbus_unit, schedule, base
):
    boiler = isystem_gtw26(mock_modbus_unit)
    mock_modbus_unit.read_events.clear()

    await boiler.schedule.async_update(schedule)

    assert [(event.address, event.count) for event in mock_modbus_unit.read_events] == [
        (base + 3 * day, 3) for day in range(7)
    ]


@pytest.mark.asyncio
async def test_isystem_decodes_selected_program(mock_modbus_unit):
    mock_modbus_unit.holding.update({231: 0x2000, 232: 0x2023, 233: 0x2038})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.climate_zones["A"].program == 1
    assert boiler.climate_zones["B"].program == 2
    assert boiler.climate_zones["C"].program == 1

    mock_modbus_unit.holding.update({231: 0x2015, 232: 0x2007, 233: 0xFFFF})
    await boiler.async_update()
    assert boiler.climate_zones["A"].program == 4
    assert boiler.climate_zones["B"].program == 2
    assert boiler.climate_zones["C"].program is None


@pytest.mark.asyncio
async def test_isystem_read_raw_covers_schedule_blocks(mock_modbus_unit):
    expected = {231: 0x2000, 232: 0x2023, 233: 0x2038}
    for base in SCHEDULE_BASES.values():
        expected.update({base + offset: base + offset for offset in range(21)})
    mock_modbus_unit.holding.update(expected)
    boiler = isystem_gtw26(mock_modbus_unit)

    raw = await boiler.async_read_all_raw()

    assert raw["holding"].items() >= expected.items()


@pytest.mark.asyncio
async def test_isystem_read_raw_refreshes_decoded_cache(mock_modbus_unit):
    _seed(mock_modbus_unit)
    boiler = isystem_gtw26(mock_modbus_unit)
    assert boiler.sensors.boiler_temperature is None

    await boiler.async_read_all_raw()

    assert boiler.sensors.boiler_temperature == 65.0


@pytest.mark.asyncio
async def test_isystem_counters_and_outdoor_settings_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({9: 0x8032, 61: 2, 102: 196, 251: 0x2B30, 252: 0x7272})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.sensors.burner_start_count == 44224
    assert boiler.sensors.burner_runtime_hours == 29298
    assert boiler.sensors.mean_outside_temperature == 19.6
    assert boiler.settings.outdoor_antifreeze == -5.0
    assert boiler.hot_water.pump_delay == 2


@pytest.mark.asyncio
async def test_isystem_absent_counters_decode_as_none(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({251: 0xFFFF, 252: 0xFFFF})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.sensors.burner_start_count is None
    assert boiler.sensors.burner_runtime_hours is None


@pytest.mark.asyncio
async def test_isystem_output_bits_and_secondary_setpoint_decode(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding.update({474: 0x0019, 734: 0x01CC, 735: 0x0008, 10: 1})
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.outputs.burner_stage_1_active is True
    assert boiler.outputs.hydraulic_valve_closing is True
    assert boiler.outputs.boiler_pump_active is True
    assert boiler.outputs.secondary_pump_active is True
    assert boiler.sensors.secondary_calculated_temperature == 46.0
    assert boiler.settings.night_mode is NightMode.DECREASE


@pytest.mark.asyncio
async def test_isystem_auxiliary_input_decodes(mock_modbus_unit):
    _seed(mock_modbus_unit)
    mock_modbus_unit.holding[741] = 0
    boiler = isystem_gtw26(mock_modbus_unit)
    await boiler.async_update()
    assert boiler.diagnostics.auxiliary_1_input is AuxiliaryInput.DISABLED
