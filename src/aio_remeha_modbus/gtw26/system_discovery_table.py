"""GTW26 register-layout discovery and identity components."""

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from modbus_connection import (
    IllegalDataAddressError,
    IllegalFunctionError,
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
    ModbusUnit,
)
from modbus_connection.model import integer

from aio_remeha_modbus.gtw26.const import (
    BASE_GENERATIONS,
    BASE_IDENTITY_BLOCKS,
    BASE_WINDOWS,
    ISYSTEM_IDENTITY_BLOCKS,
    ISYSTEM_WINDOWS,
    MESSAGE_SPACING,
    MODEL_CODES,
    ControllerGeneration,
    RegisterLayout,
)
from aio_remeha_modbus.gtw26.errors import GTW26ProbeError
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


class DetectionFailureReason(Enum):
    """Describe the reason for a GTW26 detection failure."""

    NOT_A_GTW26 = 0
    """No identity register layout answered, so the device is not a GTW26."""

    UNKNOWN_MODEL = 1
    """A device answered but its type code does not name a known generation."""


@dataclass(frozen=True)
class GTW26Detection:
    """Describe a GTW26 detection attempt and its probe evidence.

    On success, `device` is a fully constructed, ready-to-use `GTW26` facade.
    Constructing it applies the message spacing the detection was given (the
    `MESSAGE_SPACING` default by default) on the unit, unlike GTW08's
    detection, which only reports a main board descriptor.
    """

    device: GTW26 | None
    """The discovered device facade. Always has a value if `success is True`."""

    success: bool
    """Whether a GTW26 controller with a known register layout was discovered."""

    failure_reason: DetectionFailureReason | None
    """The reason the detection failed. Always has a value if `success is False`."""

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
    """Read identity blocks, retaining register answers and wrong-device rejections.

    Connection-level errors propagate so a dead link fails detection outright.
    """
    results: list[ProbeBlock] = []
    for address, count in blocks:
        try:
            values = tuple(await unit.read_holding_registers(address, count))
        except ModbusConnectionError, ModbusTimeoutError:
            raise
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


async def _async_probe(
    unit: ModbusUnit,
    *,
    base_only: bool,
    message_spacing_seconds: float,
) -> GTW26Detection:
    """Probe the identity blocks and freeze the evidence into one detection.

    ``base_only`` skips the iSystem blocks, for a caller that already knows the
    base layout answers and only needs its controller generation.
    """
    base_probe = await _async_read_blocks(unit, BASE_IDENTITY_BLOCKS)
    isystem_probe = () if base_only else await _async_read_blocks(unit, ISYSTEM_IDENTITY_BLOCKS)
    type_values = _block_values(base_probe, 457)
    type_code = type_values[0] if type_values is not None else None
    generation = BASE_GENERATIONS.get(type_code) if type_code is not None else None
    isystem_detected = not base_only and all(block.outcome == "success" for block in isystem_probe)
    base_detected = generation is not None and all(
        block.outcome == "success" for block in base_probe
    )

    from aio_remeha_modbus.gtw26.gtw26 import GTW26  # noqa: PLC0415

    def result(
        device: GTW26 | None, failure_reason: DetectionFailureReason | None
    ) -> GTW26Detection:
        """Freeze the probe evidence into one detection result."""
        return GTW26Detection(
            device=device,
            success=failure_reason is None,
            failure_reason=failure_reason,
            raw_type_code=type_code,
            generation=generation,
            isystem_detected=isystem_detected,
            base_probe=base_probe,
            isystem_probe=isystem_probe,
        )

    if type_code is not None and type_code in MODEL_CODES and generation is None:
        return result(None, DetectionFailureReason.UNKNOWN_MODEL)
    if isystem_detected:
        device = GTW26(
            "GTW26",
            unit,
            layout=RegisterLayout.ISYSTEM,
            generation=generation,
            message_spacing_seconds=message_spacing_seconds,
        )
        return result(device, None)
    if base_detected:
        assert generation is not None
        device = GTW26(
            "GTW26",
            unit,
            layout=RegisterLayout.BASE,
            generation=generation,
            message_spacing_seconds=message_spacing_seconds,
        )
        return result(device, None)
    return result(None, DetectionFailureReason.NOT_A_GTW26)


async def async_detect(
    unit: ModbusUnit, *, message_spacing_seconds: float = MESSAGE_SPACING
) -> GTW26Detection:
    """Detect the GTW26 layout and retain all identity probe evidence.

    A wrong-device answer is reported through a failed detection result.
    Only transient or unknown `ModbusError` instances propagate.
    ``message_spacing_seconds`` is the spacing the discovered device enforces
    on ``unit``, so a caller-configured spacing survives detection.
    """
    return await _async_probe(
        unit, base_only=False, message_spacing_seconds=message_spacing_seconds
    )


async def async_detect_base(
    unit: ModbusUnit, *, message_spacing_seconds: float = MESSAGE_SPACING
) -> GTW26Detection:
    """Probe only the base identity blocks to resolve the controller generation.

    The iSystem blocks are skipped, so a caller that already knows the base
    layout answers pays for three reads instead of five.
    """
    return await _async_probe(unit, base_only=True, message_spacing_seconds=message_spacing_seconds)


async def async_probe(unit: ModbusUnit) -> GTW26:
    """Detect the GTW26 layout and return its configured device facade.

    Raises:
        GTW26ProbeError: if detection returned a failed result.

    """
    detection = await async_detect(unit)
    if not detection.success:
        raise GTW26ProbeError(detection)
    assert detection.device is not None
    return detection.device
