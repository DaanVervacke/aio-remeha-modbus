"""GTW26 heating climate-zone components."""

from modbus_connection.model import NumberField, bit, integer

from aio_remeha_modbus.gtw26.const import (
    BASE_MODE_REGISTERS,
    BASE_WINDOWS,
    HEATING_MODE_MASK,
    ISYSTEM_MODE_REGISTERS,
    ISYSTEM_WINDOWS,
    ActiveMode,
    CircuitType,
    HeatingMode,
)
from aio_remeha_modbus.gtw26.fields import (
    derogation_until_end,
    permanent_derogation,
    time_program,
)
from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.helpers.fields import (
    enum_value,
    float10,
    masked_enum,
    snap_clamp,
)

_BASE_ZONE_A, _BASE_ZONE_B = BASE_MODE_REGISTERS
_ISYSTEM_ZONE_A, _ISYSTEM_ZONE_B, _ISYSTEM_ZONE_C = ISYSTEM_MODE_REGISTERS

_ZONE = snap_clamp(0.5, 5.0, 30.0)
_SLOPE = snap_clamp(0.1, 0.0, 4.0)
_ZONE_DAY = snap_clamp(0.5, 10.0, 30.0)
_ZONE_NIGHT = snap_clamp(0.5, 5.0, 30.0)
_ZONE_BC_MIN = snap_clamp(0.5, 10.0, 30.0)
_ZONE_BC_MAX = snap_clamp(0.5, 50.0, 95.0)
_ZONE_FROST = snap_clamp(0.5, 3.0, 20.0)


class ClimateZone(Gtw26Component):
    """Base-layout climate-zone component. The facade sets its designation."""

    register_ranges = BASE_WINDOWS
    designation: str


class ClimateZoneA(ClimateZone):
    """Base-layout climate zone A."""

    room_temperature = float10(18, unit="°C")
    calculated_temperature = float10(21, unit="°C")
    mode = masked_enum(_BASE_ZONE_A, HEATING_MODE_MASK, HeatingMode)
    pump_active = bit(427, 4)
    ambient_influence = integer(19, signed=False)
    heating_curve_slope = float10(20, writable=_SLOPE, force_fc16=True, unit="K/K")
    comfort_target = float10(14, writable=_ZONE, force_fc16=True, unit="°C")
    reduced_target = float10(15, writable=_ZONE, force_fc16=True, unit="°C")
    frost_protection_target = float10(16, writable=_ZONE, force_fc16=True, unit="°C")


class ClimateZoneB(ClimateZone):
    """Base-layout climate zone B."""

    room_temperature = float10(27, unit="°C")
    calculated_temperature = float10(32, unit="°C")
    supply_temperature = float10(33, unit="°C")
    mode = masked_enum(_BASE_ZONE_B, HEATING_MODE_MASK, HeatingMode)
    pump_active = bit(428, 4)
    ambient_influence = integer(28, signed=False)
    min_temperature = float10(30, unit="°C")
    max_temperature = float10(31, unit="°C")
    heating_curve_slope = float10(29, writable=_SLOPE, force_fc16=True, unit="K/K")
    comfort_target = float10(23, writable=_ZONE, force_fc16=True, unit="°C")
    reduced_target = float10(24, writable=_ZONE, force_fc16=True, unit="°C")
    frost_protection_target = float10(25, writable=_ZONE, force_fc16=True, unit="°C")


class ISystemClimateZone(Gtw26Component):
    """iSystem climate-zone base. The facade sets its A, B, or C designation."""

    register_ranges = ISYSTEM_WINDOWS
    designation: str


class ISystemClimateZoneA(ISystemClimateZone):
    """iSystem climate zone A."""

    room_temperature = float10(614, unit="°C")
    calculated_temperature = float10(615, unit="°C")
    supply_temperature = float10(621, unit="°C")
    mode = masked_enum(_ISYSTEM_ZONE_A, HEATING_MODE_MASK, HeatingMode)
    circuit_type = enum_value(296, CircuitType)
    active_mode = masked_enum(637, 0x06, ActiveMode)
    permanent_derogation = NumberField[bool | None](
        _ISYSTEM_ZONE_A, signed=False, convert=permanent_derogation
    )
    derogation_until_end = NumberField[bool | None](
        _ISYSTEM_ZONE_A, signed=False, convert=derogation_until_end
    )
    program = time_program(231)
    pump_active = bit(427, 4)
    ambient_influence = integer(654, signed=False)
    heating_curve_slope = float10(655, writable=_SLOPE, force_fc16=True, unit="K/K")
    comfort_target = float10(650, writable=_ZONE_DAY, force_fc16=True, unit="°C")
    reduced_target = float10(651, writable=_ZONE_NIGHT, force_fc16=True, unit="°C")
    frost_protection_target = float10(652, writable=_ZONE_FROST, force_fc16=True, unit="°C")


class ISystemClimateZoneB(ISystemClimateZone):
    """iSystem climate zone B."""

    room_temperature = float10(616, unit="°C")
    calculated_temperature = float10(617, unit="°C")
    supply_temperature = float10(605, unit="°C")
    mode = masked_enum(_ISYSTEM_ZONE_B, HEATING_MODE_MASK, HeatingMode)
    circuit_type = enum_value(297, CircuitType)
    active_mode = masked_enum(638, 0x06, ActiveMode)
    permanent_derogation = NumberField[bool | None](
        _ISYSTEM_ZONE_B, signed=False, convert=permanent_derogation
    )
    derogation_until_end = NumberField[bool | None](
        _ISYSTEM_ZONE_B, signed=False, convert=derogation_until_end
    )
    all_circuits_derogation = bit(659, 7)
    program = time_program(232)
    pump_active = bit(428, 4)
    valve_opening = bit(428, 1)
    valve_closing = bit(428, 0)
    ambient_influence = integer(660, signed=False)
    heating_curve_slope = float10(661, writable=_SLOPE, force_fc16=True, unit="K/K")
    min_temperature = float10(662, writable=_ZONE_BC_MIN, force_fc16=True, unit="°C")
    max_temperature = float10(663, writable=_ZONE_BC_MAX, force_fc16=True, unit="°C")
    comfort_target = float10(656, writable=_ZONE_DAY, force_fc16=True, unit="°C")
    reduced_target = float10(657, writable=_ZONE_NIGHT, force_fc16=True, unit="°C")
    frost_protection_target = float10(658, writable=_ZONE_FROST, force_fc16=True, unit="°C")


class ISystemClimateZoneC(ISystemClimateZone):
    """iSystem climate zone C."""

    room_temperature = float10(618, unit="°C")
    calculated_temperature = float10(619, unit="°C")
    mode = masked_enum(_ISYSTEM_ZONE_C, HEATING_MODE_MASK, HeatingMode)
    circuit_type = enum_value(360, CircuitType)
    active_mode = masked_enum(639, 0x06, ActiveMode)
    program = time_program(233)
    permanent_derogation = NumberField[bool | None](
        _ISYSTEM_ZONE_C, signed=False, convert=permanent_derogation
    )
    derogation_until_end = NumberField[bool | None](
        _ISYSTEM_ZONE_C, signed=False, convert=derogation_until_end
    )
    all_circuits_derogation = bit(667, 7)
    ambient_influence = integer(668, signed=False)
    heating_curve_slope = float10(669, writable=_SLOPE, force_fc16=True, unit="K/K")
    min_temperature = float10(670, writable=_ZONE_BC_MIN, force_fc16=True, unit="°C")
    max_temperature = float10(671, writable=_ZONE_BC_MAX, force_fc16=True, unit="°C")
    comfort_target = float10(664, writable=_ZONE_DAY, force_fc16=True, unit="°C")
    reduced_target = float10(665, writable=_ZONE_NIGHT, force_fc16=True, unit="°C")
    frost_protection_target = float10(666, writable=_ZONE_FROST, force_fc16=True, unit="°C")
