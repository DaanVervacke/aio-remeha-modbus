"""Modbus helper functions."""

from collections.abc import Callable
from functools import wraps
from types import CoroutineType
from typing import Any, ParamSpec, TypeVar, cast, override

from modbus_connection import ModbusUnit
from typing_extensions import TypeForm

from aio_remeha_modbus.gtw08.errors import TransientModbusError


class _RetryStatistics:
    """A observable retry statistics class."""

    def __init__(self) -> None:
        """Create a new RetryStatistics instance."""

        self._retries: list[TypeForm[TransientModbusError]] = []

    def retried(self, exception: TypeForm[TransientModbusError]) -> None:
        """Insert a retry record.

        Args:
            exception (E): The exception that caused the retry.

        """

        self._retries.append(exception)

    @property
    def retries(self) -> tuple[TypeForm[TransientModbusError], ...]:
        """Return a read-only view of the exceptions causing the retries."""

        return tuple(self._retries)


R = TypeVar("R")
P = ParamSpec("P")


def retry_on_transient(
    max_tries: int = 3,
) -> Callable[[Callable[P, CoroutineType[Any, Any, R]]], Callable[P, CoroutineType[Any, Any, R]]]:
    """Retry function execution if a `TransientModbusError` occurs.

    Args:
        max_tries (int): The maximum amount attempts to execute the function before giving up and raising.

    The function is executed at most `max_tries`, after which the exception will be re-raised.

    """

    def decorator(
        coro: Callable[P, CoroutineType[Any, Any, R]],
    ) -> Callable[P, CoroutineType[Any, Any, R]]:

        @wraps(coro)  # noqa: RET503
        async def wrapped_fn(*args: P.args, **kwargs: P.kwargs) -> R:  # pyright: ignore[reportReturnType]
            for i in range(max_tries):
                try:
                    return await coro(*args, **kwargs)
                except Exception as ex:
                    if isinstance(ex, TransientModbusError.__value__):
                        if args and isinstance(args[0], _RetryStatistics):
                            statistics: _RetryStatistics = args[0]
                            statistics.retried(cast(TypeForm[TransientModbusError], ex))

                        if i == max_tries - 1:
                            raise
                    else:
                        raise

        return wrapped_fn

    return decorator


class RetryingModbusUnit(ModbusUnit, _RetryStatistics):
    """A `ModbusUnit` that retries requests on failure.

    Only methods decorated with `@retry_on_transient()` are retried on failure.
    This class wraps a provided `ModbusUnit`.
    """

    def __init__(self, unit: ModbusUnit) -> None:
        """Create a new RetryingModbusUnit instance.

        Args:
            unit (ModbusUnit): The unit to wrap.

        """

        _RetryStatistics.__init__(self)
        self._unit = unit

    @property
    def connected(self) -> bool:
        """Show whether this unit is connected to a modbus device."""

        return self._unit.connected

    @retry_on_transient()
    @override
    async def read_holding_registers(self, address: int, count: int) -> list[int]:
        """Read holding registers (FC03).

        Args:
            address (int): The register address to read.
            count (int): The amount of registers to read.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.read_holding_registers(address, count)

    @retry_on_transient()
    @override
    async def read_input_registers(self, address: int, count: int) -> list[int]:
        """Read input registers (FC04).

        Args:
            address (int): The register address to read.
            count (int): The amount of registers to read.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.read_input_registers(address, count)

    @override
    async def write_register(self, address: int, value: int) -> None:
        """Write a single register value.

        Args:
            address (int): The register to write to.
            value (int): The raw value to write.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.write_register(address, value)

    @override
    async def write_registers(self, address: int, values: list[int]) -> None:
        """Write to a set of sequential registers.

        Args:
            address (int): The register to start writing at.
            values (int): The list of values to write, one per register.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.write_registers(address, values)

    @retry_on_transient()
    @override
    async def read_coils(self, address: int, count: int) -> list[bool]:
        """Read a sequential set of coil registers.

        Args:
            address (int): The register to start reading from.
            count (int): The amount of registers to read.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.read_coils(address, count)

    @retry_on_transient()
    @override
    async def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        """Read a sequential set of discrete input registers.

        Args:
            address (int): The register to start reading from.
            count (int): The amount of registers to read.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.read_discrete_inputs(address, count)

    @override
    async def write_coil(self, address: int, value: bool) -> None:
        """Write to a single coil register.

        Args:
            address (int): The register to write to.
            value (int): The raw value to write.

        Raises:
            ModbusError: If a modbus error occurs.

        """
        return await self._unit.write_coil(address, value)

    @override
    async def write_coils(self, address: int, values: list[bool]) -> None:
        """Write to a sequential set of coil registers.

        Args:
            address (int): The register to write to.
            values (int): The list of values to write, one per register.

        Raises:
            ModbusError: If a modbus error occurs.


        """
        return await self._unit.write_coils(address, values)

    @override
    async def read_exception_status(self) -> int:
        """Read the exception status (F0x07) from the modbus device.

        The exception status reads the contents of eight Exception Status
        outputs in the remote device. Available on serial connections only.

        Returns the exception status.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.read_exception_status()

    @override
    async def report_server_id(self) -> bytes:
        """Read the server id (F0x11).

        Returns the type, current status and other information specific to
        the remote device. Available on serial connections only.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.report_server_id()

    @override
    async def mask_write_register(self, address: int, and_mask: int, or_mask: int) -> None:
        """Mask write register (F0x16).

        This function code is used to modify the contents of a specified holding
        register using a combination of an AND mask, an OR mask and the register's
        current contents.

        The function's algorithm is:
        ```
        (current_contents & and_mask) | (or_mask & (~and_mask))
        ```

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.mask_write_register(address, and_mask, or_mask)

    @override
    async def read_write_registers(
        self, read_address: int, read_count: int, write_address: int, write_values: list[int]
    ) -> list[int]:
        """Read/write multiple registers (F0x17).

        Perform a combinarion of one read and one write in a single MODBUS transaction.
        The write operation is processed before the read.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.read_write_registers(
            read_address, read_count, write_address, write_values
        )

    @override
    async def read_fifo_queue(self, address: int) -> list[int]:
        """Read FIFO queue (F0x18).

        Read the contents of a FIFO queue of registers in the remote device.

        Returns `list[int]`:
            The count of the registers in the queue, followed by the queued data.

        Raises:
            IllegalDataValueError: if the queue size exceeds 31.
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.read_fifo_queue(address)

    @override
    async def read_device_identification(self) -> dict[int, bytes]:
        """Read device identificatio (F0x2B/F0x0E).

        Read the identification and additional information relative to the physical
        and functional description of the remote device.

        Returns `dict[int, bytes]`:
            A `dict` if response values, mapped by their Object Id.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.read_device_identification()

    @override
    async def read_file_record(self, file: int, record: int, length: int) -> list[int]:
        """Read file record (F0x14).

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.read_file_record(file, record, length)

    @override
    async def write_file_record(self, file: int, record: int, values: list[int]) -> None:
        """Write file record (F0x15).

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.write_file_record(file, record, values)

    @override
    async def diagnostics(self, sub_function: int, data: int = 0) -> int:
        """Send a sub-function code with one data word.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.diagnostics(sub_function, data)

    @override
    async def get_comm_event_counter(self) -> tuple[bool, int]:
        """Get comm event counter (F0x0B).

        Get a status word and an event count from the remote device's communication
        event counter.
        By fetching the current count before and after a series of messages, a client can
        determine whether the messages were handled normally by the remote device.
        The device's event counter is incremented once for each successful message completion.
        Available on serial connections only.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.get_comm_event_counter()

    @override
    async def get_comm_event_log(self) -> bytes:
        """Get comm event log (F0x0C).

        Get a status word, event count, message count and a field of event bytes
        from the remote device.
        Available on serial connections only.

        Raises:
            IllegalFunctionError: if the remote device does not support this function.

        """
        return await self._unit.get_comm_event_log()

    @override
    def set_message_spacing(self, seconds: float) -> None:
        """Set the minimum interval between requests to this unit.

        Raises:
            ValueError: if `seconds` is negative.

        """
        return self._unit.set_message_spacing(seconds)

    @override
    def require_timeout(self, seconds: float | None) -> None:
        """Ask the link of a per-request timeout of at least `seconds`.

        Raises:
            ValueError: if `seconds` is negative.

        """
        return self._unit.require_timeout(seconds)

    @override
    def require_connect_delay(self, seconds: float | None) -> None:
        """Ask the link for a pause of at least `seconds` after it opens.

        Args:
            seconds (float|None): The pause in seconds, or `None` to withdraw the requirement.

        Raises:
            ValueError: if `seconds` is negative.

        """
        return self._unit.require_connect_delay(seconds)

    @override
    def on_connection_lost(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback when the connection's link drops.

        Returns:
            A callable to unsubscribe from this event.

        """
        return self._unit.on_connection_lost(callback)

    @override
    async def disconnect(self) -> None:
        """`async`. Drop the owning connection's link."""
        return await self._unit.disconnect()
