"""Tests for the modbus field helpers."""

from datetime import time
from enum import IntFlag

import pytest

# Import the package first: importing `helpers.fields` directly triggers a circular import.
import aio_remeha_modbus.gtw08  # noqa: F401
from aio_remeha_modbus.helpers.fields import (
    BinaryField,
    BytePosition,
    NullableBinaryField,
    TimeStepsField,
    binary,
    bits8,
    decode_bytes,
    encode_bytes,
    int16,
    nullable_binary,
    time_steps,
    uint8,
    uint16,
)


class _Flags(IntFlag):
    """Flags used to test `bits8`."""

    A = 1
    B = 2


def test_decode_bytes():
    """Test decoding registers to bytes for both word orders."""

    assert decode_bytes([0x0102, 0x0304]) == b"\x01\x02\x03\x04"
    assert decode_bytes([0x0102, 0x0304], word_order="little") == b"\x02\x01\x04\x03"
    assert decode_bytes([]) == b""


def test_encode_bytes():
    """Test encoding bytes to registers for both word orders."""

    assert encode_bytes(b"\x01\x02\x03\x04") == [0x0102, 0x0304]
    assert encode_bytes(b"\x01\x02\x03\x04", word_order="little") == [0x0201, 0x0403]
    assert encode_bytes(b"") == []


def test_encode_decode_bytes_round_trip():
    """Test that encoding and decoding gives back the original value."""

    value = bytes(range(12))
    assert decode_bytes(encode_bytes(value)) == value


def test_byte_position():
    """Test the bit offsets of the byte positions."""

    assert BytePosition.LOW == 0
    assert BytePosition.HIGH == 8


def test_binary_field():
    """Test that a binary field maps registers to bytes and back."""

    field = binary(10, count=2)
    assert isinstance(field, BinaryField)
    assert field.decode([0x0102, 0xFFFF]) == b"\x01\x02\xff\xff"
    assert field.encode(b"\x01\x02\xff\xff") == [0x0102, 0xFFFF]


def test_binary_field_word_order():
    """Test that the word order is used."""

    field = binary(10, count=1, word_order="little")
    assert field.decode([0x0102]) == b"\x02\x01"
    assert field.encode(b"\x02\x01") == [0x0102]


def test_nullable_binary_field_nan():
    """Test that the nan bytes are mapped to `None` and back."""

    field = nullable_binary(10, count=2)
    assert isinstance(field, NullableBinaryField)
    assert field.decode([0xFFFF, 0xFFFF]) is None
    assert field.encode(None) == [0xFFFF, 0xFFFF]


def test_nullable_binary_field_value():
    """Test that a non-nan value is decoded and encoded unchanged."""

    field = nullable_binary(10, count=2)
    assert field.decode([0x0102, 0xFFFF]) == b"\x01\x02\xff\xff"
    assert field.encode(b"\x01\x02\x03\x04") == [0x0102, 0x0304]


def test_nullable_binary_field_custom_nan_bytes():
    """Test that custom nan bytes are repeated for every register."""

    field = nullable_binary(10, count=2, nan_bytes=b"\xff\x00")
    assert field.decode([0xFF00, 0xFF00]) is None
    assert field.decode([0xFFFF, 0xFFFF]) == b"\xff\xff\xff\xff"
    assert field.encode(None) == [0xFF00, 0xFF00]


@pytest.mark.parametrize("nan_bytes", [b"", b"\xff", b"\xff\xff\xff"])
def test_nullable_binary_field_invalid_nan_bytes(nan_bytes: bytes):
    """Test that nan bytes with a length other than 2 are refused."""

    with pytest.raises(ValueError, match="nan_bytes requires a length of 2"):
        nullable_binary(10, nan_bytes=nan_bytes)


def test_time_steps_field_decode():
    """Test decoding 10-minute steps into a time of day."""

    field = time_steps(10)
    assert isinstance(field, TimeStepsField)
    assert field.decode([0]) == time(0, 0)
    assert field.decode([6]) == time(1, 0)
    assert field.decode([143]) == time(23, 50)


def test_time_steps_field_nan():
    """Test that `0xFF` is mapped to `None` and back."""

    field = time_steps(10)
    assert field.decode([0xFF]) is None
    assert field.encode(None) == [TimeStepsField.nan]


def test_time_steps_field_encode():
    """Test encoding a time of day to 10-minute steps."""

    field = time_steps(10)
    assert field.encode(time(0, 0)) == [0]
    assert field.encode(time(1, 0)) == [6]
    assert field.encode(time(23, 59)) == [143]


def test_uint8_scaled():
    """Test that a scaled uint8 is a gauge with `0xFF` as nan."""

    field = uint8(10, scale=0.5)
    assert field.decode([0x10]) == 8.0
    assert field.decode([0xFF]) is None
    assert field.encode(8.0) == [0x10]


def test_uint8_position():
    """Test that an unscaled uint8 reads the requested byte of the register."""

    assert uint8(10).decode([0x1234]) == 0x34
    assert uint8(10, position=BytePosition.LOW).decode([0x1234]) == 0x34
    assert uint8(10, position=BytePosition.HIGH).decode([0x1234]) == 0x12


def test_bits8():
    """Test that bits8 decodes into the given flags and treats `0xFF` as nan."""

    field = bits8(10, _Flags)
    assert field.decode([0x03]) == _Flags.A | _Flags.B
    assert isinstance(field.decode([0x02]), _Flags)
    assert field.decode([0xFF]) is None


def test_int16():
    """Test that int16 is signed and treats `0x8000` as nan."""

    field = int16(10)
    assert field.decode([0xFFFF]) == -1
    assert field.decode([0x8000]) is None
    assert field.encode(-1) == [0xFFFF]


def test_int16_scaled():
    """Test that a scaled int16 applies its scale in both directions."""

    field = int16(10, scale=0.1)
    assert field.decode([0xFFFF]) == pytest.approx(-0.1)
    assert field.decode([0x8000]) is None
    assert field.encode(2.5) == [25]


def test_int16_nan_override():
    """Test that int16 accepts multiple nan values, for both plain and scaled fields."""

    field = int16(10, nan=(0xFFFF, 0x8000))
    assert field.decode([0xFFFF]) is None
    assert field.decode([0x8000]) is None
    assert field.decode([0xFFFE]) == -2

    scaled = int16(10, scale=0.1, nan=(0xFFFF, 0x8000))
    assert scaled.decode([0xFFFF]) is None
    assert scaled.decode([0x8000]) is None
    assert scaled.decode([0xFFFE]) == pytest.approx(-0.2)


def test_uint16():
    """Test that uint16 is unsigned and treats `0xFFFF` as nan."""

    field = uint16(10)
    assert field.decode([3]) == 3
    assert field.decode([0xFFFF]) is None
    assert field.encode(3) == [3]


def test_uint16_scaled():
    """Test that a scaled uint16 applies its scale in both directions."""

    field = uint16(10, scale=0.1)
    assert field.decode([25]) == pytest.approx(2.5)
    assert field.decode([0xFFFF]) is None
    assert field.encode(2.5) == [25]
