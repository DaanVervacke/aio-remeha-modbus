"""Implementation of appliance-scoped functionality."""

from datetime import time
from enum import IntEnum

from modbus_connection.model import boolean, enum, uint32

from aio_remeha_modbus.gtw08.const import REMEHA_MAX_SPAN, SeasonalMode
from aio_remeha_modbus.gtw08.model import RemehaComponent
from aio_remeha_modbus.helpers.fields import int16, time_steps, uint8, uint16


class SilentMode(IntEnum):
    """Defines the silent mode of the appliance."""

    OFF = 0
    """Normal operation."""

    LEVEL_1 = 1
    """Silent mode."""

    LEVEL_2 = 2
    """Extra silent mode."""


class CoolingType(IntEnum):
    """Defines the type of cooling used by the appliance (if any)."""

    OFF = 0
    """Cooling is off."""

    ACTIVE_COOLING = 1
    """The appliance uses active cooling.

    This type of cooling is used by all air-sourced heat pumps.
    """

    FREE_COOLING = 2
    """The appliance uses free cooling.

    This type of cooling is used by geothermal and water-source
    heat pumps.
    """


class ApplianceStatus(IntEnum):
    """The current status of the appliance."""

    standby = 0
    """The appliance is in standby mode."""

    heat_demand = 1
    """A heat demand is active."""

    generator_start = 2
    """The appliance is starting up."""

    generator_heating = 3
    """The appliance is heating the CH system."""

    generator_dhw = 4
    """The appliance is heating the DHW system."""

    generator_stop = 5
    """The appliance has stopped."""

    pump_post_run = 6
    """The pump is active after the appliance has stopped."""

    cooling = 7
    """The appliance is cooling the CH system."""

    controlled_shutdown = 8
    """The appliance is not starting because a precondition has not been met."""

    start_prevention = 9
    """The appliance is blocked."""

    locking_mode = 10
    """The appliance is locked."""

    load_test_min = 11
    """The appliance is running a load test (min) on the CH system."""

    load_test_heating_max = 12
    """The appliance is running a load test (max) on the CH system."""

    load_test_dhw_max = 13
    """The appliance is running a load test (max) on the DHW system."""

    manual_heat_demand = 15
    """A manual heat demand is active."""

    frost_protection = 16
    """The appliance is running in frost-protection mode."""

    venting = 17
    """The appliance is venting."""

    control_unit_cooling = 18
    """The appliance is cooling the control unit."""

    resetting = 19
    """The appliance is being reset."""

    automatic_filling = 20
    """The appliance is filling the circuit(s)."""

    stopped = 21
    """The appliance is paused and must be stopped manually."""

    calibration = 22
    """The appliance is being calibrated."""

    factory_test = 23
    """The appliance is in factory testing mode."""

    hydraulic_balancing = 24
    """The appliance is balancing the circuits."""

    device_mode = 200
    """The service tool interface manages the appliance modes."""

    unknown = 254
    """The appliance is in an unknown state."""


class ApplianceSubStatus(IntEnum):
    """The appliance sub status provides more details about the status."""

    standby = 0
    """Appliance is waiting on a process or action."""

    anti_cyclus = 1
    """Appliance is waiting to restart because of short cycle protection."""

    close_hydraulic_valve = 2
    """Closing hydraulic valve."""

    stop_pump = 3
    """Stopping pump."""

    wait_start_release = 4
    """The appliance is waiting for temperature to meet the start up-conditions."""

    generator_starting = 21
    """The generator is starting."""

    internal_setpoint = 30
    """The appliance is working to reach the requested setpoint."""

    limited_internal_setpoint = 31
    """The appliance is working to reach the requested reduced setpoint."""

    power_controlled = 32
    """The appliance is working on the desired power level."""

    pump_post_run = 60
    """The pump is running after the appliance has stopped to release the leftover heat."""

    start_pump = 61
    """The pump has stopped."""

    start_pause_time = 63
    """Starting short cycle protection."""

    compressor_unloaded = 65
    """The compressor is running at minimum capacity."""

    hp_tmax_backup_on = 66
    """The heat pump flow temperature has exceeded its maximum limit."""

    outside_temp_limit_hp_off = 67
    """The heat pump has shut off because of an external condition; backup power is used."""

    hp_stop_by_hybrid = 68
    """The hybrid heat pump has shut off because of an external condition; backup power is used."""

    defrost_with_heat_pump = 69
    """Defrost running using only the heat pump."""

    defrost_with_backup = 70
    """Defrost running using only backup power."""

    defrost_hp_and_backup = 71
    """Defrost running using both heat pump- and backup power."""

    hp_flow_above_tmax = 73
    """The heat pump flow temperature exceeds its maximum limit."""

    hp_off_high_humidity = 75
    """The heat pump has shut off because the humidity is too high."""

    hp_off_flow = 76
    """The heat pump has shut off because the flow rate is too low."""

    generator_unloaded = 79
    """Heat pump and backup not allowed for CH and DHW."""

    hp_unloaded_cooling = 80
    """Heat pump cooling not allowed."""

    hp_stop_outside_temp = 81
    """Heat pump shut off because outside temperature is outside its limits."""

    hp_off_flow_tmax = 82
    """Heat pump shut off because it has too little operating time."""

    bl_backup_off = 88
    """Blocking input: backup power off."""

    bl_heat_pump_off = 89
    """Blocking input: heat pump power off."""

    bl_hp_and_backup_off = 90
    """Blocking input: heat pump and backup power off."""

    low_tariff = 91
    """Blocking input: low tariff."""

    pv_with_heat_pump = 92
    """Blocking input: heat pump off because of excess PV power."""

    pv_hp_and_backup = 93
    """Blocking input: heat pump and backup power off because of excess PV power."""

    smart_grid = 94
    """Blocking input: heat pump off because of smart grid settings."""

    wait_water_pressure = 95
    """Waiting for water pressure to become acceptable."""

    no_generator_available = 96
    """No generator available."""

    free_cooling_pump_off = 102
    """Heat pump free cooling mode: CH pump off"""

    free_cooling_pump_on = 103
    """Heat pump free cooling mode: CH pump on"""

    blocking_active = 106
    """The appliance has paused operation due to an unusual external and/or temporary condition."""

    warming_up = 107
    """The appliance is warming up."""

    curative_defrost = 108
    """The appliance is actively performing a corrective defrost to
    clear ice accumulation from the outdoor unit."""

    preventive_defrost = 109
    """The appliance is performing a defrost to prevent ice accumulation on the outdoor unit."""

    init_completed = 200
    """Initialization complete."""

    init_csu = 201
    """Configuration Storage Unit is being initialized.

    The CSU is a memory module that stores settings and software parameters of the appliance.
    """

    init_identification = 202
    """Initializing identifiers.

    The appliance is discovering installed devices and sensors.
    """

    init_blocking_parameters = 203
    """Blocking parameters are being initialized."""

    init_safety_unit = 204
    """Safety group is being initialized.

    A safety group is a mandatory safety element in your heat pump.
    It combines overpressure protection, a non-return valve and a shut-off valve.
    """

    init_blocking = 205
    """BLocking is being initialized."""

    unknown = 254
    """The substatus is not defined."""

    safety_shutdown = 255
    """The safety group is shut down due to too many resets.

    Wait for 60 minutes and power cycle your appliance.
    """


class Appliance(RemehaComponent):
    """Represents a Remeha appliance.

    An `Appliance` stores information about the appliance that cannot be linked to any of
    the other available api types, like appliance error status or burning hours counters.
    """

    max_span = REMEHA_MAX_SPAN
    register_ranges = ((384, 390), (400, 438), (439, 494), (500, 503), (9230, 9230))

    outside_temperature = int16(address=384, scale=0.01, unit="°C")
    """The outside temperature."""

    season_mode = enum(address=385, enum_type=SeasonalMode, signed=False, nan=0xFF)
    """Which season mode is currently active."""

    summer_winter = uint16(address=386, scale=0.01, writable=True, unit="°C")
    """Upper limit of outdoor temperature for heating (30.5 means disabled)."""

    neutral_band_summer_winter = uint16(address=387, scale=0.01, writable=True, unit="°C")
    """Temperature band below the summer/winter limit within which the appliance
    neither heats nor cools (parameter AP075)."""

    forced_summer_mode = boolean(address=389, nan=0xFF, writable=True)
    """Whether forced summer mode is active (parameter AP074)."""

    flow_temperature = int16(address=400, scale=0.01, unit="°C")
    """Current flow temperature (parameter AM016)."""

    return_temperature = int16(address=401, scale=0.01, unit="°C")
    """Current return temperature (parameter AM018)."""

    heat_pump_flow_temperature = int16(address=403, scale=0.01, unit="°C")
    """Current heat pump flow temperature (parameter HM001)."""

    heat_pump_return_temperature = int16(address=404, scale=0.01, unit="°C")
    """Current heat pump return temperature (parameter HM001)."""

    actual_water_pressure = uint8(address=409, scale=0.1, unit="bar")
    """The actual water pressure measured in bar."""

    flow_rate = uint16(address=410, scale=0.01, unit="L/min")
    """The current flow rate in L/min."""

    appliance_status = enum(address=411, enum_type=ApplianceStatus, nan=0xFF)
    """The current appliance status (parameter AM012)."""

    appliance_substatus = enum(address=412, enum_type=ApplianceSubStatus)
    """The current appliance substatus. Shows details about the current status (parameter AM014)."""

    actual_relative_power = uint16(address=413, scale=0.01, unit="%")
    """The actual relative power being produced (parameter AM024)."""

    generator_starts_total = uint32(address=419, nan=0xFFFFFFFF)
    """The total burner/compressor start count (parameter PC002)."""

    generator_hours_total = uint32(address=421, unit="h", nan=0xFFFFFFFF)
    """The total burner/compressor run time in hours (parameter PC003)."""

    backup1_starts = uint32(address=423, nan=0xFFFFFFFF)
    """The total start count of backup 1 (parameter AC030)."""

    backup1_hours = uint32(address=425, unit="h", nan=0xFFFFFFFF)
    """The total backup1 run time in hours (parameter AC028)."""

    backup2_starts = uint32(address=427, nan=0xFFFFFFFF)
    """The total start count of backup 2 (parameter AC031)."""

    backup2_hours = uint32(address=429, unit="h", nan=0xFFFFFFFF)
    """The total backup2 run time in hours (parameter AC029)."""

    power_on_hours = uint32(address=431, unit="h", nan=0xFFFFFFFF)
    """The total number of hours the appliance was active (parameter AC001)."""

    ch_energy_consumption = uint32(address=433, unit="kWh", nan=0xFFFFFFFF)
    """Total energy consumed for production of central heat (parameter AC005)."""

    dhw_energy_consumption = uint32(address=435, unit="kWh", nan=0xFFFFFFFF)
    """Total energy consumed for production of domestic hot water (parameter AC006)."""

    cooling_energy_consumption = uint32(address=437, unit="kWh", nan=0xFFFFFFFF)
    """Total energy consumed for cooling (parameter AC007)."""

    total_energy_consumption = uint32(address=439, unit="kWh", nan=0xFFFFFFFF)
    """Total energy consumed in the current year."""

    backup_energy_consumption = uint32(address=441, unit="kWh", nan=0xFFFFFFFF)
    """Total energy consumed by electrical or hydraulic backup (parameter AC018)."""

    total_energy_delivery = uint32(address=443, unit="kWh", nan=0xFFFFFFFF)
    """Total energy delivered in the current year."""

    ch_energy_delivery = uint32(address=445, unit="kWh", nan=0xFFFFFFFF)
    """Energy delivered for central heating (parameter AC008)."""

    dhw_energy_delivery = uint32(address=447, unit="kWh", nan=0xFFFFFFFF)
    """Energy delivered for domestic hot water (parameter AC009)."""

    cooling_energy_delivery = uint32(address=449, unit="kWh", nan=0xFFFFFFFF)
    """Energy delivered for cooling (parameter AC010)."""

    backup_energy_delivery = uint32(address=451, unit="kWh", nan=0xFFFFFFFF)
    """Energy delivered for electrical or hydraulic backup (parameter AC019)."""

    pump_speed = uint16(address=459, scale=0.1, unit="%")
    """Current pump speed in percent."""

    actual_produced_power = uint32(address=460, scale=0.01, unit="kWh", nan=0xFFFFFFFF)
    """Signal used to capture actual power calculation."""

    cop_calculated = uint16(address=462, scale=0.001)
    """Instantaneous calculated Coefficient of Performance (COP) (parameter HM031)."""

    silent_mode = enum(address=490, enum_type=SilentMode, signed=False, nan=0xFF, writable=True)
    """The silent mode level of the appliance."""

    silent_mode_start_time = time_steps(address=491, writable=True)
    """The time of day at which the silent mode starts."""

    silent_mode_end_time = time_steps(address=492, writable=True)
    """The time of day at which the silent mode ends."""

    ch_enabled = boolean(address=500, nan=0xFF, writable=True)
    """Whether central heating demand processing is enabled."""

    cooling_type = enum(address=502, enum_type=CoolingType, signed=False, nan=0xFF, writable=True)
    """The type of cooling."""

    forced_cooling_mode = boolean(address=503, nan=0xFF, writable=True)
    """Whether the appliance is in forced cooling mode.

    This variable is defined on the appliance level. In the Remeha Home app however, this variable
    is configurable in two places: in the CH zone and at the system level. Change one, change
    the other too.
    In this integration, this value is shown in all CH climates and can be set as follows:

    * To force cooling, set HVACMode to COOL
    * To let the system decide to cool or heat, set HVACMode to HEAT_COOL
    """

    # TODO This is a register for hybrid appliances. If more are required, move to dedicated class.
    hybrid_cop_calculated = uint16(address=9230, scale=0.001)
    """Instantaneous calculated Coefficient of Performance (COP) on a hybrid system (parameter HM031)."""

    def is_cooling_required(self) -> bool:
        """Whether the appliance cooling mode is required.

        This can be forced (`forced_cooling_mode == True`) or derived (`season_mode` is in a summer variant).
        """

        return self.forced_cooling_mode or self.season_mode in {
            SeasonalMode.SUMMER_NEUTRAL_BAND,
            SeasonalMode.SUMMER,
        }

    async def async_set_summer_winter(self, temperature: float):
        """Set the outdoor temperature upper limit for heating.

        Args:
            temperature (float): The outdoor temperature in °C.

        """

        await self.write("summer_winter", temperature)

    async def async_set_neutral_band_summer_winter(self, bandwidth: float):
        """Set the neutral band in which the heat pump is deactivated.

        Args:
            bandwidth (float): The bandwidth in °C

        """

        await self.write("neutral_band_summer_winter", bandwidth)

    async def async_enable_forced_summer_mode(self):
        """Stop heating, maintain hot water. Force summer mode."""

        await self.write("forced_summer_mode", True)

    async def async_disable_forced_summer_mode(self):
        """Do not force summer mode."""

        await self.write("forced_summer_mode", False)

    async def async_set_silent_mode(self, value: SilentMode):
        """Set the silent mode level.

        Args:
            value (SilentMode): The requested silent mode.

        """
        await self.write("silent_mode", value)

    async def async_set_silent_mode_start_time(self, start_time: time):
        """Set the time of day at which the silent mode starts.

        Args:
            start_time (time): The time at which the silent mode should start.

        """
        await self.write("silent_mode_start_time", start_time)

    async def async_set_silent_mode_end_time(self, end_time: time):
        """Set the time of day at which the silent mode ends.

        Args:
            end_time (time): The time at which the silent mode should end.

        """
        await self.write("silent_mode_end_time", end_time)

    async def async_set_ch_enabled(self):
        """Enable central heat demand processing."""
        await self.write("ch_enabled", True)

    async def async_set_ch_disabled(self):
        """Disable central heat demand processing."""
        await self.write("ch_enabled", False)

    async def async_set_cooling_type(self, value: CoolingType):
        """Set the type of cooling for this appliance.

        Args:
            value (CoolingType): The requested cooling type.

        """
        await self.write("cooling_type", value)

    async def async_enable_forced_cooling_mode(self):
        """Enable forced cooling mode."""

        await self.write("forced_cooling_mode", True)

    async def async_disable_forced_cooling_mode(self):
        """Disable forced cooling mode."""

        await self.write("forced_cooling_mode", False)
