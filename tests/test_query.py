"""Tests for the remeha-query CLI."""

import argparse
from datetime import time
from typing import Any

import pytest
from modbus_connection.cli_helper import CountingUnit
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus import query
from aio_remeha_modbus.gtw26.schedule import ComfortPeriod


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
