"""Tests for the BufferTank."""

import pytest
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw08.buffer_tank import BufferTank
from aio_remeha_modbus.gtw08.gtw08 import GTW08


@pytest.mark.asyncio
async def test_read_buffer_tank(remeha_modbus_unit: MockModbusUnit):
    """Test that the buffer tank temperatures can be read using a modbus unit."""

    buffer_tank = BufferTank(remeha_modbus_unit)
    await buffer_tank.async_update()

    assert buffer_tank.temperature_bottom == 24.5

    # The fixture holds the INT16 null value, as if no top sensor is fitted.
    assert buffer_tank.temperature_top is None


@pytest.mark.asyncio
async def test_buffer_tank_is_polled(gtw_08: GTW08, remeha_modbus_unit: MockModbusUnit):
    """Test that the GTW-08 refreshes the buffer tank on every update."""

    assert gtw_08.buffer_tank.temperature_bottom == 24.5

    await remeha_modbus_unit.write_register(7600, 2600)
    await gtw_08.async_update()

    assert gtw_08.buffer_tank.temperature_bottom == 26.0
