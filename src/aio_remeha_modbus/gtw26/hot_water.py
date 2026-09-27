"""GTW26 domestic hot-water components."""

from modbus_connection.model import integer

import aio_remeha_modbus.gtw08  # noqa: F401
from aio_remeha_modbus.gtw26.const import (
    BASE_WINDOWS,
    HOT_WATER_MODE_MASK,
    ISYSTEM_HOT_WATER_REGISTER,
    ISYSTEM_WINDOWS,
    ActiveMode,
    HotWaterMode,
    HotWaterPriority,
    LegionellaProtection,
)
from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.helpers.fields import enum_value, float10, int_clamp, masked_enum, snap_clamp

_HOT_WATER = snap_clamp(1.0, 10.0, 80.0)
_PUMP_DELAY = int_clamp(0, 15)


class HotWater(Gtw26Component):
    """Domestic hot-water readings and setpoints in the base layout."""

    register_ranges = BASE_WINDOWS

    temperature = float10(62, unit="°C")
    priority = masked_enum(60, 0xFF, HotWaterPriority)
    pump_delay = integer(61, signed=False, writable=True, force_fc16=True, unit="min")
    temperature_dpsm = float10(459, unit="°C")
    mode = masked_enum(17, HOT_WATER_MODE_MASK, HotWaterMode)
    comfort_target = float10(59, writable=_HOT_WATER, force_fc16=True, unit="°C")
    reduced_target = float10(96, writable=_HOT_WATER, force_fc16=True, unit="°C")


class ISystemHotWater(Gtw26Component):
    """Domestic hot-water readings and setpoints in the iSystem layout."""

    register_ranges = ISYSTEM_WINDOWS

    temperature = float10(603, unit="°C")
    mode = masked_enum(ISYSTEM_HOT_WATER_REGISTER, HOT_WATER_MODE_MASK, HotWaterMode)
    active_mode = masked_enum(640, 0x06, ActiveMode)
    priority = enum_value(674, HotWaterPriority, writable=True, force_fc16=True)
    pump_delay = integer(61, signed=False, writable=_PUMP_DELAY, force_fc16=True, unit="min")
    legionella_protection = enum_value(268, LegionellaProtection, writable=True, force_fc16=True)
    comfort_target = float10(672, writable=_HOT_WATER, force_fc16=True, unit="°C")
    reduced_target = float10(673, writable=_HOT_WATER, force_fc16=True, unit="°C")
