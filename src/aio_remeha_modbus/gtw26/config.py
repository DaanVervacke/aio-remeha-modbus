"""GTW26 configuration, output and service register components."""

from collections.abc import Callable
from typing import Self

from modbus_connection.model import bit, integer

# Import the GTW08 package before the shared field helpers.  The existing GTW08
# package imports those helpers from its module initialisation path.
import aio_remeha_modbus.gtw08  # noqa: F401
from aio_remeha_modbus.gtw26.const import (
    BASE_WINDOWS,
    ISYSTEM_WINDOWS,
    ActiveMode,
    AuxiliaryInput,
    AuxiliaryOutputType,
    AuxiliaryType,
    HotWaterPriority,
    Language,
    NightMode,
)
from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.helpers.fields import (
    enum_value,
    float10,
    float10_range,
    int_clamp,
    masked_enum,
    multiplied_integer,
    positive_float10,
    scaled_integer,
    snap_clamp,
)

_ZONE = snap_clamp(0.5, 5.0, 30.0)
_SUMMER_WINTER = snap_clamp(0.5, 15.0, 30.5)
_HOT_WATER = snap_clamp(1.0, 10.0, 80.0)
_SLOPE = snap_clamp(0.1, 0.0, 4.0)
_PUMP_DELAY = int_clamp(0, 15)
_INERTIA = int_clamp(0, 10)
_BANDWIDTH = snap_clamp(1.0, 4.0, 16.0)
_ZONE_A_MIN = snap_clamp(0.5, 10.0, 50.0)
_ZONE_A_MAX = snap_clamp(0.5, 20.0, 120.0)
_ANTICIPATION = snap_clamp(0.1, 0.0, 10.0)
_BOILER_MIN = float10_range(30.0, 50.0)
_BOILER_MAX = float10_range(50.0, 95.0)


class Settings(Gtw26Component):
    """Boiler-level configuration in the base register layout."""

    register_ranges = BASE_WINDOWS

    frost_threshold = float10(9, writable=positive_float10, force_fc16=True, unit="°C")
    summer_winter_temperature = float10(8, writable=_SUMMER_WINTER, force_fc16=True, unit="°C")
    boiler_minimum_temperature = float10(70, writable=_BOILER_MIN, force_fc16=True, unit="°C")
    boiler_maximum_temperature = float10(71, writable=_BOILER_MAX, force_fc16=True, unit="°C")
    primary_boiler_temperature = float10(121, unit="°C")


class Outputs(Gtw26Component):
    """Read-only output words and documented secondary output bits."""

    register_ranges = BASE_WINDOWS

    primary = integer(474, signed=False)
    secondary = integer(475, signed=False)
    dhw_pump_active = bit(475, 0)
    circuit_a_pump_active = bit(475, 1)
    circuit_a_valve_opening = bit(475, 2)
    circuit_a_valve_closing = bit(475, 3)
    circuit_b_pump_active = bit(475, 4)
    circuit_b_valve_opening = bit(475, 5)
    circuit_b_valve_closing = bit(475, 6)
    circuit_c_pump_active = bit(475, 7)
    circuit_c_valve_opening = bit(475, 8)
    circuit_c_valve_closing = bit(475, 9)
    auxiliary_1_pump_active = bit(475, 10)
    auxiliary_2_pump_active = bit(475, 11)
    auxiliary_3_pump_active = bit(475, 12)
    phone_output_active = bit(475, 13)


class Service(Gtw26Component):
    """Read-only burner counters and runtime values."""

    register_ranges = BASE_WINDOWS

    burner_start_count = scaled_integer(77, 10, unit="starts")
    burner_runtime_hours = scaled_integer(78, 10, unit="h")
    second_stage_start_count = scaled_integer(79, 10, unit="starts")
    second_stage_runtime_hours = scaled_integer(80, 10, unit="h")
    burner_start_count_raw = integer(251, signed=False, unit="starts")
    burner_runtime_hours_raw = integer(252, signed=False, unit="h")
    second_stage_start_count_raw = integer(253, signed=False, unit="starts")
    second_stage_runtime_hours_raw = integer(254, signed=False, unit="h")


class ISystemSettings(Gtw26Component):
    """Boiler-level configuration in the iSystem register layout."""

    register_ranges = ISYSTEM_WINDOWS

    language = enum_value(263, Language)
    summer_winter_temperature = float10(8, writable=_SUMMER_WINTER, force_fc16=True, unit="°C")
    outdoor_antifreeze = float10(9, unit="°C")
    night_mode = enum_value(10, NightMode, writable=True, force_fc16=True)
    heating_pump_delay = integer(
        11, signed=False, writable=_PUMP_DELAY, force_fc16=True, unit="min"
    )
    boiler_minimum_temperature = float10(677, unit="°C")
    boiler_maximum_temperature = float10(678, unit="°C")


class Config(Gtw26Component):
    """Installer settings and output values cached after their first read."""

    register_ranges = ISYSTEM_WINDOWS
    _on_written: Callable[[Self], None] | None = None

    async def write(self, field: str, value: object) -> None:
        """Write a config field and notify the facade to reread it."""
        await super().write(field, value)
        if self._on_written is not None:
            self._on_written(self)

    autoadapt_a = float10(247)
    autoadapt_b = float10(248)
    autoadapt_c = float10(249)
    building_inertia = integer(264, signed=False, writable=_INERTIA, force_fc16=True)
    bandwidth = float10(266, writable=_BANDWIDTH, force_fc16=True, unit="K")
    three_way_valve_shift = float10(267)
    min_running_time = integer(269, signed=False, unit="s")
    burner_temporisation = integer(271, signed=False)
    pump_postrun = multiplied_integer(272, 2, unit="min")
    outside_calibration = float10(274, unit="°C")
    zone_a_calibration = float10(275, unit="°C")
    zone_b_calibration = float10(276, unit="°C")
    zone_c_calibration = float10(277, unit="°C")
    anticipation_a = float10(282, writable=_ANTICIPATION, force_fc16=True, none_values=(101,))
    anticipation_b = float10(283, writable=_ANTICIPATION, force_fc16=True, none_values=(101,))
    anticipation_c = float10(284, writable=_ANTICIPATION, force_fc16=True, none_values=(101,))
    footprint_a_day = float10(289, none_values=(150,))
    footprint_a_night = float10(290, none_values=(150,))
    footprint_b_day = float10(291, none_values=(150,))
    footprint_b_night = float10(292, none_values=(150,))
    footprint_c_day = float10(358, none_values=(150,))
    footprint_c_night = float10(359, none_values=(150,))
    zone_a_min = float10(298, writable=_ZONE_A_MIN, force_fc16=True, unit="°C")
    zone_a_max = float10(299, writable=_ZONE_A_MAX, force_fc16=True, unit="°C")
    three_way_valve_temperature_shift = float10(426, unit="°C")


class ISystemOutputs(Gtw26Component):
    """Read-only iSystem output words and documented output bits."""

    register_ranges = ISYSTEM_WINDOWS

    primary = integer(474, signed=False)
    secondary = integer(475, signed=False)
    boiler_state = integer(735, signed=False)
    burner_stage_1_active = bit(474, 0)
    hydraulic_valve_closing = bit(474, 3)
    boiler_pump_active = bit(474, 4)
    secondary_pump_active = bit(735, 3)
    dhw_pump_active = bit(475, 0)
    circuit_a_pump_active = bit(475, 1)
    circuit_a_valve_opening = bit(475, 2)
    circuit_a_valve_closing = bit(475, 3)
    circuit_b_pump_active = bit(475, 4)
    circuit_b_valve_opening = bit(475, 5)
    circuit_b_valve_closing = bit(475, 6)
    circuit_c_pump_active = bit(475, 7)
    circuit_c_valve_opening = bit(475, 8)
    circuit_c_valve_closing = bit(475, 9)
    auxiliary_1_pump_active = bit(475, 10)
    auxiliary_2_pump_active = bit(475, 11)
    auxiliary_3_pump_active = bit(475, 12)
    phone_output_active = bit(475, 13)


class Diagnostics(Gtw26Component):
    """Boiler state and diagnostic registers in the iSystem layout."""

    register_ranges = ISYSTEM_WINDOWS

    boiler_active_mode = integer(644, signed=False)
    aux_active_mode = masked_enum(641, 0x06, ActiveMode)
    dhw_priority = masked_enum(674, 0xFF, HotWaterPriority)
    pcu_state = integer(710, signed=False)
    pcu_substate = integer(711, signed=False)
    pcu_block = integer(712, signed=False)
    pcu_lock = integer(713, signed=False)
    auxiliary_1_input = enum_value(741, AuxiliaryInput)
    auxiliary_1_type = enum_value(744, AuxiliaryType)
    auxiliary_2_type = enum_value(745, AuxiliaryOutputType)
    auxiliary_3_type = enum_value(746, AuxiliaryOutputType)
