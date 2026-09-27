"""GTW26 boiler and system sensor components."""

from modbus_connection.model import bit, integer

import aio_remeha_modbus.gtw08  # noqa: F401
from aio_remeha_modbus.gtw26.const import BASE_WINDOWS, ISYSTEM_WINDOWS, M3_GT_FAULTS
from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.helpers.fields import fault_code, float10, multiplied_integer


class Sensors(Gtw26Component):
    """Boiler and system sensor readings in the base layout."""

    register_ranges = BASE_WINDOWS

    outdoor_temperature = float10(7, unit="°C")
    mean_outside_temperature = float10(102, unit="°C")
    outdoor_temperature_bus = float10(470, unit="°C")
    boiler_temperature = float10(75, unit="°C")
    boiler_temperature_dpsm = float10(452, unit="°C")
    calculated_boiler_temperature = float10(462, unit="°C")
    return_temperature = float10(453, unit="°C")
    flue_gas_temperature = float10(454, unit="°C")
    water_pressure = float10(456, unit="bar")
    ionization_current = float10(451, unit="µA")
    fan_speed = integer(455, signed=False, nan=0xFFFF, unit="rpm")
    pump_power = integer(463, signed=False, nan=0xFFFF, unit="%")
    instantaneous_power = float10(471, unit="kW")
    average_power = float10(472, unit="kW")
    solar_temperature = float10(467, unit="°C")
    solar_tank_temperature = float10(468, unit="°C")
    burner_active = bit(427, 3)
    hot_water_pump_active = bit(427, 5)
    fault = fault_code(465, M3_GT_FAULTS)
    sensor_faults = integer(116, signed=False, nan=0xFFFF)


class ISystemSensors(Gtw26Component):
    """Boiler and system sensor readings in the iSystem layout."""

    register_ranges = ISYSTEM_WINDOWS

    outdoor_temperature = float10(601, unit="°C")
    boiler_temperature = float10(602, unit="°C")
    calculated_boiler_temperature = float10(620, unit="°C")
    secondary_calculated_temperature = float10(734, unit="°C")
    return_temperature = float10(607, unit="°C")
    auxiliary_1_temperature = float10(622, unit="°C")
    auxiliary_2_temperature = float10(623, unit="°C")
    universal_temperature = float10(624, unit="°C")
    ionization_current = float10(608, unit="µA")
    fan_speed = integer(609, signed=False, nan=0xFFFF, unit="rpm")
    instantaneous_power = integer(613, signed=False, unit="%")
    flue_gas_temperature = float10(604, unit="°C")
    water_pressure = float10(610, unit="bar")
    mean_outside_temperature = float10(102, unit="°C")
    burner_start_count = multiplied_integer(251, 4, nan=0xFFFF, unit="starts")
    burner_runtime_hours = integer(252, signed=False, nan=0xFFFF, unit="h")
    burner_active = bit(427, 3)
    hot_water_pump_active = bit(427, 5)
    fault = fault_code(465, M3_GT_FAULTS)
