"""GTW26 register-layout discovery and identity components."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from modbus_connection import (
    IllegalDataAddressError,
    IllegalFunctionError,
    ModbusError,
    ModbusUnit,
)
from modbus_connection.model import integer

from aio_remeha_modbus.gtw26.const import (
    BASE_GENERATIONS,
    BASE_IDENTITY_BLOCKS,
    BASE_WINDOWS,
    ISYSTEM_IDENTITY_BLOCKS,
    ISYSTEM_WINDOWS,
    MODEL_CODES,
    ControllerGeneration,
    RegisterLayout,
)
from aio_remeha_modbus.gtw26.errors import Gtw26ProbeError
from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.helpers.fields import controller_type_field

if TYPE_CHECKING:
    from aio_remeha_modbus.gtw26.gtw26 import GTW26


class Identity(Gtw26Component):
    """Controller identity and clock registers in the base layout."""

    register_ranges = BASE_WINDOWS

    controller = integer(3, signed=False)
    controller_type = controller_type_field()
    hour = integer(4, signed=False)
    minute = integer(5, signed=False)
    weekday = integer(6, signed=False)
    day = integer(108, signed=False)
    month = integer(109, signed=False)
    year = integer(110, signed=False)


class ISystemIdentity(Gtw26Component):
    """Controller identity and clock registers in the iSystem layout."""

    register_ranges = ISYSTEM_WINDOWS

    software_version = integer(600, signed=False)
    controller_type = controller_type_field()
    hour = integer(679, signed=False)
    minute = integer(680, signed=False)
    weekday = integer(681, signed=False)
    day = integer(682, signed=False)
    month = integer(683, signed=False)
    year = integer(684, signed=False)


@dataclass(frozen=True)
class ProbeBlock:
    """Record one identity-block read during layout discovery."""

    address: int
    count: int
    values: tuple[int, ...] | None
    error: ModbusError | None

    @property
    def outcome(self) -> str:
        """The stable outcome name for this block."""
        if self.error is None:
            return "success"
        if isinstance(self.error, (IllegalDataAddressError, IllegalFunctionError)):
            return "unsupported"
        return "error"

    @property
    def error_type(self) -> str | None:
        """The exception class name when the block failed."""
        return type(self.error).__name__ if self.error is not None else None

    @property
    def error_message(self) -> str | None:
        """The exception text when the block failed."""
        return str(self.error) if self.error is not None else None


@dataclass(frozen=True)
class Gtw26Detection:
    """Describe a GTW26 detection attempt and its probe evidence."""

    device: GTW26 | None
    raw_type_code: int | None
    generation: ControllerGeneration | None
    isystem_detected: bool
    base_probe: tuple[ProbeBlock, ...]
    isystem_probe: tuple[ProbeBlock, ...]


class SystemDiscoveryTable(Gtw26Component):
    """Marker component used by the GTW26 facade for system discovery."""


async def _async_read_blocks(
    unit: ModbusUnit, blocks: tuple[tuple[int, int], ...]
) -> tuple[ProbeBlock, ...]:
    """Read identity blocks and retain successful values or raised errors."""
    results: list[ProbeBlock] = []
    for address, count in blocks:
        try:
            values = tuple(await unit.read_holding_registers(address, count))
        except ModbusError as err:
            results.append(ProbeBlock(address, count, None, err))
        else:
            results.append(ProbeBlock(address, count, values, None))
    return tuple(results)


def _block_values(blocks: tuple[ProbeBlock, ...], address: int) -> tuple[int, ...] | None:
    """Return the values for the block beginning at ``address``."""
    for block in blocks:
        if block.address == address:
            return block.values
    return None


async def async_detect(unit: ModbusUnit) -> Gtw26Detection:
    """Detect the GTW26 layout and retain all identity probe evidence."""
    base_probe = await _async_read_blocks(unit, BASE_IDENTITY_BLOCKS)
    isystem_probe = await _async_read_blocks(unit, ISYSTEM_IDENTITY_BLOCKS)
    type_values = _block_values(base_probe, 457)
    type_code = type_values[0] if type_values is not None else None
    generation = BASE_GENERATIONS.get(type_code) if type_code is not None else None
    isystem_detected = all(block.outcome == "success" for block in isystem_probe)
    base_detected = generation is not None and all(
        block.outcome == "success" for block in base_probe
    )

    detection = Gtw26Detection(
        None,
        type_code,
        generation,
        isystem_detected,
        base_probe,
        isystem_probe,
    )
    if type_code is not None and type_code in MODEL_CODES and generation is None:
        raise Gtw26ProbeError(detection)

    from aio_remeha_modbus.gtw26.gtw26 import GTW26  # noqa: PLC0415

    if isystem_detected:
        return Gtw26Detection(
            GTW26("GTW26", unit, layout=RegisterLayout.ISYSTEM, generation=generation),
            type_code,
            generation,
            True,
            base_probe,
            isystem_probe,
        )
    if base_detected:
        assert generation is not None
        return Gtw26Detection(
            GTW26("GTW26", unit, layout=RegisterLayout.BASE, generation=generation),
            type_code,
            generation,
            False,
            base_probe,
            isystem_probe,
        )
    raise Gtw26ProbeError(detection)


async def async_probe(unit: ModbusUnit) -> GTW26:
    """Detect the GTW26 layout and return its configured device facade."""
    detection = await async_detect(unit)
    assert detection.device is not None
    return detection.device
