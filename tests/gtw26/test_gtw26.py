"""GTW26 facade tests."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection import ModbusConnectionError
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import MockModbusUnit, WriteEvent

from aio_remeha_modbus.gtw08.errors import RemehaApiError, RemehaModbusError
from aio_remeha_modbus.gtw26 import GTW26, DetectionFailureReason, HeatingMode, HotWaterMode
from aio_remeha_modbus.gtw26.const import (
    ControllerGeneration,
    RegisterLayout,
)
from aio_remeha_modbus.gtw26.errors import GTW26ProbeError


def _seed(unit: MockModbusUnit) -> None:
    """Seed a mock unit with base layout data."""
    unit.holding.update({
        3: 400,
        4: 14,
        5: 30,
        6: 2,
        7: 205,
        102: 175,
        108: 10,
        109: 9,
        110: 25,
        14: 550,
        17: 0x58,
        18: 210,
        27: 0xFFFF,
        30: 0xFFFF,
        31: 0xFFFF,
        32: 0xFFFF,
        33: 0xFFFF,
        59: 550,
        60: 0,
        62: 500,
        75: 650,
        116: 0x0005,
        121: 800,
        427: 0x38,
        453: 0xFFFF,
        455: 3000,
        456: 15,
        457: 24,  # Type code for Gen4
        459: 505,
        462: 700,
        463: 42,
        465: 0xFFFF,
        467: 0x8000 | 120,
        470: 195,
        471: 250,
    })


def _seed_isystem(unit: MockModbusUnit) -> None:
    """Seed a mock unit with iSystem layout data."""
    unit.holding.update({
        3: 400,
        4: 14,
        5: 30,
        6: 2,
        108: 10,
        109: 9,
        110: 25,
        457: 24,  # Type code for Gen4
        600: 412,
        601: 205,
        602: 650,
        614: 210,
        619: 215,
        679: 12,
        680: 30,
        681: 2,
        682: 10,
        683: 9,
        684: 25,
        126: 0x0180,
        231: 0x2000,
        232: 0x2023,
        233: 0x2038,
        247: 0x0000,
        659: 0x58,
        640: 6,
        641: 6,
        653: 0x58,
        661: 200,
        662: 100,
        663: 950,
        669: 40,
        670: 150,
        671: 500,
    })


class TestAutoSetup:
    """Tests for the auto-setup path."""

    @pytest.mark.asyncio
    async def test_async_setup_detects_base_layout_when_not_provided(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _async_setup detects BASE layout when layout is None."""
        _seed(mock_modbus_unit)
        # Fail iSystem reads to force BASE detection
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26("test", mock_modbus_unit)
        await device._async_setup()

        assert device._layout is RegisterLayout.BASE
        assert device._generation is ControllerGeneration.GENERATION_4
        assert device._setup_complete is True

    @pytest.mark.asyncio
    async def test_async_setup_detects_isystem_layout_when_not_provided(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _async_setup detects ISYSTEM layout when layout is None."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit)
        await device._async_setup()

        assert device._layout is RegisterLayout.ISYSTEM
        assert device._generation is ControllerGeneration.GENERATION_4
        assert device._setup_complete is True

    @pytest.mark.asyncio
    async def test_async_setup_uses_provided_layout_and_generation(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _async_setup uses provided layout and generation."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_3,
        )
        await device._async_setup()

        assert device._layout is RegisterLayout.BASE
        assert device._generation is ControllerGeneration.GENERATION_3
        assert device._setup_complete is True

    @pytest.mark.asyncio
    async def test_async_setup_raises_probe_error_on_failed_detection(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _async_setup raises GTW26ProbeError when detection fails."""
        # Fail all reads to simulate NOT_A_GTW26
        mock_modbus_unit.fail_read(3, IllegalDataAddressError())
        mock_modbus_unit.fail_read(108, IllegalDataAddressError())
        mock_modbus_unit.fail_read(457, IllegalDataAddressError())
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26("test", mock_modbus_unit)

        with pytest.raises(GTW26ProbeError):
            await device._async_setup()

    @pytest.mark.asyncio
    async def test_configured_message_spacing_survives_auto_detection(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that a caller-configured spacing is not reset by detection."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit, message_spacing_seconds=0.5)
        await device.async_update()

        assert mock_modbus_unit.message_spacing == 0.5

    @pytest.mark.asyncio
    async def test_detect_applies_requested_message_spacing(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that detection constructs its device with the given spacing."""
        _seed_isystem(mock_modbus_unit)

        detection = await GTW26.async_detect(mock_modbus_unit, message_spacing_seconds=0.5)

        assert mock_modbus_unit.message_spacing == 0.5
        assert detection.device is not None
        assert detection.device._message_spacing_seconds == 0.5

    @pytest.mark.asyncio
    async def test_setup_does_not_probe_when_layout_and_generation_known(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that a fully configured device sets up without identity probes."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )

        await device.async_ensure_setup()

        assert mock_modbus_unit.read_events == []

    @pytest.mark.asyncio
    async def test_isystem_setup_treats_missing_generation_as_terminal(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that an iSystem device without a generation never probes identity."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit, layout=RegisterLayout.ISYSTEM)
        await device.async_ensure_setup()

        assert device.generation is None
        assert mock_modbus_unit.read_events == []

    @pytest.mark.asyncio
    async def test_base_setup_without_generation_probes_only_base_identity(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that a base device without a generation skips the iSystem probe."""
        _seed(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit, layout=RegisterLayout.BASE)
        await device.async_ensure_setup()

        blocks = [(event.address, event.count) for event in mock_modbus_unit.read_events]
        assert blocks == [(3, 4), (108, 3), (457, 1)]
        assert device.generation is ControllerGeneration.GENERATION_4

    @pytest.mark.parametrize(
        ("type_code", "failure_reason"),
        [
            pytest.param(21, DetectionFailureReason.UNKNOWN_MODEL, id="known_model_code"),
            pytest.param(999, DetectionFailureReason.NOT_A_GTW26, id="unknown_model_code"),
        ],
    )
    @pytest.mark.asyncio
    async def test_base_setup_without_generation_raises_on_unmapped_type_code(
        self,
        mock_modbus_unit: MockModbusUnit,
        type_code: int,
        failure_reason: DetectionFailureReason,
    ) -> None:
        """Test that a base device whose type code names no generation fails setup."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.holding[457] = type_code

        device = GTW26("test", mock_modbus_unit, layout=RegisterLayout.BASE)

        with pytest.raises(GTW26ProbeError) as caught:
            await device.async_ensure_setup()

        assert caught.value.detection.failure_reason is failure_reason

    @pytest.mark.asyncio
    async def test_async_setup_only_detects_once(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test that _async_setup only calls detect once."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26("test", mock_modbus_unit)

        with patch.object(
            device._unit, "read_holding_registers", wraps=device._unit.read_holding_registers
        ) as mock_read:
            await device._async_setup()
            call_count_before = mock_read.call_count
            await device._async_setup()  # Should not read again
            call_count_after = mock_read.call_count

        # Second call should not trigger new reads
        assert call_count_after == call_count_before

    @pytest.mark.asyncio
    async def test_async_ensure_setup_calls_setup_once(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that async_ensure_setup only calls _async_setup once."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26("test", mock_modbus_unit)

        async def mock_setup() -> None:
            device._setup_complete = True

        mock_setup_func = AsyncMock(side_effect=mock_setup)
        with patch.object(device, "_async_setup", mock_setup_func):
            await device.async_ensure_setup()
            await device.async_ensure_setup()  # Should not call setup again

        mock_setup_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_ensure_setup_handles_concurrent_calls(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that async_ensure_setup handles concurrent calls correctly."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26("test", mock_modbus_unit)

        with patch.object(
            device._unit, "read_holding_registers", wraps=device._unit.read_holding_registers
        ) as mock_read:
            await asyncio.gather(
                device.async_ensure_setup(),
                device.async_ensure_setup(),
                device.async_ensure_setup(),
            )
            call_count = mock_read.call_count

        # One detection only: three base identity blocks plus two iSystem identity blocks.
        assert call_count == 5


class TestProperties:
    """Tests for zone_a_present, zone_b_present, zone_c_present, hot_water_present properties."""

    @pytest.mark.asyncio
    async def test_zone_a_present_with_sensor(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test zone_a_present returns True when zone A has a sensor."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        await device.async_update()

        assert device.zone_a_present is True

    @pytest.mark.asyncio
    async def test_zone_a_present_with_force(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test zone_a_present returns True when force_zone_a is True."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
            force_zone_a=True,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        # No sensor data
        assert device.zone_a_present is True

    @pytest.mark.asyncio
    async def test_zone_a_present_without_sensor_or_force(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test zone_a_present returns False when no sensor and not forced."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        # Remove temperature data (room_temperature at 18, calculated_temperature at 21)
        mock_modbus_unit.holding[18] = 0xFFFF
        mock_modbus_unit.holding[21] = 0xFFFF
        await device.async_update()

        assert device.zone_a_present is False

    @pytest.mark.asyncio
    async def test_zone_b_present_with_sensor(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test zone_b_present returns True when zone B has a sensor."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        # Add zone B sensor data - room_temperature is at register 27
        mock_modbus_unit.holding[27] = 210
        await device.async_update()

        assert device.zone_b_present is True

    @pytest.mark.asyncio
    async def test_zone_b_present_with_force(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test zone_b_present returns True when force_zone_b is True."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
            force_zone_b=True,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        assert device.zone_b_present is True

    @pytest.mark.asyncio
    async def test_zone_b_present_without_sensor_or_force(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test zone_b_present returns False when no sensor and not forced."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        # Remove all temperature data for zone B
        # room_temperature at 27, calculated_temperature at 32, supply_temperature at 33
        # min_temperature at 30, max_temperature at 31
        mock_modbus_unit.holding[27] = 0xFFFF
        mock_modbus_unit.holding[30] = 0xFFFF
        mock_modbus_unit.holding[31] = 0xFFFF
        mock_modbus_unit.holding[32] = 0xFFFF
        mock_modbus_unit.holding[33] = 0xFFFF
        await device.async_update()

        assert device.zone_b_present is False

    @pytest.mark.asyncio
    async def test_zone_c_present_returns_false_for_base_layout(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test zone_c_present returns False for BASE layout."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        assert device.zone_c_present is False

    @pytest.mark.asyncio
    async def test_zone_c_present_with_sensor_isystem(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test zone_c_present returns True when zone C has a sensor in iSystem."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.ISYSTEM,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.ISYSTEM, device.generation)

        # Add zone C sensor data
        await device.async_update()

        assert device.zone_c_present is True

    @pytest.mark.asyncio
    async def test_zone_c_present_with_force_isystem(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test zone_c_present returns True when force_zone_c is True in iSystem."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.ISYSTEM,
            generation=ControllerGeneration.GENERATION_4,
            force_zone_c=True,
        )
        device._setup_bundles(RegisterLayout.ISYSTEM, device.generation)

        assert device.zone_c_present is True

    @pytest.mark.asyncio
    async def test_zone_c_present_without_sensor_or_force_isystem(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test zone_c_present returns False when no sensor and not forced in iSystem."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.ISYSTEM,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.ISYSTEM, device.generation)

        # Remove zone C sensor data
        mock_modbus_unit.holding[618] = 0xFFFF
        mock_modbus_unit.holding[619] = 0xFFFF
        await device.async_update()

        assert device.zone_c_present is False

    @pytest.mark.asyncio
    async def test_hot_water_present_with_sensor_base(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test hot_water_present returns True when hot water has a sensor in BASE."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        await device.async_update()

        assert device.hot_water_present is True

    @pytest.mark.asyncio
    async def test_hot_water_present_with_dpsm_sensor_base(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test hot_water_present returns True when hot water has DPSM sensor in BASE."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        # Remove primary sensor but keep DPSM
        mock_modbus_unit.holding[62] = 0xFFFF
        mock_modbus_unit.holding[459] = 505
        await device.async_update()

        assert device.hot_water_present is True

    @pytest.mark.asyncio
    async def test_hot_water_present_without_sensor_base(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test hot_water_present returns False when no sensor in BASE."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        # Remove all sensors
        mock_modbus_unit.holding[62] = 0xFFFF
        mock_modbus_unit.holding[459] = 0xFFFF
        await device.async_update()

        assert device.hot_water_present is False

    @pytest.mark.asyncio
    async def test_hot_water_present_with_sensor_isystem(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test hot_water_present returns True when hot water has a sensor in iSystem."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.ISYSTEM,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.ISYSTEM, device.generation)

        # Add hot water sensor - temperature is at register 614
        mock_modbus_unit.holding[614] = 550
        await device.async_update()

        assert device.hot_water_present is True

    @pytest.mark.parametrize(
        ("zone", "force_kwargs", "expected"),
        [
            pytest.param("A", {}, False, id="zone-a-unforced"),
            pytest.param("A", {"force_zone_a": True}, True, id="zone-a-forced"),
            pytest.param("B", {}, False, id="zone-b-unforced"),
            pytest.param("B", {"force_zone_b": True}, True, id="zone-b-forced"),
        ],
    )
    @pytest.mark.asyncio
    async def test_zone_present_without_zone_component(
        self,
        mock_modbus_unit: MockModbusUnit,
        zone: str,
        force_kwargs: dict[str, bool],
        expected: bool,
    ) -> None:
        """Test that a zone missing from climate_zones is present only when forced."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
            **force_kwargs,
        )
        await device.async_ensure_setup()
        device.climate_zones.pop(zone)

        assert getattr(device, f"zone_{zone.lower()}_present") is expected

    @pytest.mark.asyncio
    async def test_zone_c_present_without_zone_component_isystem(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that zone_c_present is False when zone C is missing from climate_zones."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.ISYSTEM,
            generation=ControllerGeneration.GENERATION_4,
        )
        await device.async_ensure_setup()
        device.climate_zones.pop("C")

        assert device.zone_c_present is False

    @pytest.mark.asyncio
    async def test_hot_water_present_without_hot_water_component(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that hot_water_present is False when the hot water component is None."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        await device.async_ensure_setup()
        device.hot_water = None

        assert device.hot_water_present is False


class TestConstructor:
    """Tests for constructor-applied unit requirements."""

    def test_request_timeout_is_required_on_unit(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test that request_timeout is forwarded to the unit."""
        GTW26("test", mock_modbus_unit, request_timeout=3.0)

        assert mock_modbus_unit.required_timeout == 3.0

    def test_without_request_timeout_the_unit_keeps_its_own(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that the constructor leaves the unit timeout unchanged by default."""
        GTW26("test", mock_modbus_unit)

        assert mock_modbus_unit.required_timeout is None


class TestReadRegisters:
    """Tests for async_read_registers method."""

    @pytest.mark.asyncio
    async def test_read_registers_single_register(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test reading a single register."""
        _seed(mock_modbus_unit)
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        # decode_bytes uses big-endian, so we need to use >H to unpack correctly
        result = await device.async_read_registers(457, count=1, struct_format=">H")

        # 457 contains 24
        assert result == (24,)

    @pytest.mark.asyncio
    async def test_read_registers_default_format_is_big_endian(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that the default struct format decodes big-endian register words."""
        _seed(mock_modbus_unit)
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        result = await device.async_read_registers(457, count=1)

        # 457 contains 24; a native-order default would mis-decode on little-endian hosts
        assert result == (24,)

    @pytest.mark.asyncio
    async def test_read_registers_multiple_registers(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test reading multiple registers."""
        _seed(mock_modbus_unit)
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        # decode_bytes uses big-endian, so we need to use >HH to unpack correctly
        result = await device.async_read_registers(457, count=2, struct_format=">HH")

        assert result == (24, 0)  # 457=24, 458=0 (not set)

    @pytest.mark.asyncio
    async def test_read_registers_with_struct_format(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test reading registers with a specific struct format."""
        _seed(mock_modbus_unit)
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        # Read as unsigned short - 457 contains 24
        # decode_bytes uses big-endian, so we need to use >H to unpack correctly
        result = await device.async_read_registers(457, count=1, struct_format=">H")

        assert result == (24,)

    @pytest.mark.asyncio
    async def test_read_registers_rejects_zero_count(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that read_registers rejects count < 1."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        with pytest.raises(ValueError, match="Illegal count 0"):
            await device.async_read_registers(457, count=0)

    @pytest.mark.asyncio
    async def test_read_registers_rejects_excessive_count(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that read_registers rejects count > GTW26_MAX_SPAN (125)."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        with pytest.raises(ValueError, match="Illegal count"):
            await device.async_read_registers(457, count=126)


class TestNudgePanel:
    """Tests for the _nudge_panel mechanism."""

    @pytest.mark.asyncio
    async def test_nudge_panel_writes_to_panel_nudge_register(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _nudge_panel writes to the panel nudge register."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_complete = True

        writes: list[WriteEvent] = []
        mock_modbus_unit.on_write(writes.append)

        # Mock asyncio.sleep to avoid actual delay
        with patch("aio_remeha_modbus.gtw26.gtw26.asyncio.sleep", AsyncMock()):
            await device._nudge_panel()

        # The panel refresh is a 1-then-0 toggle on PANEL_NUDGE_REGISTER (13)
        assert [(event.address, event.values) for event in writes] == [(13, [1]), (13, [0])]

    @pytest.mark.asyncio
    async def test_nudge_panel_called_after_heating_mode_write_gen4(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _nudge_panel is called after heating mode write for Gen4."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        with patch.object(device, "_nudge_panel", AsyncMock()) as mock_nudge:
            await device.async_set_heating_mode("A", HeatingMode.AUTO)

        mock_nudge.assert_called_once()

    @pytest.mark.asyncio
    async def test_nudge_panel_not_called_for_gen3(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test that _nudge_panel is not called for Gen3."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_3,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        with patch.object(device, "_nudge_panel", AsyncMock()) as mock_nudge:
            await device.async_set_heating_mode("A", HeatingMode.AUTO)

        mock_nudge.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_panel_called_after_hot_water_mode_write_gen4(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _nudge_panel is called after hot water mode write for Gen4."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        with patch.object(device, "_nudge_panel", AsyncMock()) as mock_nudge:
            await device.async_set_hot_water_mode(HotWaterMode.TEMP)

        mock_nudge.assert_called_once()


class TestErrorPaths:
    """Tests for error handling paths."""

    @pytest.mark.asyncio
    async def test_async_update_raises_connection_error(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that async_update raises ModbusConnectionError."""
        _seed(mock_modbus_unit)
        mock_modbus_unit.fail_read(600, IllegalDataAddressError())
        mock_modbus_unit.fail_read(679, IllegalDataAddressError())

        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)

        mock_modbus_unit.fail_requests(ModbusConnectionError("link down"))

        with pytest.raises(ModbusConnectionError):
            await device.async_update()

    @pytest.mark.asyncio
    async def test_health_check_success(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test that async_health_check succeeds when register is readable."""
        _seed(mock_modbus_unit)

        await GTW26.async_health_check(mock_modbus_unit)

    @pytest.mark.asyncio
    async def test_health_check_raises_on_error(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test that async_health_check raises RemehaModbusError on ModbusError."""
        mock_modbus_unit.fail_read(457, IllegalDataAddressError())

        with pytest.raises(RemehaModbusError) as exc_info:
            await GTW26.async_health_check(mock_modbus_unit)

        assert exc_info.value.translation_key == "health_check_failed"

    @pytest.mark.asyncio
    async def test_policy_raises_when_layout_not_set(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _policy raises RemehaApiError when layout is not set."""
        device = GTW26("test", mock_modbus_unit)
        device._layout = None

        with pytest.raises(RemehaApiError) as exc_info:
            device._policy()

        assert exc_info.value.translation_key == "layout_not_set_up"

    @pytest.mark.asyncio
    async def test_async_setup_with_no_pool_does_not_fail(
        self, mock_modbus_unit: MockModbusUnit
    ) -> None:
        """Test that _poll_group handles None pool gracefully."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
            generation=ControllerGeneration.GENERATION_4,
        )
        device._setup_bundles(RegisterLayout.BASE, device.generation)
        device._pool = None

        # Should not raise even with None pool
        report = await device.async_update()

        # Should complete without error but with no updates
        assert len(report.updated) == 0 or not report.complete


class TestStaticProperties:
    """Tests for static properties."""

    def test_name_property(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test the name property."""
        device = GTW26("my_device", mock_modbus_unit)

        assert device.name == "my_device"

    def test_layout_property(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test the layout property."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
        )

        assert device.layout is RegisterLayout.BASE

    def test_generation_property(self, mock_modbus_unit: MockModbusUnit) -> None:
        """Test the generation property."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            generation=ControllerGeneration.GENERATION_4,
        )

        assert device.generation is ControllerGeneration.GENERATION_4
