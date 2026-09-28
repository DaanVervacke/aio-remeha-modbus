"""Tests for time schedules."""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Final

import pytest
from freezegun import freeze_time

from aio_remeha_modbus.gtw08 import GTW08
from aio_remeha_modbus.gtw08.climate_zone import ClimateZoneScheduleId
from aio_remeha_modbus.gtw08.const import (
    BoilerConfiguration,
    BoilerEnergyLabel,
    PVSystem,
    PVSystemOrientation,
    UnitOfTemperature,
)
from aio_remeha_modbus.gtw08.errors import AutoSchedulingError
from aio_remeha_modbus.gtw08.schedule import (
    AUTO_SCHEDULE_DEFAULT_ID,
    HourlyForecast,
    SeasonalMode,
    Timeslot,
    TimeslotActivity,
    TimeslotSetpointType,
    WeatherForecast,
    _energy_label_to_heat_loss_rate,
    generate_dhw_day_schedule,
)
from tests.conftest import json_fixture


@pytest.mark.asyncio
async def test_generate_dhw_time_schedule(gtw_08: GTW08):
    """Test generating a time schedule for heating the DHW boiler."""

    weather_forecast: WeatherForecast = WeatherForecast(
        unit_of_temperature=UnitOfTemperature.CELSIUS,
        forecasts=[
            HourlyForecast.from_dict(native_forecast)
            for native_forecast in json_fixture("weather_forecast.json")
        ],
    )

    pv_system: PVSystem = PVSystem(
        nominal_power=5720,
        orientation=PVSystemOrientation.SOUTH,
        annual_efficiency_decrease=0.42,
        installation_date=date.today(),
        tilt=30.0,
    )

    boiler_config: BoilerConfiguration = BoilerConfiguration(
        volume=300, heat_loss_rate=None, energy_label=BoilerEnergyLabel.C
    )

    appliance = gtw_08.appliance
    zone = gtw_08.zones[1]
    assert zone is not None

    schedule = generate_dhw_day_schedule(
        weather_forecast=weather_forecast,
        pv_system=pv_system,
        boiler_config=boiler_config,
        calorifier_hysteresis=4.0,
        appliance_seasonal_mode=appliance.season_mode,
    )

    assert schedule == [
        Timeslot(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("00:00"),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.COMFORT,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("10:00"),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("13:00"),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.COMFORT,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("18:00"),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("21:00"),
        ),
    ]


@pytest.mark.asyncio
async def test_generate_dhw_time_schedule_without_solar_yield(gtw_08: GTW08):
    """Test generating a time schedule for heating the DHW boiler on a day there is no solar yield."""

    weather_forecast: WeatherForecast = WeatherForecast(
        unit_of_temperature=UnitOfTemperature.CELSIUS,
        forecasts=[
            HourlyForecast.from_dict(native_forecast)
            for native_forecast in json_fixture("weather_forecast_no_sun.json")
        ],
    )

    pv_system: PVSystem = PVSystem(
        nominal_power=5720,
        orientation=PVSystemOrientation.SOUTH,
        annual_efficiency_decrease=0.42,
        installation_date=date.today(),
        tilt=30.0,
    )

    boiler_config: BoilerConfiguration = BoilerConfiguration(
        volume=300, heat_loss_rate=91.3, energy_label=None
    )

    appliance = gtw_08.appliance
    zone = gtw_08.zones[1]
    assert zone is not None

    schedule = generate_dhw_day_schedule(
        weather_forecast=weather_forecast,
        pv_system=pv_system,
        boiler_config=boiler_config,
        calorifier_hysteresis=4.0,
        appliance_seasonal_mode=appliance.season_mode,
    )

    assert schedule == [
        Timeslot(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("00:00"),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.COMFORT,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("10:00"),
        ),
        Timeslot(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=TimeslotActivity.DHW,
            switch_time=time.fromisoformat("23:00"),
        ),
    ]


_FROZEN_NOW: Final[str] = "2026-06-01 20:00:00"


def _forecast(irradiance_by_hour: dict[int, int] | None = None, *, last_hour: int = 23):
    """Create a weather forecast that runs from 00:00 until `last_hour`.

    Args:
        irradiance_by_hour: The solar irradiance in W/m² per hour, all other hours have none.
        last_hour: The hour of the last forecast entry.

    """

    irradiance_by_hour = irradiance_by_hour or {}
    return WeatherForecast(
        unit_of_temperature=UnitOfTemperature.CELSIUS,
        forecasts=[
            HourlyForecast.from_dict({
                "datetime": f"2026-06-02T{hour:02d}:00:00+02:00",
                "temperature": 20.0,
                "solar_irradiance": irradiance_by_hour.get(hour, 0),
            })
            for hour in range(last_hour + 1)
        ],
    )


def _pv_system(**overrides: Any) -> PVSystem:
    """Create a PV system that yields multiple kWh per hour in full sun."""

    parameters: dict[str, Any] = {
        "nominal_power": 5720,
        "orientation": PVSystemOrientation.SOUTH,
        "annual_efficiency_decrease": 0.0,
        "installation_date": date(2026, 6, 1),
        "tilt": 30.0,
    }
    return PVSystem(**{**parameters, **overrides})


def _boiler(**overrides: Any) -> BoilerConfiguration:
    """Create a 300 litre boiler with a fixed heat loss rate."""

    parameters: dict[str, Any] = {
        "volume": 300,
        "heat_loss_rate": 91.3,
        "energy_label": None,
    }
    return BoilerConfiguration(**{**parameters, **overrides})


def _schedule(
    forecast: WeatherForecast,
    season: SeasonalMode | None,
    *,
    pv_system: PVSystem | None = None,
    boiler: BoilerConfiguration | None = None,
) -> list[tuple[str, str]]:
    """Generate a schedule and reduce it to (setpoint type, switch time) tuples."""

    slots = generate_dhw_day_schedule(
        weather_forecast=forecast,
        pv_system=pv_system or _pv_system(),
        boiler_config=boiler or _boiler(),
        calorifier_hysteresis=4.0,
        appliance_seasonal_mode=season,
    )
    assert all(slot.activity is TimeslotActivity.DHW for slot in slots)
    return [(slot.setpoint_type.name, slot.switch_time.strftime("%H:%M")) for slot in slots]


def test_hourly_forecast_from_dict():
    """Test that a forecast is created from a weather forecast entry."""

    forecast = HourlyForecast.from_dict({
        "datetime": "2026-06-02T13:00:00+02:00",
        "temperature": "21.5",
        "solar_irradiance": "640",
        "condition": "sunny",
    })

    assert forecast.start_time == datetime(2026, 6, 2, 13, tzinfo=timezone(timedelta(hours=2)))
    assert forecast.temperature == 21.5
    assert forecast.solar_irradiance == 640


def test_hourly_forecast_from_dict_without_solar_irradiance():
    """Test that the solar irradiance is optional."""

    forecast = HourlyForecast.from_dict({"datetime": "2026-06-02T13:00:00", "temperature": 21})

    assert forecast.temperature == 21.0
    assert forecast.solar_irradiance is None


def test_hourly_forecast_from_dict_missing_fields():
    """Test that the datetime and temperature are required."""

    with pytest.raises(KeyError):
        HourlyForecast.from_dict({"temperature": 21})

    with pytest.raises(KeyError):
        HourlyForecast.from_dict({"datetime": "2026-06-02T13:00:00"})


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        (BoilerEnergyLabel.A_PLUS, 7.0 + 3.925 * 100**0.4),
        (BoilerEnergyLabel.B, 10.25 + 5.09 * 100**0.4),
        (BoilerEnergyLabel.C, 14.33 + 7.13 * 100**0.4),
        (BoilerEnergyLabel.D, 18.83 + 9.33 * 100**0.4),
        (BoilerEnergyLabel.E, 23.5 + 11.995 * 100**0.4),
    ],
)
def test_energy_label_to_heat_loss_rate(label: BoilerEnergyLabel, expected: float):
    """Test the heat loss rate, which is the mean of the lower and upper bound of the label."""

    assert _energy_label_to_heat_loss_rate(label, 100) == pytest.approx(expected)


def test_energy_label_to_heat_loss_rate_ordering():
    """Test that a worse label has a higher heat loss rate and that some labels share a value."""

    rates = [_energy_label_to_heat_loss_rate(label, 200) for label in BoilerEnergyLabel]

    assert _energy_label_to_heat_loss_rate(
        BoilerEnergyLabel.A_PLUS, 200
    ) == _energy_label_to_heat_loss_rate(BoilerEnergyLabel.A, 200)
    assert _energy_label_to_heat_loss_rate(
        BoilerEnergyLabel.E, 200
    ) == _energy_label_to_heat_loss_rate(BoilerEnergyLabel.F, 200)
    assert rates == sorted(rates)
    assert len(set(rates)) == 5


def test_generate_schedule_without_forecasts():
    """Test that at least one forecast is required."""

    forecast = WeatherForecast(unit_of_temperature=UnitOfTemperature.CELSIUS, forecasts=[])

    with pytest.raises(AutoSchedulingError) as exc_info:
        _schedule(forecast, SeasonalMode.SUMMER)

    assert exc_info.value.translation_key == "auto_schedule_no_forecasts"


def test_generate_schedule_forecast_ends_too_early():
    """Test that a forecast that doesn't reach into the evening is refused."""

    with pytest.raises(AutoSchedulingError) as exc_info:
        _schedule(_forecast(last_hour=20), SeasonalMode.SUMMER)

    assert exc_info.value.translation_key == "auto_schedule_forecast_not_enough_hours"
    assert exc_info.value.translation_placeholders == {
        "max_forecast_time": "20:00",
        "min_required_end_time": "21:00",
    }


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_forecast_ends_at_minimal_hour():
    """Test that a forecast ending at the minimal end hour is accepted."""

    assert _schedule(_forecast(last_hour=21), SeasonalMode.SUMMER)


@freeze_time(_FROZEN_NOW)
@pytest.mark.parametrize(
    ("season", "expected"),
    [
        # No sun: heating is allowed during all usable hours of the season.
        (None, [("COMFORT", "00:00")]),
        (SeasonalMode.WINTER, [("ECO", "00:00"), ("COMFORT", "10:00"), ("ECO", "17:00")]),
        (
            SeasonalMode.WINTER_FROST_PROTECTION,
            [("ECO", "00:00"), ("COMFORT", "10:00"), ("ECO", "17:00")],
        ),
        (
            SeasonalMode.SUMMER_NEUTRAL_BAND,
            [("ECO", "00:00"), ("COMFORT", "10:00"), ("ECO", "23:00")],
        ),
        (SeasonalMode.SUMMER, [("ECO", "00:00"), ("COMFORT", "10:00"), ("ECO", "23:00")]),
    ],
)
def test_generate_schedule_without_sun_per_season(
    season: SeasonalMode | None, expected: list[tuple[str, str]]
):
    """Test the usable hours for every seasonal mode when the sun doesn't yield anything."""

    assert _schedule(_forecast(), season) == expected


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_sun_in_two_periods():
    """Test that a morning and an afternoon block are used if both yield enough."""

    forecast = _forecast({12: 1000, 13: 1000, 14: 1000})

    assert _schedule(forecast, SeasonalMode.WINTER) == [
        ("ECO", "00:00"),
        ("COMFORT", "10:00"),
        ("ECO", "13:00"),
        ("COMFORT", "14:00"),
        ("ECO", "17:00"),
    ]


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_single_acceptable_block():
    """Test that a single acceptable block is used once if only one block yields enough."""

    forecast = _forecast({10: 1000})

    assert _schedule(forecast, SeasonalMode.WINTER) == [
        ("ECO", "00:00"),
        ("COMFORT", "10:00"),
        ("ECO", "13:00"),
    ]


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_ignores_irradiance_outside_usable_hours():
    """Test that sun outside of the usable hours doesn't produce an acceptable block."""

    forecast = _forecast({6: 1000, 7: 1000, 20: 1000})

    assert _schedule(forecast, SeasonalMode.WINTER) == [
        ("ECO", "00:00"),
        ("COMFORT", "10:00"),
        ("ECO", "17:00"),
    ]


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_uses_boiler_energy_label():
    """Test that the energy label is used if there is no heat loss rate."""

    forecast = _forecast({12: 1000})
    label_boiler = _boiler(heat_loss_rate=None, energy_label=BoilerEnergyLabel.C)

    assert _schedule(forecast, SeasonalMode.WINTER, boiler=label_boiler) == _schedule(
        forecast, SeasonalMode.WINTER
    )


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_yield_depends_on_boiler_size():
    """Test that a bigger boiler needs more solar yield before a block is acceptable."""

    # An hour of 1000 W/m² gives about 5 kWh. A 300 L boiler needs 1.4 kWh, a 30000 L boiler 139 kWh.
    forecast = _forecast({10: 1000})

    small = _schedule(forecast, SeasonalMode.WINTER, boiler=_boiler(volume=300))
    large = _schedule(forecast, SeasonalMode.WINTER, boiler=_boiler(volume=30000))

    assert small == [("ECO", "00:00"), ("COMFORT", "10:00"), ("ECO", "13:00")]
    assert large == [("ECO", "00:00"), ("COMFORT", "10:00"), ("ECO", "17:00")]


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_tilt_is_limited():
    """Test that a tilt above the maximum uses the efficiency of the maximum tilt."""

    forecast = _forecast({12: 1000})

    assert _schedule(forecast, SeasonalMode.WINTER, pv_system=_pv_system(tilt=95.0)) == _schedule(
        forecast, SeasonalMode.WINTER, pv_system=_pv_system(tilt=90.0)
    )


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_tilt_is_rounded_up():
    """Test that a tilt that isn't a multiple of ten is rounded up to the next multiple."""

    forecast = _forecast({12: 1000})

    assert _schedule(forecast, SeasonalMode.WINTER, pv_system=_pv_system(tilt=21.0)) == _schedule(
        forecast, SeasonalMode.WINTER, pv_system=_pv_system(tilt=30.0)
    )


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_efficiency_decrease():
    """Test that an ageing PV system yields less and might not reach the required kWh."""

    forecast = _forecast({10: 1000})
    # 2400 Wp * 0.9x efficiency gives 2 kWh in full sun, which is enough for a 300 L boiler.
    new_system = _pv_system(nominal_power=2400)
    old_system = _pv_system(
        nominal_power=2400,
        annual_efficiency_decrease=10.0,
        installation_date=date(2021, 6, 1),
    )

    assert _schedule(forecast, SeasonalMode.WINTER, pv_system=new_system) == [
        ("ECO", "00:00"),
        ("COMFORT", "10:00"),
        ("ECO", "13:00"),
    ]
    assert _schedule(forecast, SeasonalMode.WINTER, pv_system=old_system) == [
        ("ECO", "00:00"),
        ("COMFORT", "10:00"),
        ("ECO", "17:00"),
    ]


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_warns_about_heating_at_night(caplog: pytest.LogCaptureFixture):
    """Test that a warning is logged if the boiler will likely reheat overnight."""

    with caplog.at_level(logging.WARNING):
        _schedule(_forecast(), SeasonalMode.WINTER, boiler=_boiler(heat_loss_rate=500.0))

    assert "likely going to heat up at night" in caplog.text


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_no_warning_when_boiler_holds_heat(caplog: pytest.LogCaptureFixture):
    """Test that no warning is logged if the boiler keeps its heat overnight."""

    with caplog.at_level(logging.WARNING):
        _schedule(_forecast(), SeasonalMode.WINTER, boiler=_boiler(heat_loss_rate=10.0))

    assert "likely going to heat up at night" not in caplog.text


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_warns_without_seasonal_mode(caplog: pytest.LogCaptureFixture):
    """Test that a warning is logged if the seasonal mode is not known."""

    with caplog.at_level(logging.WARNING):
        _schedule(_forecast(), None)

    assert "does not specify a seasonal mode" in caplog.text


@freeze_time(_FROZEN_NOW)
def test_generate_schedule_is_sorted():
    """Test that the generated timeslots are sorted by switch time."""

    slots = generate_dhw_day_schedule(
        weather_forecast=_forecast({12: 1000, 13: 1000, 14: 1000}),
        pv_system=_pv_system(),
        boiler_config=_boiler(),
        calorifier_hysteresis=4.0,
        appliance_seasonal_mode=SeasonalMode.WINTER,
    )

    assert slots == sorted(slots)


def test_auto_schedule_default_id():
    """Test that the default schedule for auto scheduling is the first schedule."""

    assert AUTO_SCHEDULE_DEFAULT_ID is ClimateZoneScheduleId.SCHEDULE_1
