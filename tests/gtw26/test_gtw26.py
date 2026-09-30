"""GTW26 facade tests."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from modbus_connection import ModbusConnectionError
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import MockModbusUnit, WriteEvent

from aio_remeha_modbus.gtw08.errors import RemehaApiError
from aio_remeha_modbus.gtw26 import GTW26, DetectionFailureReason, HeatingMode, HotWaterMode
from aio_remeha_modbus.gtw26.const import (
    ControllerGeneration,
    RegisterLayout,
)
from aio_remeha_modbus.gtw26.errors import GTW26ProbeError
from tests.gtw26.conftest import Gtw26Factory, LayoutGtw26Factory


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
    @staticmethod
    async def test_async_setup_detects_base_layout_when_not_provided(
        mock_modbus_unit: MockModbusUnit,
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
    @staticmethod
    async def test_async_setup_detects_isystem_layout_when_not_provided(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that _async_setup detects ISYSTEM layout when layout is None."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit)
        await device._async_setup()

        assert device._layout is RegisterLayout.ISYSTEM
        assert device._generation is ControllerGeneration.GENERATION_4
        assert device._setup_complete is True

    @pytest.mark.asyncio
    @staticmethod
    async def test_async_setup_uses_provided_layout_and_generation(
        mock_modbus_unit: MockModbusUnit,
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
    @staticmethod
    async def test_configured_message_spacing_survives_auto_detection(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that a caller-configured spacing is not reset by detection."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit, message_spacing_seconds=0.5)
        await device.async_update()

        assert mock_modbus_unit.message_spacing == 0.5

    @pytest.mark.asyncio
    @staticmethod
    async def test_detect_applies_requested_message_spacing(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that detection constructs its device with the given spacing."""
        _seed_isystem(mock_modbus_unit)

        detection = await GTW26.async_detect(mock_modbus_unit, message_spacing_seconds=0.5)

        assert mock_modbus_unit.message_spacing == 0.5
        assert detection.device is not None
        assert detection.device._message_spacing_seconds == 0.5

    @pytest.mark.asyncio
    @staticmethod
    async def test_setup_does_not_probe_when_layout_and_generation_known(
        mock_modbus_unit: MockModbusUnit,
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
    @staticmethod
    async def test_isystem_setup_treats_missing_generation_as_terminal(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that an iSystem device without a generation never probes identity."""
        _seed_isystem(mock_modbus_unit)

        device = GTW26("test", mock_modbus_unit, layout=RegisterLayout.ISYSTEM)
        await device.async_ensure_setup()

        assert device.generation is None
        assert mock_modbus_unit.read_events == []

    @pytest.mark.asyncio
    @staticmethod
    async def test_base_setup_without_generation_probes_only_base_identity(
        mock_modbus_unit: MockModbusUnit,
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
    @staticmethod
    async def test_base_setup_without_generation_raises_on_unmapped_type_code(
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
    @staticmethod
    async def test_async_setup_only_detects_once(mock_modbus_unit: MockModbusUnit) -> None:
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
    @staticmethod
    async def test_async_ensure_setup_calls_setup_once(mock_modbus_unit: MockModbusUnit) -> None:
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
    @staticmethod
    async def test_async_ensure_setup_handles_concurrent_calls(
        mock_modbus_unit: MockModbusUnit,
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
    """Tests for the zone_a/b/c_present and hot_water_present properties."""

    # One blank set per zone: every register the presence check reads, set to
    # the absent sentinel, so a seeded sensor register is the only signal left.
    _ZONE_CASES = [
        pytest.param(
            RegisterLayout.BASE,
            "a",
            {18: 0xFFFF, 21: 0xFFFF},
            18,
            id="base-a",
        ),
        pytest.param(
            RegisterLayout.BASE,
            "b",
            {27: 0xFFFF, 30: 0xFFFF, 31: 0xFFFF, 32: 0xFFFF, 33: 0xFFFF},
            27,
            id="base-b",
        ),
        pytest.param(
            RegisterLayout.ISYSTEM,
            "c",
            {618: 0xFFFF, 619: 0xFFFF},
            618,
            id="isystem-c",
        ),
    ]

    @pytest.mark.parametrize(("layout", "zone", "blank", "sensor_address"), _ZONE_CASES)
    @pytest.mark.asyncio
    @staticmethod
    async def test_zone_present_with_sensor(
        mock_modbus_unit: MockModbusUnit,
        gtw26: LayoutGtw26Factory,
        layout: RegisterLayout,
        zone: str,
        blank: dict[int, int],
        sensor_address: int,
    ) -> None:
        """A zone counts as present once its room sensor answers."""
        device = await gtw26(mock_modbus_unit, layout)
        mock_modbus_unit.holding.update(blank)
        mock_modbus_unit.holding[sensor_address] = 210
        await device.async_update()

        assert getattr(device, f"zone_{zone}_present") is True

    @pytest.mark.parametrize(("layout", "zone", "blank", "sensor_address"), _ZONE_CASES)
    @pytest.mark.asyncio
    @staticmethod
    async def test_zone_absent_without_sensor_or_force(
        mock_modbus_unit: MockModbusUnit,
        gtw26: LayoutGtw26Factory,
        layout: RegisterLayout,
        zone: str,
        blank: dict[int, int],
        sensor_address: int,
    ) -> None:
        """A zone without a sensor reading and without the force flag is absent."""
        device = await gtw26(mock_modbus_unit, layout)
        mock_modbus_unit.holding.update(blank)
        await device.async_update()

        assert getattr(device, f"zone_{zone}_present") is False

    @pytest.mark.parametrize(
        ("layout", "zone", "force_kwargs"),
        [
            pytest.param(RegisterLayout.BASE, "a", {"force_circuit_a": True}, id="base-a"),
            pytest.param(RegisterLayout.BASE, "b", {"force_circuit_b": True}, id="base-b"),
            pytest.param(RegisterLayout.ISYSTEM, "c", {"force_circuit_c": True}, id="isystem-c"),
        ],
    )
    @pytest.mark.asyncio
    @staticmethod
    async def test_zone_present_when_forced(
        mock_modbus_unit: MockModbusUnit,
        gtw26: LayoutGtw26Factory,
        layout: RegisterLayout,
        zone: str,
        force_kwargs: dict[str, bool],
    ) -> None:
        """The force flags report a zone as present before the first poll."""
        device = await gtw26(mock_modbus_unit, layout, **force_kwargs)

        assert getattr(device, f"zone_{zone}_present") is True

    @pytest.mark.asyncio
    @staticmethod
    async def test_zone_c_absent_on_base_layout(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Zone C does not exist on the base layout."""
        device = await base_gtw26(mock_modbus_unit)

        assert device.zone_c_present is False

    @pytest.mark.asyncio
    @staticmethod
    async def test_hot_water_presence_follows_temperature_isystem(
        mock_modbus_unit: MockModbusUnit,
        isystem_gtw26: Gtw26Factory,
    ) -> None:
        """iSystem hot-water presence follows the temperature register 603."""
        device = await isystem_gtw26(mock_modbus_unit)

        mock_modbus_unit.holding[603] = 0xFFFF
        await device.async_update()
        assert device.hot_water_present is False

        mock_modbus_unit.holding[603] = 550
        await device.async_update()
        assert device.hot_water_present is True

    @pytest.mark.parametrize(
        ("zone", "force_kwargs", "expected"),
        [
            pytest.param("A", {}, False, id="zone-a-unforced"),
            pytest.param("A", {"force_circuit_a": True}, True, id="zone-a-forced"),
            pytest.param("B", {}, False, id="zone-b-unforced"),
            pytest.param("B", {"force_circuit_b": True}, True, id="zone-b-forced"),
        ],
    )
    @pytest.mark.asyncio
    @staticmethod
    async def test_zone_present_without_zone_component(
        mock_modbus_unit: MockModbusUnit,
        zone: str,
        force_kwargs: dict[str, bool],
        expected: bool,
        base_gtw26: Gtw26Factory,
    ) -> None:
        """A zone missing from climate_zones is present only when forced."""
        device = await base_gtw26(mock_modbus_unit, **force_kwargs)
        device.climate_zones.pop(zone)

        assert getattr(device, f"zone_{zone.lower()}_present") is expected

    @pytest.mark.asyncio
    @staticmethod
    async def test_zone_c_present_without_zone_component_isystem(
        mock_modbus_unit: MockModbusUnit,
        isystem_gtw26: Gtw26Factory,
    ) -> None:
        """Zone C missing from climate_zones is never present, even when forced."""
        device = await isystem_gtw26(mock_modbus_unit, force_circuit_c=True)
        device.climate_zones.pop("C")

        assert device.zone_c_present is False

    @pytest.mark.asyncio
    @staticmethod
    async def test_hot_water_present_without_hot_water_component(
        mock_modbus_unit: MockModbusUnit,
        base_gtw26: Gtw26Factory,
    ) -> None:
        """Hot water missing from the facade is never present."""
        device = await base_gtw26(mock_modbus_unit)
        device.hot_water = None

        assert device.hot_water_present is False


class TestConstructor:
    """Tests for constructor-applied unit requirements."""

    @staticmethod
    def test_request_timeout_is_required_on_unit(mock_modbus_unit: MockModbusUnit) -> None:
        """Test that request_timeout is forwarded to the unit."""
        GTW26("test", mock_modbus_unit, request_timeout=3.0)

        assert mock_modbus_unit.required_timeout == 3.0

    @staticmethod
    def test_without_request_timeout_the_unit_keeps_its_own(
        mock_modbus_unit: MockModbusUnit,
    ) -> None:
        """Test that the constructor leaves the unit timeout unchanged by default."""
        GTW26("test", mock_modbus_unit)

        assert mock_modbus_unit.required_timeout is None


class TestReadRegisters:
    """Tests for async_read_registers method."""

    @pytest.mark.asyncio
    @staticmethod
    async def test_read_registers_single_register(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test reading a single register."""
        _seed(mock_modbus_unit)
        device = await base_gtw26(mock_modbus_unit)

        # decode_bytes uses big-endian, so we need to use >H to unpack correctly
        result = await device.async_read_registers(457, count=1, struct_format=">H")

        # 457 contains 24
        assert result == (24,)

    @pytest.mark.asyncio
    @staticmethod
    async def test_read_registers_default_format_is_big_endian(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that the default struct format decodes big-endian register words."""
        _seed(mock_modbus_unit)
        device = await base_gtw26(mock_modbus_unit)

        result = await device.async_read_registers(457, count=1)

        # 457 contains 24; a native-order default would mis-decode on little-endian hosts
        assert result == (24,)

    @pytest.mark.asyncio
    @staticmethod
    async def test_read_registers_multiple_registers(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test reading multiple registers."""
        _seed(mock_modbus_unit)
        device = await base_gtw26(mock_modbus_unit)

        # decode_bytes uses big-endian, so we need to use >HH to unpack correctly
        result = await device.async_read_registers(457, count=2, struct_format=">HH")

        assert result == (24, 0)  # 457=24, 458=0 (not set)

    @pytest.mark.asyncio
    @staticmethod
    async def test_read_registers_with_struct_format(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test reading registers with a specific struct format."""
        _seed(mock_modbus_unit)
        device = await base_gtw26(mock_modbus_unit)

        # Read as unsigned short - 457 contains 24
        # decode_bytes uses big-endian, so we need to use >H to unpack correctly
        result = await device.async_read_registers(457, count=1, struct_format=">H")

        assert result == (24,)

    @pytest.mark.asyncio
    @staticmethod
    async def test_read_registers_rejects_zero_count(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that read_registers rejects count < 1."""
        device = await base_gtw26(mock_modbus_unit)

        with pytest.raises(ValueError, match="Illegal count 0"):
            await device.async_read_registers(457, count=0)

    @pytest.mark.asyncio
    @staticmethod
    async def test_read_registers_rejects_excessive_count(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that read_registers rejects count > GTW26_MAX_SPAN (125)."""
        device = await base_gtw26(mock_modbus_unit)

        with pytest.raises(ValueError, match="Illegal count"):
            await device.async_read_registers(457, count=126)


class TestNudgePanel:
    """Tests for the _nudge_panel mechanism."""

    @pytest.mark.asyncio
    @staticmethod
    async def test_nudge_panel_writes_to_panel_nudge_register(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that _nudge_panel writes to the panel nudge register."""
        device = await base_gtw26(mock_modbus_unit)

        writes: list[WriteEvent] = []
        mock_modbus_unit.on_write(writes.append)

        # Mock asyncio.sleep to avoid actual delay
        with patch("aio_remeha_modbus.gtw26.gtw26.asyncio.sleep", AsyncMock()):
            await device._nudge_panel()

        # The panel refresh is a 1-then-0 toggle on PANEL_NUDGE_REGISTER (13)
        assert [(event.address, event.values) for event in writes] == [(13, [1]), (13, [0])]

    @pytest.mark.asyncio
    @staticmethod
    async def test_nudge_panel_called_after_heating_mode_write_gen4(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that _nudge_panel is called after heating mode write for Gen4."""
        device = await base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)

        with patch.object(device, "_nudge_panel", AsyncMock()) as mock_nudge:
            await device.async_set_heating_mode("A", HeatingMode.AUTO)

        mock_nudge.assert_called_once()

    @pytest.mark.asyncio
    @staticmethod
    async def test_nudge_panel_not_called_for_gen3(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that _nudge_panel is not called for Gen3."""
        device = await base_gtw26(mock_modbus_unit)

        with patch.object(device, "_nudge_panel", AsyncMock()) as mock_nudge:
            await device.async_set_heating_mode("A", HeatingMode.AUTO)

        mock_nudge.assert_not_called()

    @pytest.mark.asyncio
    @staticmethod
    async def test_nudge_panel_called_after_hot_water_mode_write_gen4(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that _nudge_panel is called after hot water mode write for Gen4."""
        device = await base_gtw26(mock_modbus_unit, variant=ControllerGeneration.GENERATION_4)

        with patch.object(device, "_nudge_panel", AsyncMock()) as mock_nudge:
            await device.async_set_hot_water_mode(HotWaterMode.TEMP)

        mock_nudge.assert_called_once()


class TestErrorPaths:
    """Tests for error handling paths."""

    @pytest.mark.asyncio
    @staticmethod
    async def test_async_update_raises_connection_error(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that async_update raises ModbusConnectionError."""
        device = await base_gtw26(mock_modbus_unit)
        mock_modbus_unit.fail_requests(ModbusConnectionError("link down"))

        with pytest.raises(ModbusConnectionError):
            await device.async_update()

    @pytest.mark.asyncio
    @staticmethod
    async def test_policy_raises_when_layout_not_set(mock_modbus_unit: MockModbusUnit) -> None:
        """Test that _policy raises RemehaApiError when layout is not set."""
        device = GTW26("test", mock_modbus_unit)
        device._layout = None

        with pytest.raises(RemehaApiError) as exc_info:
            device._policy()

        assert exc_info.value.translation_key == "layout_not_set_up"

    @pytest.mark.asyncio
    @staticmethod
    async def test_async_setup_with_no_pool_does_not_fail(
        mock_modbus_unit: MockModbusUnit, base_gtw26: Gtw26Factory
    ) -> None:
        """Test that _poll_group handles None pool gracefully."""
        device = await base_gtw26(mock_modbus_unit)
        device._pool = None

        # A missing pool skips the pooled poll entirely: nothing updates, nothing fails.
        report = await device.async_update()

        assert report.updated == set()
        assert report.failed == {}
        assert report.complete


class TestStaticProperties:
    """Tests for static properties."""

    @staticmethod
    def test_name_property(mock_modbus_unit: MockModbusUnit) -> None:
        """Test the name property."""
        device = GTW26("my_device", mock_modbus_unit)

        assert device.name == "my_device"

    @staticmethod
    def test_layout_property(mock_modbus_unit: MockModbusUnit) -> None:
        """Test the layout property."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            layout=RegisterLayout.BASE,
        )

        assert device.layout is RegisterLayout.BASE

    @staticmethod
    def test_generation_property(mock_modbus_unit: MockModbusUnit) -> None:
        """Test the generation property."""
        device = GTW26(
            "test",
            mock_modbus_unit,
            generation=ControllerGeneration.GENERATION_4,
        )

        assert device.generation is ControllerGeneration.GENERATION_4
