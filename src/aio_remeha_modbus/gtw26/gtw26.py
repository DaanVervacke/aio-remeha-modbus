"""GTW26 facade, polling engine, and controller write operations."""

import asyncio
import struct
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final

from modbus_connection import (
    ModbusConnectionError,
    ModbusError,
    ModbusUnit,
)
from modbus_connection.model import Component, ComponentGroup, Device, UpdateReport

from aio_remeha_modbus.gtw08.errors import RemehaApiError, RemehaModbusError
from aio_remeha_modbus.gtw26.climate_zone import (
    ClimateZone,
    ClimateZoneA,
    ClimateZoneB,
    ISystemClimateZone,
    ISystemClimateZoneA,
    ISystemClimateZoneB,
    ISystemClimateZoneC,
)
from aio_remeha_modbus.gtw26.config import (
    Config,
    Diagnostics,
    ISystemOutputs,
    ISystemSettings,
    Outputs,
    Service,
    Settings,
)
from aio_remeha_modbus.gtw26.const import (
    BASE_POLICY,
    CLOCK_MARKER,
    GTW26_MAX_SPAN,
    HEATING_MODE_MASK,
    HOT_WATER_MODE_MASK,
    ISYSTEM_POLICY,
    MESSAGE_SPACING,
    PANEL_NUDGE_REGISTER,
    SCHEDULE_BASES,
    ControllerGeneration,
    HeatingMode,
    HotWaterMode,
    RegisterLayout,
)
from aio_remeha_modbus.gtw26.errors import GTW26ProbeError
from aio_remeha_modbus.gtw26.hot_water import HotWater, ISystemHotWater
from aio_remeha_modbus.gtw26.schedule import ScheduleFacade
from aio_remeha_modbus.gtw26.sensors import ISystemSensors, Sensors
from aio_remeha_modbus.gtw26.system_discovery_table import (
    GTW26Detection,
    Identity,
    ISystemIdentity,
    async_detect,
    async_detect_base,
    async_probe,
)
from aio_remeha_modbus.helpers.fields import decode_bytes

_BASE_READ_ONCE = frozenset()
_ISYSTEM_READ_ONCE = frozenset(f"schedules.{name}" for name in SCHEDULE_BASES) | {"config"}

# Bundle-name split per layout, mirroring the GTW08 READINGS/SETTINGS contract:
# readings are the live values, settings the rarely-changing configuration.
# Read-once bundles (config, schedules) belong to the settings semantics and
# are polled through `_pending_once`, not through the settings pool.
_BASE_READINGS: Final = (
    "sensors",
    "hot_water",
    "climate_zone_a",
    "climate_zone_b",
    "outputs",
    "service",
)
_BASE_SETTINGS: Final = ("settings", "identity")
_ISYSTEM_READINGS: Final = (
    "sensors",
    "hot_water",
    "climate_zone_a",
    "climate_zone_b",
    "climate_zone_c",
    "outputs",
    "diagnostics",
)
_ISYSTEM_SETTINGS: Final = ("settings", "identity")

__all__ = ["GTW26", "async_detect", "async_probe"]


class GTW26(Device):
    """Represent a GTW26 gateway over a Modbus unit.

    Note:
        This class does not perform automatic retries on transient errors.
        Callers who want retry behavior should wrap their ModbusUnit with
        RetryingModbusUnit from aio_remeha_modbus.helpers.modbus before
        passing it to the constructor.

    Attributes:
        sensors: Sensor readings component. None until setup complete.
        hot_water: Hot water component. None until setup complete.
        climate_zones: Dict of climate zone components keyed by designation.
        settings: Settings component. None until setup complete.
        config: Configuration component (iSystem only). None until setup complete.
        diagnostics: Diagnostics component (iSystem only). None until setup complete.
        outputs: Outputs component. None until setup complete.
        service: Service component. None until setup complete.
        identity: Identity component. None until setup complete.
        schedule: Schedule component (iSystem only). None until setup complete.
        _pool: ComponentGroup for pooled reads of all regular bundles.
        _readings_pool: ComponentGroup for the live-value bundles.
        _settings_pool: ComponentGroup for the configuration bundles.
        _bundles: Dict of all component bundles by name.
        _read_once: Frozenset of bundle names to read only once.
        _pending_once: Dict of pending one-time read bundles.
        _write_lock: Lock for serializing write operations.
        _setup_complete: Flag indicating setup has completed.
        _setup_lock: Lock for thread-safe setup.

    """

    def __init__(
        self,
        name: str,
        unit: ModbusUnit,
        *,
        layout: RegisterLayout | None = None,
        generation: ControllerGeneration | None = None,
        force_zone_a: bool = False,
        force_zone_b: bool = False,
        force_zone_c: bool = False,
        message_spacing_seconds: float = MESSAGE_SPACING,
        request_timeout: float | None = None,
    ) -> None:
        """Create a GTW26 facade over ``unit``.

        Args:
            name: A label for this facade, exposed through ``name``.
            unit: The Modbus unit to poll registers from.
            layout: Force a register layout instead of auto-detecting one on the
                first update. When omitted, detection picks `RegisterLayout.ISYSTEM`
                when the iSystem identity answers, `RegisterLayout.BASE` otherwise.
            generation: The controller generation to use, as reported by
                `async_detect`. Detected automatically when omitted.
            force_zone_a: Report zone A as present even without a reported sensor.
            force_zone_b: Report zone B as present even without a reported sensor.
            force_zone_c: Report zone C as present even without a reported sensor.
                iSystem-only: rejected with `ValueError` when `layout` is
                `RegisterLayout.BASE`, and inert under auto-detection unless
                the iSystem layout is detected.
            message_spacing_seconds: The pause between Modbus messages that the
                controller requires. Defaults to `MESSAGE_SPACING`.
            request_timeout: Require a request timeout on ``unit`` instead of
                leaving its configured value unchanged.

        """
        if layout is RegisterLayout.BASE and force_zone_c:
            raise ValueError(
                "force_zone_c requires the iSystem layout: zone C does not exist on"
                " RegisterLayout.BASE"
            )
        super().__init__(unit)
        unit.set_message_spacing(message_spacing_seconds)
        if request_timeout is not None:
            unit.require_timeout(request_timeout)

        self._name = name
        self._unit = unit
        self._layout = layout
        self._generation = generation
        self._message_spacing_seconds = message_spacing_seconds
        self._force_zone_a = force_zone_a
        self._force_zone_b = force_zone_b
        self._force_zone_c = force_zone_c

        self.sensors: Sensors | ISystemSensors | None = None
        self.hot_water: HotWater | ISystemHotWater | None = None
        self.climate_zones: dict[str, ClimateZone | ISystemClimateZone] = {}
        self.settings: Settings | ISystemSettings | None = None
        self.config: Config | None = None
        self.diagnostics: Diagnostics | None = None
        self.outputs: Outputs | ISystemOutputs | None = None
        self.service: Service | None = None
        self.identity: Identity | ISystemIdentity | None = None
        self.schedule: ScheduleFacade | None = None

        self._pool: ComponentGroup | None = None
        self._readings_pool: ComponentGroup | None = None
        self._settings_pool: ComponentGroup | None = None
        self._readings_names: frozenset[str] = frozenset()
        self._settings_names: frozenset[str] = frozenset()
        self._bundles: dict[str, Component] = {}
        self._read_once: frozenset[str] = frozenset()
        self._pending_once: dict[str, Component] = {}
        self._write_lock = asyncio.Lock()
        self._setup_complete = False
        self._setup_lock = asyncio.Lock()

    @staticmethod
    async def async_detect(
        unit: ModbusUnit, *, message_spacing_seconds: float = MESSAGE_SPACING
    ) -> GTW26Detection:
        """Detect the type of GTW26 controller.

        A successful detection returns a fully constructed, ready-to-use `GTW26`
        device. Constructing it applies the message spacing the detection was
        given through `unit.set_message_spacing`, so a caller-configured spacing
        survives detection when passed here.
        See `GTW26Detection` for how this differs
        from GTW08's detection.

        Args:
            unit (ModbusUnit): The modbus unit to connect to the device.
            message_spacing_seconds (float): The message spacing the discovered
                device enforces on ``unit``.

        Returns:
            `GTW26Detection` The discovery result.

        Raises:
            `ModbusError` if a transient or unknown modbus error is raised during discovery.

        """
        return await async_detect(unit, message_spacing_seconds=message_spacing_seconds)

    @property
    def name(self) -> str:
        """The facade name."""
        return self._name

    @property
    def layout(self) -> RegisterLayout | None:
        """The detected or configured register layout."""
        return self._layout

    @property
    def generation(self) -> ControllerGeneration | None:
        """The detected or configured controller generation."""
        return self._generation

    async def _async_setup(self) -> None:
        """Detect what is missing and construct the layout's register bundles.

        A known layout is never re-probed. The controller generation is resolved
        from the base identity blocks when the base layout needs it; a missing
        generation is a valid terminal state on the iSystem layout, whose write
        policy never nudges the panel.
        """
        layout = self._layout
        generation = self._generation
        if layout is None:
            detection = await async_detect(
                self._unit, message_spacing_seconds=self._message_spacing_seconds
            )
            if not detection.success:
                raise GTW26ProbeError(detection)
            layout = RegisterLayout.ISYSTEM if detection.isystem_detected else RegisterLayout.BASE
            generation = detection.generation
        elif layout is RegisterLayout.BASE and generation is None:
            detection = await async_detect_base(
                self._unit, message_spacing_seconds=self._message_spacing_seconds
            )
            if not detection.success:
                raise GTW26ProbeError(detection)
            generation = detection.generation
        self._setup_bundles(layout, generation)

    def _setup_bundles(
        self, layout: RegisterLayout, generation: ControllerGeneration | None
    ) -> None:
        """Construct the layout's components, poll pools and read-once state."""
        self._layout = RegisterLayout(layout)
        self._generation = None if generation is None else ControllerGeneration(generation)

        if self._layout is RegisterLayout.BASE:
            self._build_base_components()
            read_once = _BASE_READ_ONCE
            readings, settings = _BASE_READINGS, _BASE_SETTINGS
        else:
            self._build_isystem_components()
            read_once = _ISYSTEM_READ_ONCE
            readings, settings = _ISYSTEM_READINGS, _ISYSTEM_SETTINGS

        regular = [name for name in self._bundles if name not in read_once]
        self._pool = ComponentGroup(self._unit, [self._bundles[name] for name in regular])
        self._readings_names = frozenset(readings)
        self._readings_pool = ComponentGroup(self._unit, [self._bundles[name] for name in readings])
        self._settings_names = frozenset(settings)
        self._settings_pool = ComponentGroup(self._unit, [self._bundles[name] for name in settings])
        self._pending_once = {name: self._bundles[name] for name in read_once}
        self._read_once = read_once
        if self.config is not None:
            self.config._on_written = self._invalidate_read_once  # noqa: SLF001
        if self.schedule is not None:
            for program in self.schedule.bundles().values():
                program._on_day_written = self._invalidate_read_once  # noqa: SLF001
        self._setup_complete = True

    def _build_base_components(self) -> None:
        """Construct the base-layout components and register bundles."""
        self.sensors = Sensors(self._unit)
        self.hot_water = HotWater(self._unit)
        zones = {"A": ClimateZoneA(self._unit), "B": ClimateZoneB(self._unit)}
        for designation, zone in zones.items():
            zone.designation = designation
        self.climate_zones = zones
        self.settings = Settings(self._unit)
        self.outputs = Outputs(self._unit)
        self.service = Service(self._unit)
        self.identity = Identity(self._unit)
        self.schedule = None
        self.config = None
        self.diagnostics = None
        self._bundles = {
            "sensors": self.sensors,
            "hot_water": self.hot_water,
            "climate_zone_a": zones["A"],
            "climate_zone_b": zones["B"],
            "settings": self.settings,
            "outputs": self.outputs,
            "service": self.service,
            "identity": self.identity,
        }

    def _build_isystem_components(self) -> None:
        """Construct the iSystem-layout components and register bundles."""
        self.sensors = ISystemSensors(self._unit)
        self.hot_water = ISystemHotWater(self._unit)
        zones = {
            "A": ISystemClimateZoneA(self._unit),
            "B": ISystemClimateZoneB(self._unit),
            "C": ISystemClimateZoneC(self._unit),
        }
        for designation, zone in zones.items():
            zone.designation = designation
        self.climate_zones = zones
        self.schedule = ScheduleFacade(self._unit)
        self.settings = ISystemSettings(self._unit)
        self.config = Config(self._unit)
        self.outputs = ISystemOutputs(self._unit)
        self.diagnostics = Diagnostics(self._unit)
        self.identity = ISystemIdentity(self._unit)
        self.service = None
        self._bundles = {
            "sensors": self.sensors,
            "hot_water": self.hot_water,
            "climate_zone_a": zones["A"],
            "climate_zone_b": zones["B"],
            "climate_zone_c": zones["C"],
            "settings": self.settings,
            "config": self.config,
            "outputs": self.outputs,
            "diagnostics": self.diagnostics,
            "identity": self.identity,
            **{f"schedules.{name}": program for name, program in self.schedule.bundles().items()},
        }

    async def async_ensure_setup(self) -> None:
        """Build the component set once, retrying after a failed setup."""
        if self._setup_complete:
            return
        async with self._setup_lock:
            if not self._setup_complete:
                await self._async_setup()

    async def _poll_group(
        self,
        group: ComponentGroup | None,
        names: Iterable[str],
        updated: set[str],
        failed: dict[str, ModbusError],
    ) -> None:
        """Poll one bundle pool, falling back to individual reads."""
        if group is None:
            return
        try:
            await group.async_update()
        except ModbusConnectionError:
            raise
        except ModbusError:
            await self._poll_individually(list(names), updated, failed)
        else:
            updated.update(names)

    async def _poll_individually(
        self, names: list[str], updated: set[str], failed: dict[str, ModbusError]
    ) -> None:
        """Poll each regular bundle separately after a pooled-read failure."""
        for name in names:
            try:
                await self._bundles[name].async_update()
            except ModbusConnectionError:
                raise
            except ModbusError as err:
                failed[name] = err
            else:
                updated.add(name)

    async def _poll_read_once(self, updated: set[str], failed: dict[str, ModbusError]) -> None:
        """Poll pending iSystem bundles and latch successful reads."""
        for name, component in list(self._pending_once.items()):
            try:
                await component.async_update()
            except ModbusConnectionError:
                raise
            except ModbusError as err:
                failed[name] = err
            else:
                updated.add(name)
                del self._pending_once[name]

    async def async_update(self) -> UpdateReport:
        """Refresh all regular and pending read-once bundles."""
        await self.async_ensure_setup()
        updated: set[str] = set()
        failed: dict[str, ModbusError] = {}
        await self._poll_group(
            self._pool,
            [name for name in self._bundles if name not in self._read_once],
            updated,
            failed,
        )
        await self._poll_read_once(updated, failed)
        return UpdateReport(updated=updated, failed=failed)

    async def async_update_readings(self) -> UpdateReport:
        """Refresh only the live-value bundles.

        Polls the sensors, hot-water, climate-zone, output and diagnostic (or
        base service) bundles. Settings, identity, config and schedule bundles
        are not read.
        """
        await self.async_ensure_setup()
        updated: set[str] = set()
        failed: dict[str, ModbusError] = {}
        await self._poll_group(self._readings_pool, self._readings_names, updated, failed)
        return UpdateReport(updated=updated, failed=failed)

    async def async_update_settings(self) -> UpdateReport:
        """Refresh only the configuration bundles.

        Polls the settings and identity bundles, plus any pending read-once
        bundles (installer config and schedules on the iSystem layout). Live
        values are not read.
        """
        await self.async_ensure_setup()
        updated: set[str] = set()
        failed: dict[str, ModbusError] = {}
        await self._poll_group(self._settings_pool, self._settings_names, updated, failed)
        await self._poll_read_once(updated, failed)
        return UpdateReport(updated=updated, failed=failed)

    def _invalidate_read_once(self, component: Component) -> None:
        """Re-arm a cached bundle after a successful write."""
        name = next((name for name, item in self._bundles.items() if item is component), None)
        if (name is not None and name.startswith("schedules.")) or name == "config":
            if name is not None:
                self._pending_once[name] = self._bundles[name]

    def _policy(self):
        """Return the write policy for the configured layout."""
        if self._layout is RegisterLayout.BASE:
            return BASE_POLICY
        if self._layout is RegisterLayout.ISYSTEM:
            return ISYSTEM_POLICY
        raise RemehaApiError("layout_not_set_up")

    async def async_set_heating_mode(self, designation: str, mode: HeatingMode) -> None:
        """Set one heating circuit mode while preserving hot-water bits.

        Raises:
            RemehaApiError: if `designation` names no zone of this layout, or
                `mode` is `HeatingMode.HOLIDAY`.

        """
        validated = HeatingMode(mode)
        if validated is HeatingMode.HOLIDAY:
            raise RemehaApiError("heating_mode_read_only")
        await self.async_ensure_setup()
        policy = self._policy()
        if designation not in policy.mode_addresses:
            raise RemehaApiError(
                "unknown_zone_designation",
                translation_placeholders={"designation": designation},
            )
        address = policy.mode_addresses[designation]
        async with self._write_lock:
            (current,) = await self._unit.read_holding_registers(address, 1)
            word = (current & ~HEATING_MODE_MASK) | int(validated)
            await self._unit.write_registers(address, [word])
            self._retain_written_word(address, word)
            if policy.nudges_panel and self._generation is ControllerGeneration.GENERATION_4:
                await self._nudge_panel()

    async def async_set_hot_water_mode(self, mode: HotWaterMode) -> None:
        """Set hot-water mode while preserving heating-circuit bits."""
        validated = HotWaterMode(mode)
        await self.async_ensure_setup()
        policy = self._policy()
        async with self._write_lock:
            currents = [
                (address, (await self._unit.read_holding_registers(address, 1))[0])
                for address in policy.hot_water_addresses
            ]
            for address, current in currents:
                word = (current & ~HOT_WATER_MODE_MASK) | int(validated)
                await self._unit.write_registers(address, [word])
                self._retain_written_word(address, word)
            if policy.nudges_panel and self._generation is ControllerGeneration.GENERATION_4:
                await self._nudge_panel()

    async def async_set_clock(self, moment: datetime) -> None:
        """Set the controller clock using the selected layout's clock policy."""
        await self.async_ensure_setup()
        policy = self._policy().clock
        async with self._write_lock:
            if policy.uses_marker:
                assert policy.date_address is not None
                time_block = [
                    CLOCK_MARKER | (moment.hour & 0xFF),
                    CLOCK_MARKER | (moment.minute & 0xFF),
                    CLOCK_MARKER | (moment.isoweekday() & 0xFF),
                ]
                date_block = [
                    CLOCK_MARKER | (moment.day & 0xFF),
                    CLOCK_MARKER | (moment.month & 0xFF),
                    CLOCK_MARKER | (moment.year % 100 & 0xFF),
                ]
                await self._unit.write_registers(policy.time_address, time_block)
                await self._unit.write_registers(policy.date_address, date_block)
            else:
                block = [
                    moment.hour,
                    moment.minute,
                    moment.isoweekday(),
                    moment.day,
                    moment.month,
                    moment.year % 100,
                ]
                await self._unit.write_registers(policy.time_address, block)
            self._retain_written_word(policy.time_address, moment.hour)
            self._retain_written_word(policy.time_address + 1, moment.minute)
            self._retain_written_word(policy.time_address + 2, moment.isoweekday())
            date_address = (
                policy.date_address if policy.date_address is not None else policy.time_address + 3
            )
            self._retain_written_word(date_address, moment.day)
            self._retain_written_word(date_address + 1, moment.month)
            self._retain_written_word(date_address + 2, moment.year % 100)

    def _retain_written_word(self, address: int, word: int) -> None:
        """Cache a written word in every component field that reads its address."""
        for component in self._bundles.values():
            for name, resolved in component.resolved_fields.items():
                if (
                    resolved.address == address
                    and resolved.space == "holding"
                    and resolved.count == 1
                ):
                    component._values[name] = resolved.field.decode([word])  # noqa: SLF001

    async def _nudge_panel(self) -> None:
        """Toggle the generation-4 panel refresh register after a mode write."""
        await self._unit.write_registers(PANEL_NUDGE_REGISTER, [1])
        await asyncio.sleep(0.5)
        await self._unit.write_registers(PANEL_NUDGE_REGISTER, [0])

    async def async_read_registers(
        self, address: int, *, count: int = 1, struct_format: str = ">H"
    ) -> tuple[Any, ...]:
        """Read and unpack raw holding registers for diagnostics.

        The default ``struct_format`` matches the big-endian register words
        `decode_bytes` emits, so a single-register read decodes correctly on
        every host byte order.
        """
        if count < 1 or count > GTW26_MAX_SPAN:
            raise ValueError(f"Illegal count {count}: must be between 1 and {GTW26_MAX_SPAN}.")
        registers = await self._unit.read_holding_registers(address, count)
        return struct.unpack(struct_format, decode_bytes(registers))

    async def async_read_all_raw(self) -> dict[str, dict[int, int | bool]]:
        """Read all mapped bundles, including read-once bundles, without notifying."""
        await self.async_ensure_setup()
        assert self._bundles
        group = ComponentGroup(self._unit, list(self._bundles.values()))
        return await group.async_read_raw(notify=False)

    @staticmethod
    async def async_health_check(unit: ModbusUnit) -> None:
        """Verify if the system is reachable by reading a single register.

        Raises:
            RemehaModbusError: If the health check failed.

        """
        try:
            await unit.read_holding_registers(457, 1)
        except ModbusError as err:
            raise RemehaModbusError("health_check_failed") from err

    @property
    def zone_a_present(self) -> bool:
        """Whether zone A has a reported sensor or is forced present."""
        zone = self.climate_zones.get("A")
        if zone is None:
            return self._force_zone_a
        return bool(
            self._force_zone_a
            or zone.room_temperature is not None
            or zone.calculated_temperature is not None
            or (
                self._layout is RegisterLayout.ISYSTEM
                and getattr(zone, "supply_temperature", None) is not None
            )
        )

    @property
    def zone_b_present(self) -> bool:
        """Whether zone B has a reported sensor or is forced present."""
        zone = self.climate_zones.get("B")
        if zone is None:
            return self._force_zone_b
        return bool(
            self._force_zone_b
            or zone.room_temperature is not None
            or zone.calculated_temperature is not None
            or getattr(zone, "supply_temperature", None) is not None
            or getattr(zone, "min_temperature", None) is not None
            or getattr(zone, "max_temperature", None) is not None
        )

    @property
    def zone_c_present(self) -> bool:
        """Whether iSystem zone C has a reported sensor or is forced present."""
        if self._layout is not RegisterLayout.ISYSTEM:
            return False
        zone = self.climate_zones.get("C")
        if zone is None:
            return False
        return bool(
            self._force_zone_c
            or zone.room_temperature is not None
            or zone.calculated_temperature is not None
        )

    @property
    def hot_water_present(self) -> bool:
        """Whether hot water has a reported temperature sensor."""
        if self.hot_water is None:
            return False
        return bool(
            self.hot_water.temperature is not None
            or (
                self._layout is RegisterLayout.BASE
                and getattr(self.hot_water, "temperature_dpsm", None) is not None
            )
        )
