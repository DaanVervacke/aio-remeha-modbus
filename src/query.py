"""Helper script to retrieve modbus components via a cli."""

import argparse
import asyncio
import sys
from datetime import time

from dateutil.tz import gettz
from modbus_connection import ModbusConnectionError, ModbusError
from modbus_connection.cli_helper import (
    CountingUnit,
    add_connection_args,
    connect_from_args,
    print_component,
)
from modbus_connection.model import Component, UpdateReport

from aio_remeha_modbus.gtw08 import GTW08
from aio_remeha_modbus.gtw08.appliance import Appliance
from aio_remeha_modbus.gtw08.climate_zone import ClimateZone
from aio_remeha_modbus.gtw08.main_control_monitoring import MainControlMonitoring
from aio_remeha_modbus.gtw08.system_discovery_table import SystemDiscoveryTable
from aio_remeha_modbus.gtw26 import (
    GTW26,
    GTW26Detection,
    RegisterLayout,
    ScheduleFacade,
)
from aio_remeha_modbus.gtw26.const import MESSAGE_SPACING, Weekday
from aio_remeha_modbus.gtw26.schedule import ComfortPeriod
from aio_remeha_modbus.helpers.modbus import RetryingModbusUnit


def _parse_zones(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Normalize and validate the requested climate zones on ``args``."""
    raw_zones: list[str] = args.zone or []
    if args.gateway == "gtw26":
        zones = [zone.upper() for zone in raw_zones]
        for zone in zones:
            if zone not in {"A", "B", "C"}:
                parser.error(f"invalid --zone {zone!r}: a gtw26 zone is one of A, B or C")
        args.zone = zones
        return

    zone_indices: list[int] = []
    for zone in raw_zones:
        try:
            index = int(zone)
        except ValueError:
            parser.error(f"invalid --zone {zone!r}: a gtw08 zone is a one-based index")
        if index < 1:
            parser.error(f"invalid --zone {index}: a gtw08 zone is a one-based index")
        zone_indices.append(index)
    args.zone = zone_indices


# Flags only the named gateway reads, mirroring the two add_argument_group blocks.
_GTW08_ONLY_FLAGS: tuple[tuple[str, str], ...] = (
    ("mcm", "--mcm"),
    ("appliance", "--appliance"),
)
_GTW26_ONLY_FLAGS: tuple[tuple[str, str], ...] = (
    ("sensors", "--sensors"),
    ("hot_water", "--hot-water"),
    ("settings", "--settings"),
    ("config", "--config"),
    ("outputs", "--outputs"),
    ("service", "--service"),
    ("diagnostics", "--diagnostics"),
    ("schedules", "--schedules"),
    ("layout", "--layout"),
)


def _warn_foreign_flags(args: argparse.Namespace) -> None:
    """Warn on stderr about set flags the selected gateway does not support.

    Scripts may pass flags broadly, so a foreign flag is ignored, not rejected.
    """
    foreign = _GTW08_ONLY_FLAGS if args.gateway == "gtw26" else _GTW26_ONLY_FLAGS
    for attr, option in foreign:
        if getattr(args, attr):
            print(  # noqa: T201
                f"ignoring {option}: not supported by gateway {args.gateway}",
                file=sys.stderr,
            )


def _print_probe_evidence(detection: GTW26Detection) -> None:
    """Print which identity blocks answered for each register layout."""
    for title, blocks in (
        ("base layout", detection.base_probe),
        ("isystem layout", detection.isystem_probe),
    ):
        print(f"{title}:")  # noqa: T201
        for block in blocks:
            line = f"  {block.address}x{block.count}: {block.outcome}"
            if block.error is not None:
                line += f" ({block.error})"
            print(line)  # noqa: T201


def _print_gtw26_header(device: GTW26, detection: GTW26Detection) -> None:
    """Print the detection summary shown above every GTW26 report."""
    layout = device.layout
    assert layout is not None
    generation = f"{device.generation}" if device.generation is not None else "unknown"
    type_code = f"{detection.raw_type_code}" if detection.raw_type_code is not None else "unknown"
    summary = (
        f"GTW26 (layout={layout.name.lower()}, generation={generation}, type code={type_code})"
    )
    detected = RegisterLayout.ISYSTEM if detection.isystem_detected else RegisterLayout.BASE
    if layout is not detected:
        summary += f" [forced layout, detected {detected.name.lower()}]"
    print(summary)  # noqa: T201


def _print_presence(device: GTW26) -> None:
    """Print which optional components answered on this controller."""
    rows: list[tuple[str, bool]] = [
        ("zone_a", device.zone_a_present),
        ("zone_b", device.zone_b_present),
    ]
    if device.layout is RegisterLayout.ISYSTEM:
        rows.append(("zone_c", device.zone_c_present))
    rows.append(("hot_water", device.hot_water_present))
    print("\nPresence")  # noqa: T201
    print("--------")  # noqa: T201
    width = max(len(name) for name, _ in rows)
    for name, present in rows:
        print(f"  {name.ljust(width)}  {'yes' if present else 'no'}")  # noqa: T201


def _print_section(component: Component | None, title: str) -> None:
    """Print one component section, or a note when the layout does not serve it."""
    print("\n")  # noqa: T201
    if component is None:
        print(f"{title}: not available in this layout")  # noqa: T201
        return
    print_component(component, title=title)


_MIDNIGHT = time(0, 0)


def _format_range(period: ComfortPeriod) -> str:
    """Format one comfort period, showing a midnight end as 24:00."""
    tail = "24:00" if period.end == _MIDNIGHT else period.end.strftime("%H:%M")
    return f"{period.start.strftime('%H:%M')}-{tail}"


def _print_schedule_sections(schedule: ScheduleFacade | None) -> None:
    """Print every weekly program as one human-readable line per weekday."""
    if schedule is None:
        _print_section(None, "Schedules")
        return
    print("\nThe schedules below show P4, which is not necessarily the selected program.")  # noqa: T201
    for name, program in schedule.bundles().items():
        week = program.week
        title = f"Schedule {name}"
        print("\n")  # noqa: T201
        print(title)  # noqa: T201
        print("-" * len(title))  # noqa: T201
        for weekday in Weekday:
            ranges = week[weekday]
            shown = ", ".join(_format_range(period) for period in ranges) or ("no comfort periods")
            print(f"  {weekday.name.capitalize().ljust(9)}  {shown}")  # noqa: T201


def _print_gtw26_sections(device: GTW26, args: argparse.Namespace) -> None:
    """Print the requested GTW26 sections, in a fixed order."""
    climate_zones = device.climate_zones
    assert climate_zones is not None
    zone_letters: list[str] = args.zone or (list(climate_zones) if args.all else [])
    sections: list[tuple[bool, str, Component | None]] = [
        (args.sensors, "Sensors", device.sensors),
        (args.hot_water, "Hot Water", device.hot_water),
        *[(True, f"Climate Zone {letter}", climate_zones.get(letter)) for letter in zone_letters],
        (args.settings, "Settings", device.settings),
        (args.config, "Config", device.config),
        (args.outputs, "Outputs", device.outputs),
        (args.service, "Service", device.service),
        (args.diagnostics, "Diagnostics", device.diagnostics),
    ]
    for flag, title, component in sections:
        if args.all or flag:
            _print_section(component, title)
    if args.all or args.schedules:
        _print_schedule_sections(device.schedule)


async def _run_gtw08(args: argparse.Namespace, unit: CountingUnit) -> int:
    """Query the requested components of a GTW08 gateway."""
    zones: list[int] = args.zone
    query_main_control_monitoring: bool = args.mcm
    query_appliance: bool = args.appliance or len(zones) > 0
    query_all: bool = args.all
    appliance: Appliance | None = None

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

        for sequence_id in zones:
            print("\n")  # noqa: T201
            assert appliance is not None
            zone = ClimateZone(
                unit=unit,
                sequence_id=sequence_id,
                time_zone=gettz(args.timezone),
                appliance_requires_cooling=appliance.is_cooling_required,
            )
            await zone.async_update()
            print_component(zone, title=f"Climate Zone {sequence_id}")
    return 0


async def _poll_gtw26_sections(device: GTW26, args: argparse.Namespace) -> UpdateReport:
    """Poll only the sections the CLI prints, plus the always-printed presence data."""
    report = UpdateReport()
    climate_zones = device.climate_zones
    assert climate_zones is not None
    targets: list[tuple[str, Component | None]] = [
        ("identity", device.identity),
        ("hot_water", device.hot_water),
        *[(f"climate_zone_{letter.lower()}", zone) for letter, zone in climate_zones.items()],
    ]
    requested: list[tuple[bool, str, Component | None]] = [
        (args.sensors, "sensors", device.sensors),
        (args.settings, "settings", device.settings),
        (args.config, "config", device.config),
        (args.outputs, "outputs", device.outputs),
        (args.service, "service", device.service),
        (args.diagnostics, "diagnostics", device.diagnostics),
    ]
    targets += [(name, component) for flag, name, component in requested if flag]
    if args.schedules and device.schedule is not None:
        targets += [
            (f"schedules.{name}", program) for name, program in device.schedule.bundles().items()
        ]
    for name, component in targets:
        if component is None:
            continue
        try:
            await component.async_update()
        except ModbusConnectionError:
            raise
        except ModbusError as err:
            report.failed[name] = err
        else:
            report.updated.add(name)
    return report


async def _run_gtw26(args: argparse.Namespace, unit: CountingUnit) -> int:
    """Detect a GTW26 gateway, poll it and print the requested sections."""
    unit.set_message_spacing(MESSAGE_SPACING)
    detection = await GTW26.async_detect(unit)
    if not detection.success:
        print("Could not detect a GTW26 controller.")  # noqa: T201
        _print_probe_evidence(detection)
        return 1

    if args.layout is None:
        # Reuse the device detection constructed, so setup never probes again.
        device = detection.device
        assert device is not None
    else:
        device = GTW26(
            name="cli_api",
            unit=unit,
            layout=RegisterLayout[args.layout.upper()],
            generation=detection.generation,
        )
    await device.async_ensure_setup()
    report = await device.async_update() if args.all else await _poll_gtw26_sections(device, args)

    _print_gtw26_header(device, detection)
    _print_section(device.identity, "Identity")
    _print_presence(device)
    _print_gtw26_sections(device, args)

    if report.failed:
        lines = "\n".join(f"  {name}: {error}" for name, error in report.failed.items())
        print(f"\nFailed bundles ({len(report.failed)}):\n{lines}")  # noqa: T201
    return 0


async def main() -> int:  # noqa: D103
    parser = argparse.ArgumentParser(description="Query a device and print values.")
    add_connection_args(parser)

    parser.add_argument(
        "--gateway",
        choices=("gtw08", "gtw26"),
        default="gtw08",
        help="The gateway type to query (default: gtw08)",
    )
    parser.add_argument("--unit", type=int, default=100, help="Modbus unit id, defaults to 100")
    parser.add_argument(
        "--timezone",
        type=str,
        default=None,
        help="Time zone of your Remeha Appliance. Defaults to your local system time zone.",
    )

    components = parser.add_argument_group(
        title="API component queries",
        description=(
            "Choose the API components you want to query. The System Discovery Table is always"
            " printed for gtw08."
        ),
    )
    components.add_argument(
        "--mcm", action="store_true", default=False, help="The Main Control Monitoring"
    )
    components.add_argument(
        "--appliance",
        action="store_true",
        default=False,
        help="The Appliance. Also retrieved if a zone is requested",
    )
    components.add_argument(
        "--zone",
        action="append",
        metavar="ZONE",
        help=(
            "A climate zone to query: a one-based index for gtw08 (e.g. 2), or one of A, B, C"
            " for gtw26. May be repeated to query multiple zones."
        ),
    )

    gtw26_components = parser.add_argument_group(
        title="GTW26 component queries",
        description=(
            "Choose the GTW26 components you want to query. Detection details, the identity"
            " and the component presence are always printed for gtw26."
        ),
    )
    gtw26_components.add_argument(
        "--sensors", action="store_true", default=False, help="The sensors"
    )
    gtw26_components.add_argument(
        "--hot-water", action="store_true", default=False, help="The hot water"
    )
    gtw26_components.add_argument(
        "--settings", action="store_true", default=False, help="The settings"
    )
    gtw26_components.add_argument(
        "--config", action="store_true", default=False, help="The installer config (iSystem layout)"
    )
    gtw26_components.add_argument(
        "--outputs", action="store_true", default=False, help="The outputs"
    )
    gtw26_components.add_argument(
        "--service", action="store_true", default=False, help="The service menu (base layout)"
    )
    gtw26_components.add_argument(
        "--diagnostics",
        action="store_true",
        default=False,
        help="The diagnostics (iSystem layout)",
    )
    gtw26_components.add_argument(
        "--schedules",
        action="store_true",
        default=False,
        help="The weekly schedules (iSystem layout)",
    )
    gtw26_components.add_argument(
        "--layout",
        choices=("base", "isystem"),
        help="Force the GTW26 register layout instead of relying on auto-detection",
    )

    api_components = parser.add_argument_group(title="All components")
    api_components.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Query all components.",
    )

    args = parser.parse_args()
    _parse_zones(parser, args)
    _warn_foreign_flags(args)

    try:
        conn = await connect_from_args(args)
    except ModbusError as err:
        print(f"Could not connect: {err}")  # noqa: T201
        return 1

    print(f"Time zone: {args.timezone or 'local'}")  # noqa: T201

    retrying_unit = RetryingModbusUnit(conn.for_unit(args.unit))
    unit = CountingUnit(retrying_unit)
    try:
        if args.gateway == "gtw26":
            exit_code = await _run_gtw26(args, unit)
        else:
            exit_code = await _run_gtw08(args, unit)
    finally:
        await conn.close()

    print(f"\n{unit.reads} Modbus reads")  # noqa: T201
    retries = retrying_unit.retries
    if len(retries) > 0:
        msg = "\n".join([str(r) for r in retries])
        print(f"Modbus retries ({len(retries)}):\n{msg}")  # noqa: T201
    return exit_code


def run() -> None:
    """Run the CLI and exit with its status code."""
    raise SystemExit(asyncio.run(main()))


if __name__ == "__main__":
    run()
