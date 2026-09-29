"""Helpers for modbus field types."""

from collections.abc import Iterable
from datetime import time
from enum import IntEnum, IntFlag
from typing import TYPE_CHECKING, Any, overload, override

from modbus_connection import WordOrder
from modbus_connection.model import (
    NumberField,
    PackedBitsField,
    RegisterField,
    WriteValidator,
    bits,
    gauge,
    integer,
)

if TYPE_CHECKING:
    from aio_remeha_modbus.helpers.gtw08 import SteppedTimeOfDay


def decode_bytes(words: list[int], word_order: WordOrder = "big") -> bytes:
    """Decode a list of registers to a bytes object."""

    return b"".join(word.to_bytes(2, byteorder=word_order) for word in words)


def encode_bytes(value: bytes, word_order: WordOrder = "big") -> list[int]:
    """Encode a byte object to a list of registers."""

    return [
        int.from_bytes(bytes=value[i : i + 2], byteorder=word_order)
        for i in range(0, len(value), 2)
    ]


class BytePosition(IntEnum):
    """Describes the position of a byte within a 2-byte modbus register."""

    LOW = 0
    """The low byte within a single modbus register."""

    HIGH = 8
    """The high byte within a single modbus register."""


class BinaryField(RegisterField[bytes]):
    """A field that spans multiple registers and maps them to a bytes object."""

    def __init__(
        self,
        address: int,
        *,
        count: int = 1,
        word_order: WordOrder = "big",
        writable: bool | WriteValidator = False,
        stride: int = 0,
        force_fc16: bool = False,
    ) -> None:
        """Create a new BinaryField."""

        super().__init__(
            address, count=count, writable=writable, stride=stride, force_fc16=force_fc16
        )
        self.word_order: WordOrder = word_order

    @override
    def decode(self, words: list[int], scale_exponent: int | None = None) -> bytes:
        return decode_bytes(words=words, word_order=self.word_order)

    @override
    def encode(self, value: bytes, scale_exponent: int | None = None) -> list[int]:
        return encode_bytes(value=value, word_order=self.word_order)


class NullableBinaryField(BinaryField):
    """A binary field that can handle null-values."""

    def __init__(
        self,
        address: int,
        *,
        count: int = 1,
        nan_bytes: bytes = b"\xff\xff",
        word_order: WordOrder = "big",
        writable: bool | WriteValidator = False,
        stride: int = 0,
        force_fc16: bool = False,
    ) -> None:
        """Create a new NullableBinaryField.

        Args:
            address (int): The register address the field starts at.
            count (int): The amount of registers to read.
            nan_bytes (bytes): The designated nan-value for a register. Must have a length of 2.
            word_order (WordOrder): The word-order for multi-register values.
            writable (bool|WriteValidator): A `bool` or a `WriteValidator`.
            stride (int): Per-index address-step for a placed component.
            force_fc16 (bool): Always write with FC16, even a single register.

        Raises:
            ValueError: If `force_fc16` is `True`, but `writable` is `False`.
            ValueError: If `nan_bytes` is not exactly 2 bytes long.

        """

        super().__init__(
            address,
            count=count,
            word_order=word_order,
            writable=writable,
            stride=stride,
            force_fc16=force_fc16,
        )

        if len(nan_bytes) == 2:
            self._nan_bytes = nan_bytes * count
        else:
            raise ValueError(f"nan_bytes requires a length of 2, got {len(nan_bytes)}")

    @override
    def decode(self, words: list[int], scale_exponent: int | None = None) -> bytes | None:
        decoded = super().decode(words=words, scale_exponent=scale_exponent)

        if decoded == self._nan_bytes:
            return None

        return decoded

    @override
    def encode(self, value: bytes | None, scale_exponent: int | None = None) -> list[int]:
        return super().encode(
            value=self._nan_bytes if value is None else value, scale_exponent=scale_exponent
        )


class TimeStepsField(RegisterField[time]):
    """A time field that is built from bytes.

    The time is encoded as 10-minute time steps starting at midnight.
    """

    nan = 0xFF

    def __init__(self, address: int, *, writable: bool | WriteValidator = False):
        """Create a new TimeOfDaySteps instance."""

        super().__init__(address, writable=writable)

    @override
    def decode(self, words: list[int], scale_exponent: int | None = None) -> time | None:
        from aio_remeha_modbus.helpers.gtw08 import SteppedTimeOfDay

        steps = words[0]
        if (steps & 0xFF) == TimeStepsField.nan:
            return None

        return SteppedTimeOfDay.from_steps(steps)

    @override
    def encode(self, value: time | None, scale_exponent: int | None = None) -> list[int]:
        from aio_remeha_modbus.helpers.gtw08 import SteppedTimeOfDay

        if value is None:
            return [TimeStepsField.nan]

        return [SteppedTimeOfDay.to_steps(value)]


def binary(
    address: int,
    *,
    count: int = 1,
    word_order: WordOrder = "big",
    writable: bool | WriteValidator = False,
    stride: int = 0,
    force_fc16: bool = False,
) -> BinaryField:
    """Create a binary register field."""

    return BinaryField(
        address,
        count=count,
        word_order=word_order,
        writable=writable,
        stride=stride,
        force_fc16=force_fc16,
    )


def nullable_binary(
    address: int,
    *,
    count: int = 1,
    nan_bytes: bytes = b"\xff\xff",
    word_order: WordOrder = "big",
    writable: bool | WriteValidator = False,
    stride: int = 0,
    force_fc16: bool = False,
) -> NullableBinaryField:
    """Create a nullable binary register field."""

    return NullableBinaryField(
        address,
        count=count,
        nan_bytes=nan_bytes,
        word_order=word_order,
        writable=writable,
        stride=stride,
        force_fc16=force_fc16,
    )


@overload
def uint8(
    address: int,
    *,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    position: BytePosition = BytePosition.LOW,
) -> PackedBitsField: ...


@overload
def uint8(
    address: int,
    *,
    scale: float,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
) -> NumberField[float]: ...


def uint8(
    address: int,
    *,
    scale: float | None = None,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    position: BytePosition | None = BytePosition.LOW,
) -> PackedBitsField | NumberField[float]:
    """Provide an 8-bit unsigned integer.

    For a non-scaled value, `position` determines which register byte to read.
    This is useful for reading registers that contain two distinct values.
    """

    if scale is not None:
        return gauge(
            address=address,
            scale=scale,
            signed=False,
            nan=0xFF,
            stride=stride,
            writable=writable,
            unit=unit,
        )

    assert position is not None
    return bits(address, start=position, width=8, writable=writable, stride=stride, unit=unit)


def bits8[F: IntFlag](
    address: int, flags: type[F] | None = None, writable: bool | WriteValidator = False
) -> NumberField[F]:
    """Create an 8-bit bitfield point."""

    return NumberField(address, count=1, signed=False, nan=0xFF, convert=flags, writable=writable)


@overload
def int16(
    address: int,
    *,
    scale: float,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    nan: int | Iterable[int] = 0x8000,
    force_fc16: bool = False,
) -> NumberField[float]: ...


@overload
def int16(
    address: int,
    *,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    nan: int | Iterable[int] = 0x8000,
    force_fc16: bool = False,
) -> NumberField[int]: ...


def int16(
    address: int,
    *,
    scale: float | None = None,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    nan: int | Iterable[int] = 0x8000,
    force_fc16: bool = False,
) -> NumberField[int | float]:
    """Create a field containing a signed 16-bits integer.

    If `scale` is provided, a `gauge` is returned, otherwise an `integer`.
    `nan` defaults to the INT16 null value `0x8000`; pass one or more raw values
    to override it.
    """

    if scale is None:
        return integer(
            address,
            nan=nan,
            stride=stride,
            writable=writable,
            unit=unit,
            force_fc16=force_fc16,
        )

    return gauge(
        address,
        scale,
        nan=nan,
        stride=stride,
        writable=writable,
        unit=unit,
        force_fc16=force_fc16,
    )


@overload
def uint16(
    address: int,
    *,
    scale: float,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    force_fc16: bool = False,
) -> NumberField[float]: ...


@overload
def uint16(
    address: int,
    *,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    force_fc16: bool = False,
) -> NumberField[int]: ...


def uint16(
    address: int,
    *,
    scale: float | None = None,
    stride: int = 0,
    writable: bool | WriteValidator = False,
    unit: str | None = None,
    force_fc16: bool = False,
) -> NumberField[int | float]:
    """Provide an unsigned 16-bit integer field."""

    if scale is None:
        return integer(
            address,
            signed=False,
            nan=0xFFFF,
            stride=stride,
            writable=writable,
            unit=unit,
            force_fc16=force_fc16,
        )

    return gauge(
        address,
        scale,
        signed=False,
        nan=0xFFFF,
        stride=stride,
        writable=writable,
        unit=unit,
        force_fc16=force_fc16,
    )


def time_steps(address: int, *, writable: bool | WriteValidator = False) -> TimeStepsField:
    """Create a field that contains the time of day in 10-minute steps since midnight."""

    return TimeStepsField(address, writable=writable)


# Values are stored in tenths with the sign in bit 15, so a negative number is
# not two's complement. 0xFFFF and 0x8CCC mean the sensor is absent.

_SIGN_BIT = 0x8000
_MAGNITUDE = 0x7FFF
_NO_SENSOR = frozenset((0xFFFF, 0x8CCC))
_PROGRAMS = 4
_DAYS = 7


class Float10Field(RegisterField[float | None]):
    """A value in tenths with a separate sign bit for negative numbers."""

    none_values: tuple[int, ...] = ()

    @override
    def decode(self, words: list[int], scale_exponent: int | None = None) -> float | None:
        raw = words[0]
        if raw in _NO_SENSOR or raw in self.none_values:
            return None
        return -(raw & _MAGNITUDE) / 10 if raw >= _SIGN_BIT else raw / 10

    @override
    def encode(self, value: Any, scale_exponent: int | None = None) -> list[int]:
        tenths = round(abs(float(value)) * 10)
        if value < 0:
            tenths |= _SIGN_BIT
        return [tenths]


def float10(
    address: int,
    *,
    writable: bool | WriteValidator = False,
    force_fc16: bool = False,
    unit: str | None = None,
    none_values: tuple[int, ...] = (),
) -> Float10Field:
    """Create a tenths field, optionally recognising extra missing-value codes."""
    field = Float10Field(address, writable=writable, force_fc16=force_fc16, unit=unit)
    field.none_values = none_values
    return field


class _MaskedEnum[E: IntEnum]:
    """Decode known modes and keep unknown mode bits as an integer."""

    def __init__(self, mask: int, enum_type: type[E]) -> None:
        self.mask = mask
        self.enum_type = enum_type

    def __call__(self, raw: int) -> E | int:
        value = raw & self.mask
        try:
            return self.enum_type(value)
        except ValueError:
            return value


def masked_enum[E: IntEnum](address: int, mask: int, enum_type: type[E]) -> NumberField[E | int]:
    """Read mode bits as a known enum member or an unknown integer code."""
    return NumberField(address, signed=False, convert=_MaskedEnum(mask, enum_type))


class _EnumValue[E: IntEnum]:
    """Decode an enum while preserving unknown register values."""

    def __init__(self, enum_type: type[E]) -> None:
        self.enum_type = enum_type

    def __call__(self, raw: int) -> E | int:
        try:
            return self.enum_type(raw)
        except ValueError:
            return raw


def enum_value[E: IntEnum](
    address: int,
    enum_type: type[E],
    *,
    writable: bool = False,
    force_fc16: bool = False,
) -> NumberField[E | int]:
    """Read an unsigned enum value while preserving unknown values."""
    return NumberField(
        address,
        signed=False,
        convert=_EnumValue(enum_type),
        writable=writable,
        force_fc16=force_fc16,
    )


def scaled_integer(address: int, divisor: int, *, unit: str) -> NumberField[float]:
    """Read an unsigned integer scaled by a fixed divisor."""
    return NumberField(address, signed=False, convert=lambda raw: raw / divisor, unit=unit)


def multiplied_integer(
    address: int, multiplier: int, *, unit: str, nan: int | None = None
) -> NumberField[int]:
    """Read an unsigned integer multiplied by a fixed factor."""
    return NumberField(
        address, signed=False, nan=nan, convert=lambda raw: raw * multiplier, unit=unit
    )


def positive_float10(value: Any) -> float:
    """Validate a nonnegative tenths value for a controller write."""
    result = float(value)
    if not 0.0 <= result <= 10.0:
        raise ValueError("value must be between 0 and 10 °C")
    return result


class _CodeLabel:
    """Map a code to its label, an ok code to None, an unknown code to the raw int."""

    def __init__(self, table: dict[int, str], ok: frozenset[int]) -> None:
        self.table = table
        self.ok = ok

    def __call__(self, raw: int) -> str | int | None:
        if raw in self.ok:
            return None
        return self.table.get(raw, raw)


def fault_code(
    address: int, table: dict[int, str], *, ok: tuple[int, ...] = (0xFFFF,)
) -> NumberField[str | int | None]:
    """Map a fault register to a label, no-fault codes to None, unknown to raw int."""
    return NumberField(address, signed=False, convert=_CodeLabel(table, frozenset(ok)))


def code_map(address: int, table: dict[int, str]) -> NumberField[str | int]:
    """Map a register to a label from `table`, unknown codes to the raw int."""
    return NumberField(address, signed=False, convert=_CodeLabel(table, frozenset()))


def controller_type_field() -> NumberField[str | int]:
    """Read register 457 as a controller type label, unknown codes kept as raw ints."""
    from aio_remeha_modbus.gtw26.const import MODEL_CODES  # noqa: PLC0415

    return code_map(457, MODEL_CODES)


class _TimeProgram:
    """Map a program-selection register to the P1 to P4 program it selects."""

    def __call__(self, raw: int) -> int | None:
        if raw in _NO_SENSOR:
            return None
        return (raw & 0xFF) // _DAYS % _PROGRAMS + 1


def time_program(address: int) -> NumberField[int | None]:
    """Read the selected heating program as a number from 1 to 4."""
    return NumberField(address, signed=False, convert=_TimeProgram())


def snap_clamp(step: float, low: float, high: float) -> WriteValidator:
    """Round requests to `step` and keep them between `low` and `high`."""

    def validate(value: Any) -> float:
        snapped = round(float(value) / step) * step
        return min(max(snapped, low), high)

    return validate


def int_clamp(low: int, high: int) -> WriteValidator:
    """Round requests to a whole number between `low` and `high`."""

    def validate(value: Any) -> int:
        return min(max(round(float(value)), low), high)

    return validate


def permanent_derogation(raw: int) -> bool | None:
    """Decode verified heating override modes independently of hot-water bits.

    `True` for a permanent day or night override, `False` for automatic mode and
    temporary overrides, and `None` for modes whose override semantics are unverified.
    """
    from aio_remeha_modbus.gtw26.const import HEATING_MODE_MASK, HeatingMode  # noqa: PLC0415

    mode = raw & HEATING_MODE_MASK
    if mode in {HeatingMode.PERM_DAY, HeatingMode.PERM_NIGHT}:
        return True
    if mode in {HeatingMode.AUTO, HeatingMode.TEMP_DAY, HeatingMode.TEMP_NIGHT}:
        return False
    return None


def derogation_until_end(raw: int) -> bool | None:
    """Decode the documented timed-override bit for known heating modes."""
    from aio_remeha_modbus.gtw26.const import HEATING_MODE_MASK, HeatingMode  # noqa: PLC0415

    mode = raw & HEATING_MODE_MASK
    if mode in {HeatingMode.PERM_DAY, HeatingMode.PERM_NIGHT}:
        return False
    if mode in {HeatingMode.AUTO, HeatingMode.TEMP_DAY, HeatingMode.TEMP_NIGHT}:
        return bool(raw & 0x20)
    return None
