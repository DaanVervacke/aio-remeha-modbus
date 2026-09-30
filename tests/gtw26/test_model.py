"""GTW26 model tests."""

from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection.mock import MockModbusUnit
from modbus_connection.model import Component, integer

from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.gtw26.sensors import Sensors
from aio_remeha_modbus.helpers.fields import int_clamp, int_range


class MockGtw26Component(Gtw26Component):
    """A mock component for testing with actual fields."""

    register_ranges = ((0, 10),)
    test_register = Sensors.outdoor_temperature
    clamped_register = integer(1, signed=False, writable=int_clamp(0, 15))
    ranged_register = integer(2, signed=False, writable=int_range(0, 15))


class TestGtw26ComponentWrite:
    """Tests for Gtw26Component.write() method."""

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_register_field_calls_parent(mock_modbus_unit: MockModbusUnit) -> None:
        """Test that write calls the parent class write method."""
        component = MockGtw26Component(mock_modbus_unit)

        with patch.object(
            Component,
            "write",
            new_callable=AsyncMock,
        ) as mock_parent_write:
            await component.write("test_register", 42.0)

            # Parent write should have been called with keyword arguments
            mock_parent_write.assert_called_once_with(field="test_register", value=42.0)

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_register_field_retains_value_in_values(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that writing a register field retains the value in _values."""
        component = MockGtw26Component(mock_modbus_unit)

        with patch.object(Component, "write", new_callable=AsyncMock):
            await component.write("test_register", 42)

        assert component._values["test_register"] == 42

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_register_field_retains_validator_coerced_value(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that a clamping write retains the effective value, not the request."""
        component = MockGtw26Component(mock_modbus_unit)

        with patch.object(Component, "write", new_callable=AsyncMock) as mock_parent_write:
            await component.write("clamped_register", 40)

        mock_parent_write.assert_called_once_with(field="clamped_register", value=15)
        assert component._values["clamped_register"] == 15

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_bit_field_retains_value_in_bits(mock_modbus_unit: MockModbusUnit) -> None:
        """Test that writing a bit field retains the value in _bits."""
        component = MockGtw26Component(mock_modbus_unit)
        component._bit_fields = {"test_bit": 200}
        component._bits = {}

        with patch.object(Component, "write", new_callable=AsyncMock):
            await component.write("test_bit", True)

        assert component._bits["test_bit"] is True

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_unknown_field_raises_attribute_error(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that writing an unknown field raises AttributeError."""
        component = MockGtw26Component(mock_modbus_unit)

        with pytest.raises(AttributeError):
            await component.write("unknown_field", 42)

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_read_only_field_raises_attribute_error(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that writing a read-only field raises AttributeError."""
        component = MockGtw26Component(mock_modbus_unit)

        with pytest.raises(AttributeError, match="read-only"):
            await component.write("test_register", 42)

    @pytest.mark.asyncio
    @staticmethod
    async def test_write_invalid_value_raises_value_error(mock_modbus_unit: MockModbusUnit) -> None:
        """Test that writing an invalid value raises ValueError."""
        component = MockGtw26Component(mock_modbus_unit)

        with pytest.raises(ValueError, match="convert"):
            await component.write("clamped_register", "invalid")

    @pytest.mark.parametrize("value", [-1, 16, 40])
    @pytest.mark.asyncio
    @staticmethod
    async def test_rejected_write_raises_before_io(
        mock_modbus_unit: MockModbusUnit, value: int
    ) -> None:
        """Test that an out-of-range write raises before any Modbus I/O."""
        component = MockGtw26Component(mock_modbus_unit)
        writes: list[object] = []
        mock_modbus_unit.on_write(writes.append)

        with pytest.raises(ValueError, match="between 0 and 15"):
            await component.write("ranged_register", value)

        assert writes == []
        assert 2 not in mock_modbus_unit.holding
        assert "ranged_register" not in component._values
