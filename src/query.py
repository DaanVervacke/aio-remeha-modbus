"""Helper script to retrieve modbus components via a cli."""

import argparse
import asyncio

from dateutil.tz import gettz, tzlocal
from modbus_connection import ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
    add_connection_args,
    connect_from_args,
    print_component,
)

from aio_remeha_modbus.gtw08 import GTW08
from aio_remeha_modbus.gtw08.appliance import Appliance
from aio_remeha_modbus.gtw08.climate_zone import ClimateZone
from aio_remeha_modbus.gtw08.main_control_monitoring import MainControlMonitoring
from aio_remeha_modbus.gtw08.system_discovery_table import SystemDiscoveryTable
from aio_remeha_modbus.helpers.modbus import RetryingModbusUnit


async def main() -> int:  # noqa: D103  # ruff: ignore[too-many-locals]
    parser = argparse.ArgumentParser(description="Query a device and print values.")
    add_connection_args(parser)

    parser.add_argument("--unit", type=int, default=100, help="Modbus unit id, defaults to 100")
    parser.add_argument(
        "--timezone",
        type=str,
        default=tzlocal().tzname(dt=None),
        help="Time zone of your Remeha Appliance. Defaults to your local system time zone.",
    )

    components = parser.add_argument_group(
        title="API component queries",
        description="Choose the API components you want to query. The System Discovery Table is always printed.",
    )
    components.add_argument(
        "--mcm", action="store_true", default=False, help="The Main Control Monitoring"
    )
    components.add_argument(
        "--appliance",
        action="store_true",
        default=False,
        help="The Appliance. Also retrieved if zone >= 1",
    )
    components.add_argument(
        "--zone", type=int, default=0, help="A Climate Zone (one-based index, default=no zone)"
    )
    api_components = parser.add_argument_group(title="All components")
    api_components.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Query all components.",
    )

    args = parser.parse_args()

    query_main_control_monitoring: bool = args.mcm
    query_appliance: bool = args.appliance or args.zone >= 1
    query_zone: int = args.zone
    query_all: bool = args.all

    try:
        conn = await connect_from_args(args)
    except ModbusError as err:
        print(f"Could not connect: {err}")  # noqa: T201
        return 1

    print(f"Time zone: {args.timezone}")  # noqa: T201

    retrying_unit = RetryingModbusUnit(conn.for_unit(args.unit))
    unit = CountingUnit(retrying_unit)
    try:
        if query_all:
            r = GTW08(name="cli_api", unit=unit, time_zone=gettz(args.timezone))
            await r.async_update()
            print(f"GTW08(name={r.name}, time_zone={r._time_zone})")  # noqa: SLF001, T201
            print("\n")  # noqa: T201
            print_component(r.discovery_table, title="System Discovery Table")
            print("\n")  # noqa: T201
            print_component(r.main_control_monitoring, title="Main Control Monitoring")
            print("\n")  # noqa: T201
            print_component(r.appliance, title="Appliance")
            for zone in r.zones:
                print("\n")  # noqa: T201
                print_component(zone, title=f"Climate Zone {zone.id}")

        else:
            discovery_table = SystemDiscoveryTable(unit=unit)
            await discovery_table.async_update()
            print_component(discovery_table)

            if query_main_control_monitoring:
                print("\n")  # noqa: T201
                main_control_monitoring = MainControlMonitoring(unit=unit)
                await main_control_monitoring.async_update()
                print_component(main_control_monitoring, title="Main Control Monitoring")

            if query_appliance:
                print("\n")  # noqa: T201
                appliance = Appliance(unit=unit)
                await appliance.async_update()
                print_component(appliance, title="Appliance")

            if query_zone >= 1:
                print("\n")  # noqa: T201
                zone = ClimateZone(
                    unit=unit,
                    sequence_id=query_zone,
                    time_zone=gettz(args.timezone),
                    appliance_requires_cooling=appliance.is_cooling_required,
                )
                await zone.async_update()
                print_component(zone, title=f"Climate Zone {query_zone}")

    finally:
        await conn.close()

    print(f"\n{unit.reads} Modbus reads")  # noqa: T201
    retries = retrying_unit.retries
    if len(retries) > 0:
        msg = "\n".join([str(r) for r in retries])
        print(f"Modbus retries ({len(retries)}):\n{msg}")  # noqa: T201
    return 0


raise SystemExit(asyncio.run(main()))
