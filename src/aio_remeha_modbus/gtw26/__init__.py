"""Public GTW26 gateway API."""

__all__ = [
    "C230_FAULTS",
    "GTW26",
    "M3_GT_FAULTS",
    "MODEL_CODES",
    "ActiveMode",
    "AuxiliaryInput",
    "AuxiliaryOutputType",
    "AuxiliaryType",
    "CircuitType",
    "ClimateZone",
    "ClimateZoneA",
    "ClimateZoneB",
    "Config",
    "ControllerGeneration",
    "Diagnostics",
    "Gtw26Detection",
    "Gtw26ProbeError",
    "HeatingMode",
    "HotWater",
    "HotWaterMode",
    "HotWaterPriority",
    "ISystemClimateZone",
    "ISystemClimateZoneA",
    "ISystemClimateZoneB",
    "ISystemClimateZoneC",
    "ISystemHotWater",
    "ISystemIdentity",
    "ISystemOutputs",
    "ISystemSensors",
    "ISystemSettings",
    "Identity",
    "Language",
    "LegionellaProtection",
    "NightMode",
    "Outputs",
    "ProbeBlock",
    "RegisterLayout",
    "ScheduleFacade",
    "Sensors",
    "Service",
    "Settings",
    "SystemDiscoveryTable",
    "UpdateReport",
    "WeekProgram",
    "async_detect",
    "async_probe",
]

from modbus_connection.model import UpdateReport

from .climate_zone import (
    ClimateZone,
    ClimateZoneA,
    ClimateZoneB,
    ISystemClimateZone,
    ISystemClimateZoneA,
    ISystemClimateZoneB,
    ISystemClimateZoneC,
)
from .config import (
    Config,
    Diagnostics,
    ISystemOutputs,
    ISystemSettings,
    Outputs,
    Service,
    Settings,
)
from .const import (
    C230_FAULTS,
    M3_GT_FAULTS,
    MODEL_CODES,
    ActiveMode,
    AuxiliaryInput,
    AuxiliaryOutputType,
    AuxiliaryType,
    CircuitType,
    ControllerGeneration,
    HeatingMode,
    HotWaterMode,
    HotWaterPriority,
    Language,
    LegionellaProtection,
    NightMode,
    RegisterLayout,
)
from .errors import Gtw26ProbeError
from .gtw26 import GTW26, async_detect, async_probe
from .hot_water import HotWater, ISystemHotWater
from .schedule import ScheduleFacade, WeekProgram
from .sensors import ISystemSensors, Sensors
from .system_discovery_table import (
    Gtw26Detection,
    Identity,
    ISystemIdentity,
    ProbeBlock,
    SystemDiscoveryTable,
)
