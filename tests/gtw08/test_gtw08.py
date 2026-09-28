"""Tests for the GTW08 device."""

import struct
from datetime import time

import pytest
from dateutil import tz
from modbus_connection import GatewayPathUnavailableError, ServerDeviceBusyError
from modbus_connection.exceptions import IllegalFunctionError
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw08 import GTW08
from aio_remeha_modbus.gtw08.appliance import (
    Appliance,
    CoolingType,
    SilentMode,
)
from aio_remeha_modbus.gtw08.climate_zone import (
    ClimateZone,
    ClimateZoneFunction,
    ClimateZoneHeatingMode,
    ClimateZoneMode,
    ClimateZoneScheduleId,
    ClimateZoneType,
)
from aio_remeha_modbus.gtw08.const import (
    REMEHA_MAX_SPAN,
    REMEHA_ZONE_RESERVED_REGISTERS,
    Weekday,
)
from aio_remeha_modbus.gtw08.errors import RemehaModbusError
from aio_remeha_modbus.gtw08.gtw08 import DetectionFailureReason
from aio_remeha_modbus.gtw08.main_control_monitoring import ApplianceErrorPriority, MonitoringStatus
from aio_remeha_modbus.gtw08.schedule import (
    Timeslot,
    TimeslotActivity,
    TimeslotSetpointType,
)
from aio_remeha_modbus.gtw08.system_discovery_table import DeviceBoardType
from aio_remeha_modbus.helpers.fields import decode_bytes


@pytest.mark.asyncio
async def test_read_single_variable(gtw_08: GTW08):
    """Test that the API can be created and a single register be read."""

    assert len(gtw_08.discovery_table.device_boards) == 2


@pytest.mark.asyncio
async def test_read_device_instance(gtw_08: GTW08):
    """Test that a device can be read through the modbus interface."""

    device_board = gtw_08.discovery_table.device_boards[0]

    assert device_board is not None
    assert device_board.id == 0
    assert device_board.hardware_version == (2, 1)
    assert device_board.config_table_version == (1, 2)
    assert device_board.software_version == (1, 1)
    assert str(device_board.board_category) == "EHC-10"
    assert device_board.article_number == 7853960


@pytest.mark.asyncio
async def test_read_zone(gtw_08: GTW08):
    """Read a single zone."""

    zone: ClimateZone | None = gtw_08.zones[0]

    assert zone is not None
    assert zone.current_setpoint == 20.0
    assert zone.current_temparature == 23.2
    assert zone.dhw_calorifier_hysteresis is None
    assert zone.dhw_comfort_setpoint is None
    assert zone.dhw_reduced_setpoint is None
    assert zone.dhw_tank_temperature is None
    assert zone.flow_temperature == 25.0
    assert zone.function == ClimateZoneFunction.MIXING_CIRCUIT
    assert zone.heating_curve_slope == 0.5
    assert zone.heating_curve_base_comfort == 20.0
    assert zone.heating_curve_base_reduced == 17.0
    assert zone.heating_mode == ClimateZoneHeatingMode.COOLING
    assert zone.id == 1
    assert zone.mode == ClimateZoneMode.MANUAL
    assert zone.owning_device == 1
    assert zone.pump_running is True
    assert zone.room_manual_setpoint == 20.0
    assert zone.room_temperature == 23.2
    assert zone.selected_schedule is ClimateZoneScheduleId.SCHEDULE_1
    assert zone.short_name == "CIRCA1"
    assert zone.type == ClimateZoneType.OTHER

    assert zone.is_central_heating() is True
    assert zone.is_domestic_hot_water() is False


@pytest.mark.asyncio
async def test_read_zone_update(gtw_08: GTW08):
    """Read a zone update from the modbus device."""

    # Read a single zone
    zone: ClimateZone | None = gtw_08.zones[0]
    assert zone is not None
    assert zone.is_central_heating()
    assert zone.mode == ClimateZoneMode.MANUAL
    current_setpoint = zone.current_setpoint
    assert current_setpoint is not None

    # Update a variable directly at the modbus interface
    new_setpoint: float = current_setpoint + 2
    await zone.async_set_current_setpoint(new_setpoint)

    # Retrieve the updated value
    await zone.async_update()

    # Validate updated setpoint
    assert zone.current_setpoint == new_setpoint


@pytest.mark.asyncio
async def test_health_check(mock_modbus_unit: MockModbusUnit):
    """Test a health check can be run without raising an exception."""

    await GTW08.async_health_check(mock_modbus_unit)


@pytest.mark.asyncio
async def test_read_appliance(gtw_08: GTW08):
    """Test that the API can read the appliance status from the modbus device."""

    appliance: Appliance = gtw_08.appliance
    ctrl_monitoring = gtw_08.main_control_monitoring
    assert ctrl_monitoring.current_error == int("0223", 16)  # H02.23 Flow rate error.
    assert ctrl_monitoring.error_priority == ApplianceErrorPriority.BLOCKING
    assert appliance.ch_enabled
    assert appliance.cooling_type is CoolingType.ACTIVE_COOLING
    assert appliance.summer_winter == 22.0
    assert appliance.silent_mode == SilentMode.LEVEL_1
    assert appliance.silent_mode_start_time == time(hour=22)
    assert appliance.silent_mode_end_time == time(hour=7)

    assert ctrl_monitoring.monitoring_status is not None
    status: MonitoringStatus = ctrl_monitoring.monitoring_status

    assert (
        status
        == MonitoringStatus.SERVICE_REQUIRED
        | MonitoringStatus.WATER_PRESSURE_LOW
        | MonitoringStatus.APPLIANCE_PUMP_ON
        | MonitoringStatus.COOLING_ACTIVE
    )


@pytest.mark.asyncio
async def test_read_registers(gtw_08: GTW08):
    """Test that the api can read an arbitrary set of registers."""

    assert await gtw_08.async_read_registers(address=130, count=4, struct_format=">HHHH") == (
        0x0101,
        0x0102,
        0x0201,
        0x0077,
    )


@pytest.mark.asyncio
async def test_read_too_many_registers(gtw_08: GTW08):
    """Test that the api doesn't allow reading a register count exceeding REMEHA_MAX_SPAN."""

    count = REMEHA_MAX_SPAN + 1
    with pytest.raises(
        ValueError, match=f"Illegal count {count}: must be between 1 and {REMEHA_MAX_SPAN}."
    ):
        assert await gtw_08.async_read_registers(address=649, count=count)


@pytest.mark.asyncio
async def test_overwrite_zone_schdule(gtw_08: GTW08):
    """Test that the API can overwrite a single ZoneSchedule."""

    expected: bytes = bytes.fromhex("05 c81024 c8302a c82036 c84060 c80087 0000 0000")
    time_slots = [
        Timeslot(
            setpoint_type=TimeslotSetpointType.COMFORT,
            activity=TimeslotActivity.HEAT_COOL,
            switch_time=time(6, 0, 0),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.MORNING,
            activity=TimeslotActivity.HEAT_COOL,
            switch_time=time(7, 0, 0),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.AWAY,
            activity=TimeslotActivity.HEAT_COOL,
            switch_time=time(9, 0, 0),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.EVENING,
            activity=TimeslotActivity.HEAT_COOL,
            switch_time=time(16, 0, 0),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=TimeslotActivity.HEAT_COOL,
            switch_time=time(22, 30, 0),
        ),
    ]

    registers: list[int] = list(
        await gtw_08.async_read_registers(899, count=10, struct_format=">HHHHHHHHHH")
    )
    encoded_bytes = decode_bytes(registers)

    # Ensure the current schedule is different.
    assert encoded_bytes != expected

    # Overwrite the new schedule
    # TODO await gtw_08.async_overwrite_zone_schedule(schedule)
    current_schedule = gtw_08.zones[0].current_schedule
    current_schedule[Weekday.MONDAY] = time_slots
    await gtw_08.zones[0].async_set_current_schedule(
        ClimateZoneScheduleId.SCHEDULE_4, current_schedule
    )

    # Re-read the registers and verify
    registers = list(await gtw_08.async_read_registers(899, count=10, struct_format=">HHHHHHHHHH"))
    assert decode_bytes(registers) == expected


@pytest.mark.asyncio
async def test_health_check_failure(mock_modbus_unit: MockModbusUnit):
    """Test that a failing health check is reported as a `RemehaModbusError`."""

    mock_modbus_unit.fail_requests(IllegalFunctionError(exception_code=0x01))

    with pytest.raises(RemehaModbusError) as exc_info:
        await GTW08.async_health_check(mock_modbus_unit)

    assert exc_info.value.translation_key == "health_check_failed"
    assert isinstance(exc_info.value.__cause__, IllegalFunctionError)


@pytest.mark.asyncio
async def test_unit_settings(remeha_modbus_unit: MockModbusUnit):
    """Test that message spacing and request timeout are set on the unit."""

    GTW08(name="test", unit=remeha_modbus_unit)
    assert remeha_modbus_unit.message_spacing == 0.00175
    assert remeha_modbus_unit.required_timeout == 0.003

    GTW08(name="test", unit=remeha_modbus_unit, message_spacing_seconds=0.5, request_timeout=2.0)
    assert remeha_modbus_unit.message_spacing == 0.5
    assert remeha_modbus_unit.required_timeout == 2.0


@pytest.mark.asyncio
@pytest.mark.parametrize("gtw_08", [{"name": "custom", "require_update": False}], indirect=True)
async def test_name(gtw_08: GTW08):
    """Test that the name is the one given on creation."""

    assert gtw_08.name == "custom"


@pytest.mark.asyncio
async def test_default_time_zone(remeha_modbus_unit: MockModbusUnit):
    """Test that the api can be used without an explicit time zone."""

    api = GTW08(name="test", unit=remeha_modbus_unit)
    await api.async_update()

    assert len(api.zones) == 2


@pytest.mark.asyncio
async def test_time_zone_is_passed_to_zones(remeha_modbus_unit: MockModbusUnit):
    """Test that the time zone is passed to the climate zones."""

    time_zone = tz.gettz("Europe/Amsterdam")
    api = GTW08(name="test", unit=remeha_modbus_unit, time_zone=time_zone)
    await api.async_update()

    assert all(zone.time_zone is time_zone for zone in api.zones)


@pytest.mark.asyncio
async def test_disabled_zone_is_skipped(remeha_modbus_unit: MockModbusUnit):
    """Test that a disabled zone is not read and not part of the zones."""

    # The second zone is the DHW zone, disable it.
    remeha_modbus_unit.holding[641 + REMEHA_ZONE_RESERVED_REGISTERS] = (
        ClimateZoneFunction.DISABLED.value
    )

    api = GTW08(name="test", unit=remeha_modbus_unit)
    await api.async_update()

    assert len(api.zones) == 1
    assert api.zones[0].id == 1
    assert api.zones[0].function == ClimateZoneFunction.MIXING_CIRCUIT


@pytest.mark.asyncio
async def test_update_readings(gtw_08: GTW08):
    """Test that updating readings does not poll the discovery table."""

    unit = gtw_08._unit  # noqa: SLF001
    assert isinstance(unit, MockModbusUnit)
    unit.read_events.clear()

    report = await gtw_08.async_update_readings()

    assert report is not None
    assert unit.read_events
    assert all(not (128 <= event.address <= 200) for event in unit.read_events)


@pytest.mark.asyncio
async def test_update_settings(gtw_08: GTW08):
    """Test that updating settings only polls the discovery table."""

    unit = gtw_08._unit  # noqa: SLF001
    assert isinstance(unit, MockModbusUnit)
    unit.read_events.clear()
    unit.holding[189] = 0x0002

    await gtw_08.async_update_settings()

    assert unit.read_events
    assert all(128 <= event.address <= 200 for event in unit.read_events)


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1])
async def test_read_too_few_registers(gtw_08: GTW08, count: int):
    """Test that the api doesn't allow reading less than one register."""

    with pytest.raises(ValueError, match=f"Illegal count {count}: must be between 1 and"):
        await gtw_08.async_read_registers(address=130, count=count)


@pytest.mark.asyncio
async def test_read_registers_default_format(gtw_08: GTW08):
    """Test that a single register is read as an unsigned short by default."""

    assert await gtw_08.async_read_registers(address=130) == (
        struct.unpack("=H", (0x0101).to_bytes(2, "big"))[0],
    )


@pytest.mark.asyncio
async def test_read_registers_invalid_format(gtw_08: GTW08):
    """Test that an illegal struct format is reported as a `struct.error`."""

    with pytest.raises(struct.error):
        await gtw_08.async_read_registers(address=130, count=1, struct_format=">HH")


@pytest.mark.asyncio
@pytest.mark.parametrize("remeha_modbus_unit", ["system_discovery_table_ok.json"], indirect=True)
async def test_detection_successful(remeha_modbus_unit):
    """Test that a successful detection returns the correct main board."""

    detection = await GTW08.async_detect(remeha_modbus_unit)
    assert detection.success is True
    assert detection.failure_reason is None

    device = detection.main_board
    assert device is not None
    assert device.is_mainboard()

    board_category = device.board_category
    assert board_category is not None
    assert board_category.type is DeviceBoardType.EHC
    assert board_category.generation == 10


@pytest.mark.asyncio
@pytest.mark.parametrize("remeha_modbus_unit", ["system_discovery_table_ok.json"], indirect=True)
async def test_detection_raises_on_transient(remeha_modbus_unit: MockModbusUnit):
    """Test that a detection attempts on a transient modbus error."""

    # Set up the failure mode
    remeha_modbus_unit.fail_read(130, ServerDeviceBusyError())

    with pytest.raises(ServerDeviceBusyError):
        await GTW08.async_detect(remeha_modbus_unit)


@pytest.mark.asyncio
@pytest.mark.parametrize("remeha_modbus_unit", ["system_discovery_table_ok.json"], indirect=True)
async def test_detection_failure_not_a_gtw08(remeha_modbus_unit: MockModbusUnit):
    """Test that a detection attempts on a transient modbus error."""

    # Set up the failure mode. A modbus that is not a GTW-08 might
    # not serve the requested address.
    remeha_modbus_unit.fail_read(130, GatewayPathUnavailableError())

    detection = await GTW08.async_detect(remeha_modbus_unit)
    assert detection.success is False
    assert detection.failure_reason is DetectionFailureReason.NOT_A_GTW08


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remeha_modbus_unit", ["system_discovery_table_no_main_board.json"], indirect=True
)
async def test_detection_no_main_board(remeha_modbus_unit):
    """Test that detection fails with the correct reason if the system discovvery table contains no main board."""

    detection = await GTW08.async_detect(remeha_modbus_unit)
    assert detection.success is False
    assert detection.failure_reason is DetectionFailureReason.NO_MAINBOARD


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remeha_modbus_unit", ["system_discovery_table_no_gateway.json"], indirect=True
)
async def test_detection_no_gateway(remeha_modbus_unit):
    """Test that detection fails with the correct reason if the system discovvery table contains no gateway."""

    detection = await GTW08.async_detect(remeha_modbus_unit)
    assert detection.success is False
    assert detection.failure_reason is DetectionFailureReason.NO_GATEWAY
