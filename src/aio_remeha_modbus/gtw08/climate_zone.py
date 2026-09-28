"""Implementation of climate zones within the Remeha Modbus integration."""

import logging
from collections.abc import Callable
from datetime import datetime, tzinfo
from enum import IntEnum
from typing import TYPE_CHECKING, Any, cast

from dateutil import relativedelta
from modbus_connection import ModbusUnit
from modbus_connection.model import boolean, enum, repeating_group, string

from aio_remeha_modbus.gtw08.const import (
    REMEHA_DAY_SCHEDULE_RESERVED_REGISTERS,
    REMEHA_MAX_SPAN,
    REMEHA_TIME_PROGRAM_RESERVED_REGISTERS,
    REMEHA_ZONE_RESERVED_REGISTERS,
    ClimateZoneScheduleId,
    Limits,
    Weekday,
)
from aio_remeha_modbus.gtw08.errors import RemehaApiError
from aio_remeha_modbus.gtw08.model import RemehaComponent
from aio_remeha_modbus.gtw08.time_program import DaySchedule, TimeProgram, TimeslotSetpointType
from aio_remeha_modbus.helpers.fields import int16, nullable_binary, uint8, uint16
from aio_remeha_modbus.helpers.gtw08 import (
    TimeOfDay,
    get_current_timeslot,
)
from aio_remeha_modbus.helpers.validation import in_range

if TYPE_CHECKING:
    from aio_remeha_modbus.helpers.gtw08 import Timeslot

_LOGGER = logging.getLogger(__name__)


class ClimateZoneType(IntEnum):
    """Enumerates the available zone types."""

    NOT_PRESENT = 0
    CH_ONLY = 1
    CH_AND_COOLING = 2
    DHW = 3
    PROCESS_HEAT = 4
    SWIMMING_POOL = 5
    OTHER = 254


class ClimateZoneFunction(IntEnum):
    """Enumerates the available zone functions."""

    DISABLED = 0
    DIRECT = 1
    MIXING_CIRCUIT = 2
    SWIMMING_POOL = 3
    HIGH_TEMPERATURE = 4
    FAN_CONVECTOR = 5
    DHW_TANK = 6
    ELECTRICAL_DHW_TANK = 7
    TIME_PROGRAM = 8
    PROCESS_HEAT = 9
    DHW_LAYERED = 10
    DHW_BIC = 11
    DHW_COMMERCIAL_TANK = 12
    DHW_PRIMARY = 254

    def is_supported(self) -> bool:
        """Return whether this `ClimateZoneFunction` is currently supported within this integration."""
        return self in {
            ClimateZoneFunction.MIXING_CIRCUIT,
            ClimateZoneFunction.DHW_PRIMARY,
        }

    def has_cooling_capability(self) -> bool:
        """Return whether this `ClimateZoneFunction` supports cooling."""
        return self in {
            ClimateZoneFunction.MIXING_CIRCUIT,
            ClimateZoneFunction.FAN_CONVECTOR,
        }


class ClimateZoneMode(IntEnum):
    """Enumerates the modes a zone can be in."""

    SCHEDULING = 0
    MANUAL = 1
    ANTI_FROST = 2


class ClimateZoneHeatingMode(IntEnum):
    """The mode the zone is currently functioning in."""

    STANDBY = 0
    HEATING = 1
    COOLING = 2


def _writable_schedule_id() -> Callable[[Any], Any]:
    """Validate the given `ClimateZoneScheduleId` for writing."""

    def _validate(value: ClimateZoneScheduleId):
        if value == ClimateZoneScheduleId.SCHEDULE_4:
            raise TypeError(f"Schedule {ClimateZoneScheduleId.SCHEDULE_4.name} is not writable")

        return value

    return _validate


def _map_selected_schedule_for_read(
    zone_mode: ClimateZoneMode,
    zone_function: ClimateZoneFunction,
    appliance_requires_cooling: bool,
    selected_schedule: int | None,
) -> ClimateZoneScheduleId | None:
    """Map `selected_schedule` to the correct `ClimateZoneScheduleId` for reading.

    Remeha stores the cooling schedule in schedule 4, but writing that to
    `selected_schedule` raises an exception since it only allows the values
    of schedule 1 through 3.
    """
    return (
        ClimateZoneScheduleId.SCHEDULE_4
        if zone_mode is ClimateZoneMode.SCHEDULING
        and zone_function.has_cooling_capability()
        and appliance_requires_cooling
        else (ClimateZoneScheduleId(selected_schedule) if selected_schedule is not None else None)
    )


def _map_selected_schedule_for_write(
    selected_schedule: ClimateZoneScheduleId,
) -> ClimateZoneScheduleId:
    """Map `selected_schedule` to the correct `ClimateZoneScheduleId` for writing.

    Remeha stores the cooling schedule in schedule 4, but writing that to
    `selected_schedule` raises an exception since it only allows the values
    of schedule 1 through 3.
    """
    return (
        ClimateZoneScheduleId.SCHEDULE_1
        if selected_schedule is ClimateZoneScheduleId.SCHEDULE_4
        else selected_schedule
    )


def _time_program_start_address(
    zone_id: int = 1, schedule_id: ClimateZoneScheduleId = ClimateZoneScheduleId.SCHEDULE_1
) -> int:
    return (
        zone_id - 1
    ) * REMEHA_ZONE_RESERVED_REGISTERS + schedule_id * REMEHA_TIME_PROGRAM_RESERVED_REGISTERS


def is_domestic_hot_water(type: ClimateZoneType, function: ClimateZoneFunction) -> bool:
    """Return whether the given type and function resolve to a DHW zone type."""

    return type == ClimateZoneType.DHW or (
        type == ClimateZoneType.OTHER
        and function
        in {
            ClimateZoneFunction.DHW_BIC,
            ClimateZoneFunction.DHW_COMMERCIAL_TANK,
            ClimateZoneFunction.DHW_LAYERED,
            ClimateZoneFunction.DHW_PRIMARY,
            ClimateZoneFunction.DHW_TANK,
            ClimateZoneFunction.ELECTRICAL_DHW_TANK,
        }
    )


def is_central_heating(type: ClimateZoneType, function: ClimateZoneFunction) -> bool:
    """Return whether the given type and function resolve to a CH zone type.

    This method is meant to be used by the API, in situations where no `ClimateZone`
    is available (yet).
    """

    return type in {
        ClimateZoneType.CH_ONLY,
        ClimateZoneType.CH_AND_COOLING,
    } or (type == ClimateZoneType.OTHER and function == ClimateZoneFunction.MIXING_CIRCUIT)


class ClimateZone(RemehaComponent):  # ruff: ignore[too-many-public-methods]
    """Defines a climate zone following the GTW-08 parameter list.

    In the GTW-08 parameter list, a climate zone contains all fields for all zone types.
    The API must stay as close as possible to the original mapping and therefore a
    `ClimateZone` does not differentiate between zone types.
    However, the entities created from `ClimateZone` instances have distinct types for all supported zone types.
    """

    max_span = REMEHA_MAX_SPAN
    register_ranges = ((640, 646), (648, 980), (1100, 1120))

    type = enum(address=640, enum_type=ClimateZoneType, nan=0xFF)
    """The type of climate zone"""

    function = enum(address=641, enum_type=ClimateZoneFunction, nan=0xFF)
    """The climate zone function"""

    short_name = string(address=642, length=3)
    """The climate zone short name"""

    owning_device = uint8(address=646)
    """The id of the device owning the zone."""

    mode = enum(address=649, enum_type=ClimateZoneMode, nan=0xFF, writable=True)
    """The current mode the zone is in."""

    room_setpoint_1 = uint16(address=650, scale=0.1, writable=in_range(range(5, 31)), unit="°C")
    """Room setpoint in ECO mode"""

    room_setpoint_2 = uint16(address=651, scale=0.1, writable=in_range(range(5, 31)), unit="°C")
    """Room setpoint in COMFORT mode"""

    room_setpoint_3 = uint16(address=652, scale=0.1, writable=in_range(range(5, 31)), unit="°C")
    """Room setpoint in AWAY mode"""

    room_setpoint_4 = uint16(address=653, scale=0.1, writable=in_range(range(5, 31)), unit="°C")
    """Room setpoint in MORNING mode"""

    room_setpoint_5 = uint16(address=654, scale=0.1, writable=in_range(range(5, 31)), unit="°C")
    """Room setpoint in EVENING mode"""

    room_cooling_setpoint_1 = uint16(address=656, scale=0.1, writable=True, unit="°C")
    """Cooling setpoint in ECO mode"""

    room_cooling_setpoint_2 = uint16(address=657, scale=0.1, writable=True, unit="°C")
    """Cooling setpoint in COMFORT mode"""

    room_cooling_setpoint_3 = uint16(address=658, scale=0.1, writable=True, unit="°C")
    """Cooling setpoint in AWAY mode"""

    room_cooling_setpoint_4 = uint16(address=659, scale=0.1, writable=True, unit="°C")
    """Cooling setpoint in MORNING mode"""

    room_cooling_setpoint_5 = uint16(address=660, scale=0.1, writable=True, unit="°C")
    """Cooling setpoint in EVENING mode"""

    temporary_room_setpoint = uint16(address=663, scale=0.1, writable=True, unit="°C")
    """Temporary room setpoint override. Only available when mode is SCHEDULING.

    Do not write to this field directly, instead call `await zone.async_set_current_setpoint()`
    """

    room_manual_setpoint = uint16(address=664, scale=0.1, writable=True, unit="°C")
    """The current room temperature setpoint"""

    dhw_comfort_setpoint = uint16(address=665, scale=0.01, writable=True, unit="°C")
    """The setpoint for DHW in comfort mode"""

    dhw_reduced_setpoint = uint16(address=666, scale=0.01, writable=True, unit="°C")
    """The setpoint for DHW in reduced (eco) mode"""

    heating_curve_slope = uint8(address=674, scale=0.1, writable=True)
    """The slope of the heating curve of the zone"""

    heating_curve_base_comfort = uint16(address=675, scale=0.1, writable=True, unit="°C")
    """The heating curve base temperature in comfort mode. 15 °C means off."""

    heating_curve_base_reduced = uint16(address=676, scale=0.1, writable=True, unit="°C")
    """The heating curve base temperature in reduced mode. 15 °C means off."""

    dhw_calorifier_hysteresis = uint16(address=686, scale=0.01, writable=True, unit="°C")
    """Hysteresis to start DHW tank load"""

    _selected_schedule = enum(
        address=688, enum_type=ClimateZoneScheduleId, nan=0xFF, writable=_writable_schedule_id()
    )
    """The currently selected schedule id.

    Although this property is optional, it needn't be `None` if `mode != ClimateZoneMode.SCHEDULING`.
    """

    available_schedules = repeating_group(
        4, TimeProgram, stride=REMEHA_TIME_PROGRAM_RESERVED_REGISTERS
    )

    _temporary_room_setpoint_end_time = nullable_binary(address=978, count=3, writable=True)
    """End time of temporary room setpoint override"""

    flow_temperature = int16(address=1100, scale=0.01, unit="°C")
    """The current flow water temperature of the zone.

    For a domestic hot water zone this is the outgoing DHW temperature.
    """

    room_temperature = int16(address=1104, scale=0.1, unit="°C")
    """The current room temperature"""

    heating_mode = enum(address=1109, enum_type=ClimateZoneHeatingMode, nan=0xFF)
    """The current heating mode of the climate zone"""

    pump_running = boolean(address=1110)
    """Whether the zone pump is currently running"""

    dhw_tank_temperature = int16(address=1119, scale=0.01, unit="°C")
    """The current DHW tank temperature"""

    id: int
    """The one-based sequence id of this zone."""

    time_zone: tzinfo | None
    """The time zone of the related appliance"""

    appliance_requires_cooling: Callable[[], bool]
    """Whether the related appliance requires cooling"""

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        sequence_id: int = 1,
        time_zone: tzinfo | None = None,
        appliance_requires_cooling: Callable[[], bool] = lambda: False,
    ) -> None:
        """Create a new ClimateZone component."""

        super().__init__(
            unit, index=1, base_offset=(sequence_id - 1) * REMEHA_ZONE_RESERVED_REGISTERS
        )

        self.id = sequence_id
        self.time_zone = time_zone
        self.appliance_requires_cooling = appliance_requires_cooling

    @property
    def selected_schedule(self) -> ClimateZoneScheduleId | None:
        """The mapped selected schedule.

        Remeha stores the cooling schedule in schedule 4, but writing that to
        `selected_schedule` raises an exception since it only allows the values
        of schedule 1 through 3.

        The API transparently maps this so that users can r/w the selected
        schedule intuitively.
        """

        return (
            _map_selected_schedule_for_read(
                zone_mode=self.mode,
                zone_function=self.function,
                appliance_requires_cooling=self.appliance_requires_cooling(),
                selected_schedule=self._selected_schedule,
            )
            if self._selected_schedule is not None
            and self.mode is not None
            and self.function is not None
            else None
        )

    @property
    def current_schedule(self) -> dict[Weekday, list[Timeslot] | None]:
        """The selected schedule.

        If no schedule was selected, this method returns the dict with all
        time slots set to `None`.
        """

        selected = self.selected_schedule
        if selected is None:
            return dict.fromkeys(Weekday)

        time_program = self.available_schedules[selected]
        return {day: time_program.day_schedules[day].slots for day in Weekday}

    @property
    def temporary_room_setpoint_end_time(self) -> datetime | None:
        """The end time of the temporary room setpoint override.

        The returned `datetime` is in the configured time zone of `self.time_zone`.
        """

        if self._temporary_room_setpoint_end_time is None:
            return None

        return TimeOfDay.from_bytes(
            data=self._temporary_room_setpoint_end_time, time_zone=self.time_zone
        )

    def _get_cooling_scheduling_setpoint(self, setpoint_type: TimeslotSetpointType) -> float | None:
        match setpoint_type:
            case TimeslotSetpointType.ECO:
                return self.room_cooling_setpoint_1
            case TimeslotSetpointType.COMFORT:
                return self.room_cooling_setpoint_2
            case TimeslotSetpointType.AWAY:
                return self.room_cooling_setpoint_3
            case TimeslotSetpointType.MORNING:
                return self.room_cooling_setpoint_4
            case TimeslotSetpointType.EVENING:
                return self.room_cooling_setpoint_5

        _LOGGER.warning("Unknown setpoint type %s for climate zone %d", setpoint_type.name, self.id)
        return None

    def _get_heating_scheduling_setpoint(self, setpoint_type: TimeslotSetpointType) -> float | None:
        match setpoint_type:
            case TimeslotSetpointType.ECO:
                return self.room_setpoint_1
            case TimeslotSetpointType.COMFORT:
                return self.room_setpoint_2
            case TimeslotSetpointType.AWAY:
                return self.room_setpoint_3
            case TimeslotSetpointType.MORNING:
                return self.room_setpoint_4
            case TimeslotSetpointType.EVENING:
                return self.room_setpoint_5

        _LOGGER.warning("Unknown setpoint type %s for climate zone %d", setpoint_type.name, self.id)
        return None

    def _get_current_ch_scheduling_setpoint(self) -> float | None:
        if self.temporary_room_setpoint_end_time is not None:
            if (
                self.temporary_room_setpoint_end_time is not None
                and self.temporary_room_setpoint_end_time >= datetime.now(tz=self.time_zone)
            ):
                # A setpoint override is currently active.
                return cast(float, self.temporary_room_setpoint)

        schedule = self.current_schedule
        current_timeslot: Timeslot | None = get_current_timeslot(
            schedule=schedule, time_zone=self.time_zone
        )

        if current_timeslot is None:
            _LOGGER.warning(
                "Cannot determine current CH setpoint because current timeslot failed to resolve."
            )
            return None

        if self.selected_schedule is None:
            _LOGGER.warning(
                "Cannot determine current CH setpoint because it's in scheduling mode but no schedule has been selected."
            )
            return None

        if self.selected_schedule.is_cooling_schedule():
            return self._get_cooling_scheduling_setpoint(current_timeslot.setpoint_type)

        return self._get_heating_scheduling_setpoint(current_timeslot.setpoint_type)

    def _get_current_dhw_scheduling_setpoint(self) -> float | None:
        if self.temporary_room_setpoint_end_time is not None:
            if (
                self.temporary_room_setpoint_end_time is not None
                and self.temporary_room_setpoint_end_time >= datetime.now(tz=self.time_zone)
            ):
                # A setpoint override is currently active.
                return cast(float, self.temporary_room_setpoint)

        current_timeslot: Timeslot | None = get_current_timeslot(
            schedule=self.current_schedule, time_zone=self.time_zone
        )
        if current_timeslot is not None:
            match current_timeslot.setpoint_type:
                case TimeslotSetpointType.ECO:
                    return self.dhw_reduced_setpoint
                case TimeslotSetpointType.COMFORT:
                    return self.dhw_comfort_setpoint

        return None

    async def _async_temporary_room_setpoint_override(
        self, setpoint: float, hours: int = 2
    ) -> None:
        """Override the current scheduling setpoint for 2 hours.

        Args:
            setpoint (float): The temporary setpoint.
            hours (int): The  override duration in hours

        """
        await self.write("temporary_room_setpoint", setpoint)

        now: datetime = datetime.now(tz=self.time_zone)
        override_end_time: datetime = now + relativedelta.relativedelta(hours=hours)
        await self.write("_temporary_room_setpoint_end_time", TimeOfDay.to_bytes(override_end_time))

    @property
    def current_setpoint(self) -> float | None:
        """The current setpoint of this zone.

        The actual returned setpoint field depends on the type of zone and
        the current zone mode.

        Returns:
            `float`: The current zone setpoint, or `None` if zone type or mode does not support a current setpoint.

        """

        if self.is_central_heating():
            match self.mode:
                case ClimateZoneMode.SCHEDULING:
                    return self._get_current_ch_scheduling_setpoint()
                case ClimateZoneMode.MANUAL:
                    return self.room_manual_setpoint
                case ClimateZoneMode.ANTI_FROST:
                    return self.min_temp
        if self.is_domestic_hot_water():
            match self.mode:
                case ClimateZoneMode.SCHEDULING:
                    return self._get_current_dhw_scheduling_setpoint()
                case ClimateZoneMode.MANUAL:
                    return self.dhw_comfort_setpoint
                case ClimateZoneMode.ANTI_FROST:
                    return self.dhw_reduced_setpoint

        _LOGGER.warning("Current setpoint not supported for climate zones of type %s", self.type)
        return None

    @property
    def current_temparature(self) -> float:
        """The current temperature of this zone.

        The actual returned temperature field depends on the type of zone.
        """

        if self.is_central_heating():
            return cast(float, self.room_temperature)

        if self.is_domestic_hot_water():
            return cast(float, self.dhw_tank_temperature)

        _LOGGER.warning("Current temperature not supported for climate zones of type %s", self.type)
        return -1

    @property
    def max_temp(self) -> float:
        """The highest allowed setpoint for this zone.

        The maximum temperature differs per zone type:
        * For DHW (Domestinc Hot Water) it's 65 degrees C
        * For CH (Central Heating) or mixing circuits it's 30 degrees C
        * For all others it's the lowest value of the above.
        This is to ensure unknown zone types won't get a flow temperature they can't handle.
        """

        if self.is_central_heating():
            return Limits.CH_MAX_TEMP

        if self.is_domestic_hot_water():
            return Limits.DHW_MAX_TEMP

        return min(Limits.CH_MAX_TEMP, Limits.DHW_MAX_TEMP)

    @property
    def min_temp(self) -> float:
        """The lowest allowed setpoint for this zone.

        The minimum temperature differs per zone type:
        * For DHW (Domestinc Hot Water) it's 6 degrees C
        * For CH (Central Heating) or mixing circuits it's 10 degrees C
        * For all others it's the highest value of the above.
        This is to ensure unknown zone types won't get a flow temperature they can't handle.
        """

        if self.is_central_heating():
            return Limits.CH_MIN_TEMP

        if self.is_domestic_hot_water():
            return Limits.DHW_MIN_TEMP

        return max(Limits.CH_MIN_TEMP, Limits.DHW_MIN_TEMP)

    def has_cooling_capability(self) -> bool:
        """Whether this type of climate zone is capable of cooling."""

        return cast(ClimateZoneFunction, self.function).has_cooling_capability()

    def is_central_heating(self) -> bool:
        """Determine if this zone is a CH (central heating) zone."""

        return is_central_heating(
            cast(ClimateZoneType, self.type), cast(ClimateZoneFunction, self.function)
        )

    def is_domestic_hot_water(self) -> bool:
        """Determine if this zone is a DHW (domestic hot water) zone."""

        return is_domestic_hot_water(
            cast(ClimateZoneType, self.type), cast(ClimateZoneFunction, self.function)
        )

    async def async_set_mode(self, mode: ClimateZoneMode):
        """Set the mode of this zone."""

        await self.write("mode", mode)

    async def async_set_current_setpoint(self, setpoint: float):
        """Set the current setpoint of this zone.

        Args:
            setpoint (float): The target temperature in °C.

        """

        # Check requested setpoint against min/max
        if setpoint < self.min_temp or setpoint > self.max_temp:
            _LOGGER.warning(
                "Ignoring requested setpoint of %0.2f since it is outside allowed range (%0.2f, %0.2f)",
                setpoint,
                self.min_temp,
                self.max_temp,
            )
            return

        if self.is_central_heating():
            match self.mode:
                case ClimateZoneMode.SCHEDULING:
                    await self._async_temporary_room_setpoint_override(
                        setpoint, hours=cast(int, Limits.SCHEDULING_SETPOINT_OVERRIDE_DURATION)
                    )
                case ClimateZoneMode.MANUAL:
                    await self.write("room_manual_setpoint", setpoint)
                case _:
                    pass

        elif self.is_domestic_hot_water():
            match self.mode:
                case ClimateZoneMode.SCHEDULING:
                    # DHW does not support a temporary setpoint override, at least
                    # through modbus the and Remeha Home app.
                    # Update schedule instead.
                    _LOGGER.warning(
                        "Overriding DHW climate scheduling setpoint not supported; adjust schedule to do this."
                    )
                case ClimateZoneMode.MANUAL:
                    await self.write("dhw_comfort_setpoint", setpoint)
                case ClimateZoneMode.ANTI_FROST:
                    await self.write("dhw_reduced_setpoint", setpoint)
        else:
            _LOGGER.warning(
                "Setting setpoint not supported for climate zones of type %s", self.type
            )

    async def async_set_room_setpoint_1(self, value: float):
        """Write the `ECO` room setpoint for heating."""

        await self.write("room_setpoint_1", value)

    async def async_set_room_setpoint_2(self, value: float):
        """Write the `COMFORT` room setpoint for heating."""

        await self.write("room_setpoint_2", value)

    async def async_set_room_setpoint_3(self, value: float):
        """Write the `AWAY` room setpoint for heating."""

        await self.write("room_setpoint_3", value)

    async def async_set_room_setpoint_4(self, value: float):
        """Write the `MORNING` room setpoint for heating."""

        await self.write("room_setpoint_4", value)

    async def async_set_room_setpoint_5(self, value: float):
        """Write the `EVENING` room setpoint for heating."""

        await self.write("room_setpoint_5", value)

    async def async_set_room_cooling_setpoint_1(self, value: float):
        """Write the `ECO` room setpoint."""

        await self.write("room_cooling_setpoint_1", value)

    async def async_set_room_cooling_setpoint_2(self, value: float):
        """Write the `COMFORT` room setpoint."""

        await self.write("room_cooling_setpoint_2", value)

    async def async_set_room_cooling_setpoint_3(self, value: float):
        """Write the `AWAY` room setpoint."""

        await self.write("room_cooling_setpoint_3", value)

    async def async_set_room_cooling_setpoint_4(self, value: float):
        """Write the `MORNING` room setpoint."""

        await self.write("room_cooling_setpoint_4", value)

    async def async_set_room_cooling_setpoint_5(self, value: float):
        """Write the `EVENING` room setpoint."""

        await self.write("room_cooling_setpoint_5", value)

    async def async_set_dhw_calorifier_hysteresis(self, value: float):
        """Write the DHW Calorifier Hysteresis.

        Args:
            value (float): The hysteresis in degrees C.

        """

        await self.write("dhw_calorifier_hysteresis", value)

    async def async_set_selected_schedule(self, value: ClimateZoneScheduleId):
        """Write the selected schedule.

        Only schedules 1-3 can be written. If schedule 4 is provided,
        it is transparently mapped to schedule 1 before writing.

        Args:
            value (ClimateZoneScheduleId): The schedule to select.

        """

        await self.write(
            "_selected_schedule",
            _map_selected_schedule_for_write(
                selected_schedule=value,
            ),
        )

    async def async_set_current_schedule(
        self, schedule_id: ClimateZoneScheduleId, schedule: dict[Weekday, list[Timeslot] | None]
    ):
        """Write a full schedule.

        Setting the current schedule also updates `selected_schedule` to `schedule_id`.

        Raises:
            RemehaApiError(`translation_key="schedule_write_not_supported"`):
                If this zone is neither a DHW zone nor a cooling schedule (`schedule_4`).

            RemehaApiError(`translation_key="invalid_schedule"`): If `schedule` doesn't contain
                a value for each `Weekday`.

        """

        # All week days must be assigned a schedule.
        if len(schedule) != len(Weekday):
            raise RemehaApiError("invalid_schedule")

        # Writing a schedule is only supported for DHW schedules and CH cooling schedules
        if self.is_domestic_hot_water() or schedule_id.is_cooling_schedule():
            # Select the current schedule if required
            if self.selected_schedule is not schedule_id:
                await self.async_set_selected_schedule(schedule_id)

            # Sequentially write all schedules.
            for day in Weekday:
                time_program_start = _time_program_start_address(self.id, schedule_id)
                day_schedule_start = (
                    time_program_start + day * REMEHA_DAY_SCHEDULE_RESERVED_REGISTERS
                )
                day_schedule = DaySchedule(
                    unit=self._unit,
                    base_offset=day_schedule_start,
                )

                await day_schedule.async_set_time_slots(schedule[day] or [])
        else:
            raise RemehaApiError("schedule_write_not_supported")

    def __eq__(self, other) -> bool:
        """Compare this `ClimateZone` with another for equality.

        For equality, only the properties ``id``, ``type`` and ``function`` are considered.

        Returns:
            `bool`: `True` if the objects are considered equal, `False` otherwise.

        """
        if isinstance(other, self.__class__):
            return (
                self.id == other.id and self.type == other.type and self.function == other.function
            )

        return False

    def __hash__(self) -> int:
        """Return a hash of this zone."""

        return hash(frozenset(vars(self)))
