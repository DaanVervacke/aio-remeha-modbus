# Async I/O  modbus API for Remeha appliances

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./assets/dark_logo.png">
  <img alt="Remeha logo" src="./assets/logo.png">
</picture>

![GitHub License](https://img.shields.io/github/license/houthacker/aio-remeha-modbus)
[![ci](https://github.com/houthacker/aio-remeha-modbus/actions/workflows/ci.yaml/badge.svg)](https://github.com/houthacker/aio-remeha-modbus/actions/workflows/ci.yaml)
[![badge](https://img.shields.io/endpoint?url=https%3A%2F%2Fgist.githubusercontent.com%2Fhouthacker%2Fab326b4825c5466a103921f42bf79ba9%2Fraw%2F55fa764f342a9495744ae834408c5768a3242711%2Faio-remeha-modbus-cov-badge.json
)](https://github.com/houthacker/aio-remeha-modbus/actions/workflows/coverage.yaml)

`aio-remeha-modbus` is an async python API for Remeha appliances.

## Installation
Add this library to your project from [PyPI](https://pypi.org) using
```bash
$ uv add aio-remeha-modbus>=4.0.0
```

or build it locally by checking out the source of this project and
```bash
$ uv build
...
$ uv pip install dist/*.whl
```

## Exposed API
The API is documented at [readthedocs](https://aio-remeha-modbus.readthedocs.io/en/latest/). A short textual description of the most important classes and their hierarchy is shown below.

## cli tool
This library also includes a cli tool to query your Remeha appliance. After installing this library, you can use `remeha-query` or if you prefer, you can run it from the cli yourself using `python src/query.py`.

### Examples
Query the 2nd zone of an appliance that uses an RTU over TCP connection at `192.168.1.2` and port 8899:
```bash
$ remeha-query --transport serial socket://192.168.1.2:8899 --zone 2
```

Query all components
```bash
$ remeha-query --transport serial socket://192.168.1.2:8899 --all
```

Query all components of a GTW-26 appliance. The register layout (`base` or `isystem`) is detected automatically:
```bash
$ remeha-query --gateway gtw26 --transport serial socket://192.168.1.2:8899 --all
```

Query the sensors and climate zone A of a GTW-26 appliance:
```bash
$ remeha-query --gateway gtw26 --transport serial socket://192.168.1.2:8899 --sensors --zone A
```

### GTW-08 detection
To detect if a GTW-08 is behind a `ModbusUnit`, call `await GTW08.async_detect()`.

### Caching
To retrieve fetch data from modbus, call `await GTW08.async_update()` explicitly. After that, the values are retained until the next update call.

The discovery table in `GTW08.discovery_table` is only read at the first call to `async_update()`. To re-read the discovery table, restart the process running this API.

### Error handling
All errors raised by this library are intended to be translated.
To facilitate that, the base error class contains a `translation_key` field to look up the translation
and a `translation_placeholders` field. This is a `dict` to be used when extrapolating the error message.

### Configuration
`aio-remeha-modbus` uses [modbus-connection](https://pypi.org/project/modbus-connection/) to talk
to your appliances, and is agnostic to the way a connection is obtained.

To create a new api instance, you need to obtain a `ModbusUnit` first. See [the modbus-connection docs](https://home-assistant-libs.github.io/modbus-connection/connection/connections-and-units/)
on how to do that.

### GTW-08 device
To create a new API instance, provide the `ModbusUnit` instance to the `GTW08` constructor.

### Appliance
The connected Remeha appliance can be retrieved using `GTW08.appliance`.

### ClimateZone
Zones, as they are configured in the Remeha appliance are exposed as `ClimateZone` instances
and can be retrieved using `GTW08.zones`.

### Zone schedules
When a `ClimateZone` is read from the appliance and its `mode` is `ClimateZoneMode.SCHEDULING`,
the schedules for each `Weekday` are available through `ClimateZone.current_schedule` as
instances of `gtw08.time_program.TimeProgram`.

### GTW-26 detection
To detect a GTW-26 controller behind a `ModbusUnit`, call `await GTW26.async_detect()`. Like its GTW-08
counterpart, the returned `GTW26Detection` carries `success` and a `failure_reason` instead of raising for
wrong-device answers; only transient `ModbusError`s propagate. The register layout (`base` or `isystem`)
and the controller generation are detected automatically; pass a `RegisterLayout` to the `GTW26`
constructor to override the detected layout.

GTW-26 controllers need at least 50 ms between Modbus messages. The `GTW26` constructor applies
this spacing automatically through its `message_spacing_seconds` parameter; pass a different value
to override it.

### GTW-26 device
To create a new API instance, provide the `ModbusUnit` instance to the `GTW26` constructor.
Components like `GTW26.sensors`, `GTW26.hot_water` and `GTW26.climate_zones` are available after
`await GTW26.async_update()`.

### GTW-26 climate zones
Zones are exposed as `ClimateZone` instances keyed `A` and `B` through `GTW26.climate_zones`;
zone `C` only exists on `isystem` layouts. The `zone_a_present`, `zone_b_present`, `zone_c_present`
and `hot_water_present` properties report whether the component reported a sensor reading (a
non-`None` decoded value); all of them return `False` until the first `await GTW26.async_update()`
call. The `force_zone_a`, `force_zone_b` and `force_zone_c` constructor flags report a zone as
present even without a sensor reading; passing `force_zone_c=True` together with an explicit
`layout="base"` raises `ValueError`.

### GTW-26 schedules
Weekly comfort schedules are available through `GTW26.schedule` as a `ScheduleFacade` on `isystem`
layouts; it is `None` on `base` layouts. `GTW26.schedule.get_week("hot_water")` returns the
`ComfortPeriod` slots for each day, keyed by the zero-based, Monday-first `Weekday` enum. A period
ending at `time(0, 0)` runs to the end of the day. The facade supports the `hot_water`,
`circuit_a_p4`, `circuit_b_p4`, `circuit_c_p4` and `auxiliary` programs.
