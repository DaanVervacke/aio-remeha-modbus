"""Tests for the remeha-query CLI."""

import argparse
import pathlib
import re
import runpy
import sys
from collections.abc import Callable
from datetime import time
from typing import Any, Final

import pytest
from modbus_connection import ModbusConnectionError, ModbusError
from modbus_connection.cli_helper import CountingUnit
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import MockModbusConnection, MockModbusUnit

import query
from aio_remeha_modbus.gtw26.schedule import ComfortPeriod
from tests.conftest import load_modbus_store

_CLI_UNIT_ID: Final = 100  # the --unit default main() connects with


def _isystem_seed(unit: MockModbusUnit) -> None:
    """Seed the identity and live registers an iSystem detection and poll need."""
    unit.holding.update({
        3: 400,
        4: 14,
        5: 30,
        6: 2,
        108: 10,
        109: 9,
        110: 25,
        457: 24,  # type code for generation 4
        600: 412,
        601: 205,
        602: 650,
        614: 210,
        679: 12,
        680: 30,
        681: 2,
        682: 10,
        683: 9,
        684: 25,
    })


def _base_seed(unit: MockModbusUnit) -> None:
    """Seed the registers a forced base-layout setup and poll need."""
    # The base-layout registers from tests/gtw26/test_gtw26.py, minus the
    # identity registers _isystem_seed already provides.
    unit.holding.update({
        7: 205,
        14: 550,
        17: 0x58,
        18: 210,
        27: 0xFFFF,
        30: 0xFFFF,
        31: 0xFFFF,
        32: 0xFFFF,
        33: 0xFFFF,
        59: 550,
        60: 0,
        62: 500,
        75: 650,
        102: 175,
        116: 0x0005,
        121: 800,
        427: 0x38,
        453: 0xFFFF,
        455: 3000,
        456: 15,
        459: 505,
        462: 700,
        463: 42,
        465: 0xFFFF,
        467: 0x8000 | 120,
        470: 195,
        471: 250,
    })


@pytest.fixture
def cli_connection(monkeypatch: pytest.MonkeyPatch) -> MockModbusConnection:
    """Serve main() an in-memory connection instead of opening a transport."""
    connection = MockModbusConnection()

    async def connect(args: argparse.Namespace) -> MockModbusConnection:
        return connection

    monkeypatch.setattr(query, "connect_from_args", connect)
    return connection


def _cli_args(**overrides: Any) -> argparse.Namespace:
    """Build the namespace main() produces, with the gateway defaults."""
    args: dict[str, Any] = {
        "gateway": "gtw26",
        "layout": None,
        "all": False,
        "zone": None,
        "sensors": False,
        "hot_water": False,
        "settings": False,
        "config": False,
        "outputs": False,
        "service": False,
        "diagnostics": False,
        "schedules": False,
        "mcm": False,
        "appliance": False,
        "timezone": None,
    }
    args.update(overrides)
    return argparse.Namespace(**args)


@pytest.mark.parametrize(
    ("gateway", "zones", "expected"),
    [
        pytest.param("gtw26", ["a", "B"], ["A", "B"], id="gtw26-normalizes-designations"),
        pytest.param("gtw26", ["a", "a"], ["A", "A"], id="gtw26-keeps-repeated-zones"),
        pytest.param("gtw26", None, [], id="gtw26-without-zones"),
        pytest.param("gtw08", ["1", "2"], [1, 2], id="gtw08-converts-indices"),
        pytest.param("gtw08", None, [], id="gtw08-without-zones"),
    ],
)
def test_parse_zones_accepts_valid_input(
    gateway: str, zones: list[str] | None, expected: list[str] | list[int]
) -> None:
    parser = argparse.ArgumentParser()
    args = argparse.Namespace(gateway=gateway, zone=zones)

    query._parse_zones(parser, args)  # noqa: SLF001

    assert args.zone == expected


@pytest.mark.parametrize(
    ("gateway", "zones"),
    [
        pytest.param("gtw26", ["D"], id="gtw26-rejects-unknown-designation"),
        pytest.param("gtw08", ["x"], id="gtw08-rejects-non-numeric"),
        pytest.param("gtw08", ["0"], id="gtw08-rejects-zero"),
        pytest.param("gtw08", ["-1"], id="gtw08-rejects-negative"),
    ],
)
def test_parse_zones_rejects_invalid_input(gateway: str, zones: list[str]) -> None:
    parser = argparse.ArgumentParser()
    args = argparse.Namespace(gateway=gateway, zone=zones)

    with pytest.raises(SystemExit):
        query._parse_zones(parser, args)  # noqa: SLF001


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        pytest.param(ComfortPeriod(time(6, 0), time(8, 30)), "06:00-08:30", id="plain"),
        pytest.param(ComfortPeriod(time(22, 0), time(0, 0)), "22:00-24:00", id="midnight-end"),
        pytest.param(ComfortPeriod(time(0, 0), time(0, 0)), "00:00-24:00", id="midnight-span"),
    ],
)
def test_format_range(period: ComfortPeriod, expected: str) -> None:
    assert query._format_range(period)  # noqa: SLF001 == expected


@pytest.mark.asyncio
async def test_run_gtw26_prints_report_and_exits_zero(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    _isystem_seed(mock_modbus_unit)

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(all=True), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "GTW26 (layout=isystem, generation=4, type code=24)" in out
    assert "Presence" in out


@pytest.mark.asyncio
async def test_run_gtw26_reports_detection_failure(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    for address in (3, 108, 457, 600, 679):
        mock_modbus_unit.fail_read(address, IllegalDataAddressError())

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Could not detect a GTW26 controller." in out
    assert "base layout:" in out
    assert "isystem layout:" in out


@pytest.mark.asyncio
async def test_run_gtw26_prints_failed_bundle_summary(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    _isystem_seed(mock_modbus_unit)
    mock_modbus_unit.fail_read(601, IllegalDataAddressError())

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(all=True), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Failed bundles (1):" in out
    assert "sensors:" in out


@pytest.mark.parametrize(
    ("gateway", "overrides", "expected_warnings"),
    [
        pytest.param(
            "gtw08",
            {"sensors": True},
            ["ignoring --sensors: not supported by gateway gtw08"],
            id="gtw08-warns-about-gtw26-flag",
        ),
        pytest.param(
            "gtw08",
            {"schedules": True, "layout": "base"},
            [
                "ignoring --schedules: not supported by gateway gtw08",
                "ignoring --layout: not supported by gateway gtw08",
            ],
            id="gtw08-warns-about-every-foreign-flag",
        ),
        pytest.param(
            "gtw26",
            {"mcm": True},
            ["ignoring --mcm: not supported by gateway gtw26"],
            id="gtw26-warns-about-gtw08-flag",
        ),
        pytest.param(
            "gtw26",
            {"appliance": True},
            ["ignoring --appliance: not supported by gateway gtw26"],
            id="gtw26-warns-about-appliance",
        ),
        pytest.param("gtw08", {"mcm": True, "appliance": True}, [], id="gtw08-accepts-own-flags"),
        pytest.param(
            "gtw26",
            {"sensors": True, "layout": "isystem"},
            [],
            id="gtw26-accepts-own-flags",
        ),
    ],
)
def test_warn_foreign_flags(
    gateway: str,
    overrides: dict[str, Any],
    expected_warnings: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    query._warn_foreign_flags(_cli_args(gateway=gateway, **overrides))  # noqa: SLF001

    assert capsys.readouterr().err.splitlines() == expected_warnings


@pytest.mark.asyncio
async def test_run_gtw26_detection_failure_prints_successful_probe_blocks(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    """A block that answered has no error suffix, even when detection fails."""
    _isystem_seed(mock_modbus_unit)
    for address in (457, 600, 679):
        mock_modbus_unit.fail_read(address, IllegalDataAddressError())

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "  3x4: success" in out
    assert "  108x3: success" in out
    assert "  457x1: unsupported (Device returned Modbus exception code 2)" in out


@pytest.mark.asyncio
async def test_run_gtw26_forced_base_layout_on_isystem_controller(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    """A forced base layout reports the mismatch and the base presence rows."""
    _isystem_seed(mock_modbus_unit)
    _base_seed(mock_modbus_unit)

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(layout="base", sensors=True, schedules=True), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "GTW26 (layout=base, generation=4, type code=24)" in out
    assert "[forced layout, detected isystem]" in out
    assert "zone_c" not in out
    assert "Schedules: not available in this layout" in out


@pytest.mark.asyncio
async def test_run_gtw26_prints_only_requested_sections(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    """Selective flags print only those sections, plus the always-printed ones."""
    _isystem_seed(mock_modbus_unit)

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(sensors=True, schedules=True, zone=["A"]), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Sensors" in out
    assert "Climate Zone A" in out
    assert "Schedule circuit_a_p4" in out
    assert "Hot Water" not in out
    assert "Settings" not in out


@pytest.mark.asyncio
async def test_run_gtw26_skips_sections_missing_in_layout(
    mock_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    """A section the layout does not serve is skipped while polling and noted when printing."""
    _isystem_seed(mock_modbus_unit)

    exit_code = await query._run_gtw26(  # noqa: SLF001
        _cli_args(service=True), CountingUnit(mock_modbus_unit)
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Service: not available in this layout" in out


@pytest.mark.asyncio
async def test_run_gtw26_reraises_connection_errors(mock_modbus_unit: MockModbusUnit) -> None:
    """Connection-level errors abort the run instead of degrading the report."""
    _isystem_seed(mock_modbus_unit)
    mock_modbus_unit.fail_read(601, ModbusConnectionError())

    with pytest.raises(ModbusConnectionError):
        await query._run_gtw26(  # noqa: SLF001
            _cli_args(sensors=True), CountingUnit(mock_modbus_unit)
        )


@pytest.mark.asyncio
async def test_run_gtw08_all_prints_every_component(
    remeha_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = await query._run_gtw08(  # noqa: SLF001
        _cli_args(gateway="gtw08", all=True, zone=[], timezone="Europe/Amsterdam"),
        CountingUnit(remeha_modbus_unit),
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "GTW08(name=cli_api" in out
    assert "System Discovery Table" in out
    assert "Main Control Monitoring" in out
    assert "Appliance" in out
    assert "Climate Zone 1" in out
    assert "Climate Zone 2" in out


@pytest.mark.asyncio
async def test_run_gtw08_selective_prints_requested_components(
    remeha_modbus_unit: MockModbusUnit, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = await query._run_gtw08(  # noqa: SLF001
        _cli_args(gateway="gtw08", mcm=True, appliance=True, zone=[1, 2]),
        CountingUnit(remeha_modbus_unit),
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Main Control Monitoring" in out
    assert "Appliance" in out
    assert "Climate Zone 1" in out
    assert "Climate Zone 2" in out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("seed", "argv", "expected_output"),
    [
        pytest.param(
            _isystem_seed,
            ["remeha-query", "localhost", "--gateway", "gtw26", "--sensors"],
            "GTW26 (layout=isystem, generation=4, type code=24)",
            id="gtw26",
        ),
        pytest.param(
            load_modbus_store,
            ["remeha-query", "localhost"],
            "SystemDiscoveryTable",
            id="gtw08",
        ),
    ],
)
async def test_main_queries_gateway_and_exits_zero(
    cli_connection: MockModbusConnection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    seed: Callable[[MockModbusUnit], None],
    argv: list[str],
    expected_output: str,
) -> None:
    seed(cli_connection.for_unit(_CLI_UNIT_ID))
    monkeypatch.setattr(sys, "argv", argv)

    exit_code = await query.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Time zone: local" in out
    assert "Modbus reads" in out
    assert expected_output in out


@pytest.mark.asyncio
async def test_main_returns_one_on_connection_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def connect(args: argparse.Namespace) -> MockModbusConnection:
        raise ModbusError("no backend available")

    monkeypatch.setattr(sys, "argv", ["remeha-query", "localhost"])
    monkeypatch.setattr(query, "connect_from_args", connect)

    exit_code = await query.main()

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Could not connect: no backend available" in out


@pytest.mark.asyncio
async def test_main_prints_modbus_retries(
    cli_connection: MockModbusConnection,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    unit = cli_connection.for_unit(_CLI_UNIT_ID)
    _isystem_seed(unit)
    unit.fail_read(601, IllegalDataAddressError())
    monkeypatch.setattr(sys, "argv", ["remeha-query", "localhost", "--gateway", "gtw26", "--sensors"])

    exit_code = await query.main()

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Failed bundles (1):" in out
    # The count is the retry policy's, so pin that one report prints with a nonzero count.
    (retry_count,) = re.findall(r"Modbus retries \((\d+)\):", out)
    assert int(retry_count) > 0


def test_run_exits_with_main_status_code(monkeypatch: pytest.MonkeyPatch) -> None:
    async def main() -> int:
        return 42

    monkeypatch.setattr(query, "main", main)

    with pytest.raises(SystemExit) as excinfo:
        query.run()

    assert excinfo.value.code == 42


def test_script_entry_point_prints_help(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The module is runnable as a script and its argument parser is wired up."""
    script = pathlib.Path(query.__file__)
    monkeypatch.setattr(sys, "argv", [str(script), "--help"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(script), run_name="__main__")

    assert excinfo.value.code == 0
    assert "Query a device and print values." in capsys.readouterr().out
