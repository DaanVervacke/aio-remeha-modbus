"""Shared GTW26 device factories for the gtw26 tests."""

from typing import Protocol

import pytest
from modbus_connection import ModbusUnit

from aio_remeha_modbus.gtw26 import GTW26
from aio_remeha_modbus.gtw26.const import ControllerGeneration, RegisterLayout


class Gtw26Factory(Protocol):
    """Build a forced-layout GTW26 with a known generation, through setup."""

    async def __call__(
        self,
        unit: ModbusUnit,
        *,
        variant: ControllerGeneration | None = None,
        force_circuit_a: bool = False,
        force_circuit_b: bool = False,
        force_circuit_c: bool = False,
    ) -> GTW26: ...


class LayoutGtw26Factory(Protocol):
    """Build a forced-layout GTW26 for the given layout, through setup."""

    async def __call__(
        self,
        unit: ModbusUnit,
        layout: RegisterLayout,
        *,
        variant: ControllerGeneration | None = None,
        force_circuit_a: bool = False,
        force_circuit_b: bool = False,
        force_circuit_c: bool = False,
    ) -> GTW26: ...


async def _build_gtw26(
    unit: ModbusUnit,
    layout: RegisterLayout,
    *,
    variant: ControllerGeneration | None = None,
    force_circuit_a: bool = False,
    force_circuit_b: bool = False,
    force_circuit_c: bool = False,
) -> GTW26:
    """Construct a forced-layout device and run its setup.

    A known layout and generation make ``async_ensure_setup`` probe nothing,
    so this is the forced-layout-without-detection construction path.
    """
    if variant is None:
        variant = (
            ControllerGeneration.GENERATION_3
            if layout is RegisterLayout.BASE
            else ControllerGeneration.GENERATION_4
        )
    device = GTW26(
        "test",
        unit,
        layout=layout,
        generation=variant,
        force_zone_a=force_circuit_a,
        force_zone_b=force_circuit_b,
        force_zone_c=force_circuit_c,
    )
    await device.async_ensure_setup()
    return device


async def _base_gtw26(
    unit: ModbusUnit,
    *,
    variant: ControllerGeneration | None = None,
    force_circuit_a: bool = False,
    force_circuit_b: bool = False,
) -> GTW26:
    """Build a base-layout device, defaulting to generation 3."""
    return await _build_gtw26(
        unit,
        RegisterLayout.BASE,
        variant=variant,
        force_circuit_a=force_circuit_a,
        force_circuit_b=force_circuit_b,
    )


async def _isystem_gtw26(
    unit: ModbusUnit,
    *,
    variant: ControllerGeneration | None = None,
    force_circuit_a: bool = False,
    force_circuit_b: bool = False,
    force_circuit_c: bool = False,
) -> GTW26:
    """Build an iSystem-layout device, defaulting to generation 4."""
    return await _build_gtw26(
        unit,
        RegisterLayout.ISYSTEM,
        variant=variant,
        force_circuit_a=force_circuit_a,
        force_circuit_b=force_circuit_b,
        force_circuit_c=force_circuit_c,
    )


@pytest.fixture
def gtw26() -> LayoutGtw26Factory:
    """Return a factory building a GTW26 with the given forced layout."""
    return _build_gtw26


@pytest.fixture
def base_gtw26() -> Gtw26Factory:
    """Return a factory building a forced-base-layout GTW26."""
    return _base_gtw26


@pytest.fixture
def isystem_gtw26() -> Gtw26Factory:
    """Return a factory building a forced-iSystem-layout GTW26."""
    return _isystem_gtw26
