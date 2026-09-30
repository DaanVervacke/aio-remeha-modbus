"""Tests for the modbus helpers."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from modbus_connection import ModbusUnit
from modbus_connection.exceptions import IllegalDataValueError, IllegalFunctionError

from aio_remeha_modbus.helpers.modbus import (
    RetryingModbusUnit,
    _RetryStatistics,
    retry_on_transient,
)


@pytest.mark.asyncio
async def test_async_retry():
    """Test that async_retry retries function execution for the right kind of exceptions."""

    # 1 retry (2 attempts)
    attempts: dict[str, int] = {"test_retries": 0, "test_raises": 0}

    @retry_on_transient(2)
    async def test_retries() -> int:
        try:
            if attempts["test_retries"] == 0:
                raise IllegalDataValueError(exception_code=0x03)

            return 42
        finally:
            attempts["test_retries"] += 1

    # IllegalDataValueError is in TransientModbusError so must be retried.
    assert await test_retries() == 42
    assert attempts["test_retries"] == 2

    @retry_on_transient(2)
    async def test_raises() -> int:
        try:
            if attempts["test_raises"] == 0:
                raise IllegalFunctionError(exception_code=0x03)

            return 42
        finally:
            attempts["test_raises"] += 1

    # IllegalFunctionError is not in TransientModbusError so must not be retried.
    with pytest.raises(
        expected_exception=IllegalFunctionError, match="Device returned Modbus exception code 3"
    ):
        await test_raises()

    assert attempts["test_raises"] == 1


@pytest.mark.parametrize(
    "max_tries",
    [
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
    ],
)
def test_retry_on_transient_rejects_invalid_max_tries(max_tries: int):
    """Test that a non-positive `max_tries` is refused at decoration time."""

    with pytest.raises(ValueError, match="max_tries must be at least 1"):

        @retry_on_transient(max_tries)
        async def never_called() -> int:
            return 42


@pytest.mark.asyncio
async def test_retry_on_transient_gives_up_after_max_tries():
    """Test that the transient exception is re-raised after `max_tries` attempts."""

    attempts = 0

    @retry_on_transient(3)
    async def always_fails() -> int:
        nonlocal attempts
        attempts += 1
        raise IllegalDataValueError(exception_code=0x03)

    with pytest.raises(IllegalDataValueError):
        await always_fails()

    assert attempts == 3


@pytest.mark.asyncio
async def test_retry_on_transient_passes_arguments():
    """Test that (keyword) arguments and the return value are passed through."""

    @retry_on_transient()
    async def add(a: int, *, b: int) -> int:
        return a + b

    assert await add(1, b=2) == 3


def test_retry_statistics():
    """Test that retries are recorded and exposed read-only."""

    statistics = _RetryStatistics()
    assert statistics.retries == ()

    first = IllegalDataValueError(exception_code=0x03)
    second = IllegalDataValueError(exception_code=0x03)
    statistics.retried(first)
    statistics.retried(second)

    assert statistics.retries == (first, second)
    assert isinstance(statistics.retries, tuple)


@pytest.mark.asyncio
async def test_retry_on_transient_records_statistics():
    """Test that a decorated method of a `_RetryStatistics` records its retries."""

    class Flaky(_RetryStatistics):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        @retry_on_transient(3)
        async def read(self) -> int:
            self.calls += 1
            if self.calls < 3:
                raise IllegalDataValueError(exception_code=0x03)

            return 42

    flaky = Flaky()
    assert await flaky.read() == 42
    assert flaky.calls == 3
    assert len(flaky.retries) == 2
    assert all(isinstance(ex, IllegalDataValueError) for ex in flaky.retries)


@pytest.fixture
def wrapped_unit() -> MagicMock:
    """Return a mocked modbus unit to be wrapped."""

    return MagicMock(spec=ModbusUnit)


@pytest.mark.asyncio
async def test_retrying_unit_retries_reads(wrapped_unit: MagicMock):
    """Test that read methods are retried and the retries are recorded."""

    wrapped_unit.read_holding_registers = AsyncMock(
        side_effect=[IllegalDataValueError(exception_code=0x03), [1, 2]]
    )
    unit = RetryingModbusUnit(wrapped_unit)

    assert await unit.read_holding_registers(10, 2) == [1, 2]
    wrapped_unit.read_holding_registers.assert_awaited_with(10, 2)
    assert wrapped_unit.read_holding_registers.await_count == 2
    assert len(unit.retries) == 1


@pytest.mark.asyncio
async def test_retrying_unit_does_not_retry_writes(wrapped_unit: MagicMock):
    """Test that write methods are not retried."""

    wrapped_unit.write_register = AsyncMock(side_effect=IllegalDataValueError(exception_code=0x03))
    unit = RetryingModbusUnit(wrapped_unit)

    with pytest.raises(IllegalDataValueError):
        await unit.write_register(1, 2)

    assert wrapped_unit.write_register.await_count == 1
    assert unit.retries == ()


@pytest.mark.asyncio
async def test_retrying_unit_gives_up_on_reads(wrapped_unit: MagicMock):
    """Test that a read that keeps failing raises after three attempts."""

    wrapped_unit.read_coils = AsyncMock(side_effect=IllegalDataValueError(exception_code=0x03))
    unit = RetryingModbusUnit(wrapped_unit)

    with pytest.raises(IllegalDataValueError):
        await unit.read_coils(0, 1)

    assert wrapped_unit.read_coils.await_count == 3
    assert len(unit.retries) == 3


@pytest.mark.parametrize("connected", [True, False])
def test_retrying_unit_connected(wrapped_unit: MagicMock, connected: bool):
    """Test that `connected` reflects the wrapped unit."""

    wrapped_unit.connected = connected
    assert RetryingModbusUnit(wrapped_unit).connected is connected


_ASYNC_PASS_THROUGH: list[tuple[str, tuple[Any, ...]]] = [
    ("read_holding_registers", (1, 2)),
    ("read_input_registers", (1, 2)),
    ("write_register", (1, 2)),
    ("write_registers", (1, [2, 3])),
    ("read_coils", (1, 2)),
    ("read_discrete_inputs", (1, 2)),
    ("write_coil", (1, True)),
    ("write_coils", (1, [True, False])),
    ("read_exception_status", ()),
    ("report_server_id", ()),
    ("mask_write_register", (1, 2, 3)),
    ("read_write_registers", (1, 2, 3, [4])),
    ("read_fifo_queue", (1,)),
    ("read_device_identification", ()),
    ("read_file_record", (1, 2, 3)),
    ("write_file_record", (1, 2, [3])),
    ("diagnostics", (1, 2)),
    ("get_comm_event_counter", ()),
    ("get_comm_event_log", ()),
    ("disconnect", ()),
]

_SYNC_PASS_THROUGH: list[tuple[str, tuple[Any, ...]]] = [
    ("set_message_spacing", (0.5,)),
    ("require_timeout", (2.0,)),
    ("require_connect_delay", (1.0,)),
    ("on_connection_lost", (lambda: None,)),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "args"), _ASYNC_PASS_THROUGH)
async def test_retrying_unit_async_pass_through(
    wrapped_unit: MagicMock, method: str, args: tuple[Any, ...]
):
    """Test that async methods forward their arguments and return the wrapped result."""

    sentinel = object()
    mocked = AsyncMock(return_value=sentinel)
    setattr(wrapped_unit, method, mocked)
    unit = RetryingModbusUnit(wrapped_unit)

    assert await getattr(unit, method)(*args) is sentinel
    mocked.assert_awaited_once_with(*args)


@pytest.mark.parametrize(("method", "args"), _SYNC_PASS_THROUGH)
def test_retrying_unit_sync_pass_through(
    wrapped_unit: MagicMock, method: str, args: tuple[Any, ...]
):
    """Test that sync methods forward their arguments and return the wrapped result."""

    sentinel = object()
    mocked = MagicMock(return_value=sentinel)
    setattr(wrapped_unit, method, mocked)
    unit = RetryingModbusUnit(wrapped_unit)

    assert getattr(unit, method)(*args) is sentinel
    mocked.assert_called_once_with(*args)
