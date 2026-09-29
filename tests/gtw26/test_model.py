"""GTW26 model tests."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection.exceptions import IllegalFunctionError
from modbus_connection.model import Component
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.gtw26.sensors import Sensors


class MockGtw26Component(Gtw26Component):
    """A mock component for testing with actual fields."""

    register_ranges = ((0, 10),)
    test_register = Sensors.outdoor_temperature

    def __init__(self, unit: MockModbusUnit) -> None:
        super().__init__(unit)


class TestGtw26ComponentWrite:
    """Tests for Gtw26Component.write() method."""

    @pytest.mark.asyncio
    async def test_write_register_field_calls_parent(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
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
    async def test_write_register_field_retains_value_in_values(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that writing a register field retains the value in _values."""
        component = MockGtw26Component(mock_modbus_unit)
        component._register_fields = {"test_register": 100}
        component._values: dict[str, Any] = {}

        # Mock the parent write to do nothing
        with patch.object(Component, "write", new_callable=AsyncMock):
            await component.write("test_register", 42)

        # The value should be retained
        assert component._values.get("test_register") == 42

    @pytest.mark.asyncio
    async def test_write_bit_field_retains_value_in_bits(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that writing a bit field retains the value in _bits."""
        component = MockGtw26Component(mock_modbus_unit)
        component._bit_fields = {"test_bit": 200}
        component._bits: dict[str, bool] = {}

        # Mock the parent write to do nothing
        with patch.object(Component, "write", new_callable=AsyncMock):
            await component.write("test_bit", True)

        # The value should be retained
        assert component._bits.get("test_bit") is True

    @pytest.mark.asyncio
    async def test_write_unknown_field_raises_attribute_error(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that writing an unknown field raises AttributeError."""
        component = MockGtw26Component(mock_modbus_unit)

        with pytest.raises(AttributeError):
            await component.write("unknown_field", 42)

    @pytest.mark.asyncio
    async def test_write_read_only_field_raises_attribute_error(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that writing a read-only field raises AttributeError."""
        component = MockGtw26Component(mock_modbus_unit)
        # Add a read-only field
        component._register_fields = {"readonly_field": 100}
        component._read_only_fields = {"readonly_field"}

        with pytest.raises(AttributeError):
            await component.write("readonly_field", 42)

    @pytest.mark.asyncio
    async def test_write_invalid_value_raises_value_error(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that writing an invalid value raises ValueError."""
        component = MockGtw26Component(mock_modbus_unit)
        component._register_fields = {"test_field": 100}

        # Mock the parent write to raise ValueError
        async def raise_value_error(*args: Any, **kwargs: Any) -> None:
            raise ValueError("Invalid value")

        with patch.object(
            Component,
            "write",
            side_effect=raise_value_error,
        ):
            with pytest.raises(ValueError):
                await component.write("test_field", "invalid")
