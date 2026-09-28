"""Implementation of time programs in the Remeha Modbus device."""

import datetime
import logging
import math
from dataclasses import dataclass
from typing import Any, Final, Self, cast

from dateutil import parser

from aio_remeha_modbus.gtw08.appliance import SeasonalMode
from aio_remeha_modbus.gtw08.climate_zone import ClimateZoneScheduleId
from aio_remeha_modbus.gtw08.const import (
    AUTO_SCHEDULE_MINIMAL_END_HOUR,
    BOILER_MAX_ALLOWED_HEAT_DURATION,
    MAXIMUM_NORMAL_SURFACE_IRRADIANCE_NL,
    PV_EFFICIENCY_TABLE,
    PV_MAX_TILT_DEGREES,
    WATER_SPECIFIC_HEAT_CAPACITY_KJ,
    BoilerConfiguration,
    BoilerEnergyLabel,
    ForecastField,
    PVSystem,
    UnitOfTemperature,
)
from aio_remeha_modbus.gtw08.errors import AutoSchedulingError
from aio_remeha_modbus.gtw08.time_program import Timeslot, TimeslotActivity, TimeslotSetpointType
from aio_remeha_modbus.helpers.iterators import consecutive_groups

_LOGGER = logging.getLogger(__name__)

AUTO_SCHEDULE_DEFAULT_ID: Final[ClimateZoneScheduleId] = ClimateZoneScheduleId.SCHEDULE_1
"""The default schedule id for auto scheduling."""


def _energy_label_to_heat_loss_rate(label: BoilerEnergyLabel, volume: float) -> float:
    v_pow_04: float = math.pow(volume, 0.4)
    match label:
        case BoilerEnergyLabel.A_PLUS | BoilerEnergyLabel.A:
            return ((5.5 + 3.6 * v_pow_04) + (8.5 + 4.25 * v_pow_04)) * 0.5
        case BoilerEnergyLabel.B:
            return ((8.5 + 4.25 * v_pow_04) + (12 + 5.93 * v_pow_04)) * 0.5
        case BoilerEnergyLabel.C:
            return ((12 + 5.93 * v_pow_04) + (16.66 + 8.33 * v_pow_04)) * 0.5
        case BoilerEnergyLabel.D:
            return ((16.66 + 8.33 * v_pow_04) + (21 + 10.33 * v_pow_04)) * 0.5
        case _:
            return ((21 + 10.33 * v_pow_04) + (26 + 13.66 * v_pow_04)) * 0.5


@dataclass(frozen=True)
class HourlyForecast:
    """An hourly weather forecast entry."""

    start_time: datetime.datetime
    """The start time of the forecast."""

    temperature: float
    """The temperature in `temperature_unit`.

    At temperatures above 25 °C, the PV panel efficiency decreases with 4 percent every 10 degrees.
    """

    solar_irradiance: int | None
    """The global horizontal irradiance, in W/m2."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create a new `HourlyForecast` based on a dict containing weather forecast attributes."""

        return cls(
            start_time=parser.parse(data[ForecastField.DATETIME]),
            temperature=float(data[ForecastField.TEMPERATURE]),
            solar_irradiance=(
                int(data[ForecastField.SOLAR_IRRADIANCE])
                if ForecastField.SOLAR_IRRADIANCE in data
                else None
            ),
        )


@dataclass(frozen=True)
class WeatherForecast:
    """A forecasted weather condition containing the necessary attributes to calculate a schedule."""

    unit_of_temperature: UnitOfTemperature
    """The unit of temperature used in the forecast entries."""

    forecasts: list[HourlyForecast]
    """A list containing the hourly forecasts for the next 24 hours."""


def generate_dhw_day_schedule(
    weather_forecast: WeatherForecast,
    pv_system: PVSystem,
    boiler_config: BoilerConfiguration,
    calorifier_hysteresis: float,
    appliance_seasonal_mode: SeasonalMode | None,
) -> list[Timeslot]:
    """Generate the schedule for the next day, based on the weather forecast.

    Args:
        weather_forecast (WeatherForecast): The weather forecast for the next 24 hours.
        pv_system (PVSystem): The PV system configuration.
        boiler_config (BoilerConfiguration): The DHW boiler configuration.
        calorifier_hysteresis (float): The amount of degrees C the boiler can cool down
            below the setpoint before heating restarts.
        appliance_seasonal_mode (SeasonalMode): The current seasonal mode of the appliance.

    Returns:
        The generated `ZoneSchedule`.

    """
    _LOGGER.info("Generating ZoneSchedule for tomorrow...")

    if not weather_forecast.forecasts:
        raise AutoSchedulingError(translation_key="auto_schedule_no_forecasts")

    # We want to generate a planning for the next whole day, which must, to be useful,
    # end no earlier than `AUTO_SCHEDULE_MINIMAL_END_HOUR`.
    last_forecast: HourlyForecast = weather_forecast.forecasts[-1]
    if last_forecast.start_time.hour < AUTO_SCHEDULE_MINIMAL_END_HOUR:
        raise AutoSchedulingError(
            translation_key="auto_schedule_forecast_not_enough_hours",
            translation_placeholders={
                "max_forecast_time": f"{last_forecast.start_time.hour}:00",
                "min_required_end_time": f"{AUTO_SCHEDULE_MINIMAL_END_HOUR}:00",
            },
        )

    # Calculate the amount of kWh required to heat to boiler to its setpoint, once
    # it reaches the heating threshold, round to two decimals.
    # This value is what we're looking for in the time blocks that we can use to schedule.
    default_required_heating_kwh: float = (
        math.ceil(
            (
                (
                    cast(float, boiler_config.volume)
                    * WATER_SPECIFIC_HEAT_CAPACITY_KJ
                    * cast(float, calorifier_hysteresis)
                )
                / 3600
            )
            * 100
        )
        / 100
    )
    _LOGGER.debug(
        "Default kWh required to heat DHW boiler from setpoint - hysteresis = %.2f",
        default_required_heating_kwh,
    )

    # Calculate the amount of kWh required to heat the boiler if it were to cool overnight,
    # from now until tomorrow 08.00.
    cooling_time_hours: int = int(
        (
            datetime.datetime.combine(
                datetime.date.today() + datetime.timedelta(days=1),
                datetime.time(hour=8),
            )
            - datetime.datetime.now()
        ).total_seconds()
        / 3600
    )
    heat_loss_rate: float = (
        boiler_config.heat_loss_rate
        if boiler_config.heat_loss_rate is not None
        else _energy_label_to_heat_loss_rate(
            label=cast(BoilerEnergyLabel, boiler_config.energy_label),
            volume=cast(float, boiler_config.volume),
        )
    )

    # Emit a warning if the required energy to heat it up again in the morning is too large.
    required_heating_kwh_after_cooling: float = (heat_loss_rate * cooling_time_hours) / 1000
    if required_heating_kwh_after_cooling > default_required_heating_kwh:
        _LOGGER.warning(
            "DHW boiler is likely going to heat up at night, outside of planning schedule."
        )

    # In the summer, only allow DHW heating in the morning and the afternoon.
    # In the winter, only allow DHW heating when it's (possibly) warmest outside.
    # If seasonal mode is unknown, allow heating all day.
    #
    # This prevents heating at night when there's no solar power, and also when
    # central heating or cooling should have priority.
    if appliance_seasonal_mode is None:
        _LOGGER.warning(
            "Your Remeha appliance does not specify a seasonal mode, allowing DHW boiler heating at all hours."
        )

    usable_hours = (
        [range(24)]
        if appliance_seasonal_mode is None
        else (
            [range(10, 23)]
            if appliance_seasonal_mode in {SeasonalMode.SUMMER_NEUTRAL_BAND, SeasonalMode.SUMMER}
            else [range(10, 17)]
        )
    )

    # Calculate static PV system efficiency, based on orientation and tilt.
    # The tilt is rounded up to the next smallest multiple of ten.
    static_pv_efficiency: float = PV_EFFICIENCY_TABLE[pv_system.orientation][
        min(math.ceil(cast(float, pv_system.tilt) / 10) * 10, PV_MAX_TILT_DEGREES)
    ]
    _LOGGER.debug("Static PV efficiency is %.2f", static_pv_efficiency)

    # Calculate dynamic PV system efficiency, using efficiency decrease of its age.
    pv_efficiency: float = static_pv_efficiency
    if pv_system.annual_efficiency_decrease != 0.0:
        system_runtime: datetime.timedelta = datetime.date.today() - cast(
            datetime.date, pv_system.installation_date
        )
        decreased_percent: float = (system_runtime.days / 365) * cast(
            float, pv_system.annual_efficiency_decrease
        )
        pv_efficiency *= (100 - decreased_percent) / 100
        _LOGGER.debug(
            "PV efficiency is %.2f after applying annual efficiency decrease",
            pv_efficiency,
        )

    # This results in a forecasted yield in kWh for all of the 24 hrs
    forecasted_kwh_yield: dict[int, int] = {
        fc.start_time.hour: int(
            (
                (cast(int, fc.solar_irradiance) / MAXIMUM_NORMAL_SURFACE_IRRADIANCE_NL)
                * pv_system.nominal_power
                * pv_efficiency
            )
            / 1000.0
        )
        for fc in weather_forecast.forecasts
        if fc.start_time.hour in [hour for r in usable_hours for hour in r]
    }

    # Generate rolling blocks of BOILER_MAX_ALLOWED_HEAT_DURATION hours which yield
    # enough kWh to heat the boiler up to its setpoint.
    def _generate_acceptable_hour_blocks():
        usable_hours_list = [hour for r in usable_hours for hour in r]
        for idx in range(len(usable_hours_list)):
            hours_subset: list[int] = (
                usable_hours_list[idx : idx + BOILER_MAX_ALLOWED_HEAT_DURATION]
                if len(usable_hours_list) >= idx + BOILER_MAX_ALLOWED_HEAT_DURATION
                else usable_hours_list[idx:]
            )

            # Calculate the total yield in kwh for the 3-hour block
            total_yield: int = sum(forecasted_kwh_yield.get(h, 0) for h in hours_subset)

            if total_yield >= default_required_heating_kwh:
                # Only yield the subset if it is a closed range
                yield (
                    hours_subset
                    if hours_subset[-1] - hours_subset[0] + 1 == len(hours_subset)
                    else []
                )

    # Take two timeslots, allowing for both morning- and afternoon heating.
    # If no timeslots are available, use all usable hours: heating is allowed at any time during the day.
    acceptable_hour_blocks: list[list[int]] = list(_generate_acceptable_hour_blocks())
    accepted_hour_blocks: list[list[int]] = (
        (
            [acceptable_hour_blocks[0]]
            if len(acceptable_hour_blocks) == 1
            else [acceptable_hour_blocks[0], acceptable_hour_blocks[-1]]
        )
        if acceptable_hour_blocks
        else [list(usable_hours[0])]
    )

    # The remaining hours are unaccepted.
    unaccepted_hour_blocks: list[list[int]] = [
        list(group)
        for group in consecutive_groups([
            h for h in range(24) if h not in {hour for r in accepted_hour_blocks for hour in r}
        ])
    ]

    # Generate the timeslots using the accepted hours yielding enough kWh.
    def _generate_timeslots():
        unaccepted_timeslots: list[Timeslot] = [
            Timeslot(
                setpoint_type=TimeslotSetpointType.ECO,
                activity=TimeslotActivity.DHW,
                switch_time=datetime.time(hour=block[0]),
            )
            for block in unaccepted_hour_blocks
        ]

        accepted_timeslots: list[Timeslot] = [
            Timeslot(
                setpoint_type=TimeslotSetpointType.COMFORT,
                activity=TimeslotActivity.DHW,
                switch_time=datetime.time(hour=block[0]),
            )
            for block in accepted_hour_blocks
        ]

        all_timeslots: list[Timeslot] = [*unaccepted_timeslots, *accepted_timeslots]
        all_timeslots.sort()

        yield from all_timeslots

    return list(_generate_timeslots())
