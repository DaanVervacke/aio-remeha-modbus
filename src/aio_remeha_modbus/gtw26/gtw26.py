"""GTW26 facade, polling engine, and controller write operations."""

import asyncio
import struct
from datetime import datetime
from typing import Any

from modbus_connection import (
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
    ModbusUnit,
    ServerDeviceBusyError,
)
from modbus_connection.model import Component, ComponentGroup, Device, UpdateReport

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
from aio_remeha_modbus.gtw26.errors import Gtw26ProbeError
from aio_remeha_modbus.gtw26.hot_water import HotWater, ISystemHotWater
from aio_remeha_modbus.gtw26.schedule import ScheduleFacade
from aio_remeha_modbus.gtw26.sensors import ISystemSensors, Sensors
from aio_remeha_modbus.gtw26.system_discovery_table import (
    Identity,
    ISystemIdentity,
    async_detect,
    async_probe,
)
from aio_remeha_modbus.helpers.fields import decode_bytes

_BASE_READ_ONCE = frozenset()
_ISYSTEM_READ_ONCE = frozenset(f"schedules.{name}" for name in SCHEDULE_BASES) | {"config"}

__all__ = ["GTW26", "async_detect", "async_probe"]


class GTW26(Device):
    """Represent a GTW26 gateway over a Modbus unit."""

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
        """Create a GTW26 facade over ``unit``."""
        super().__init__(unit)
        unit.set_message_spacing(message_spacing_seconds)
        if request_timeout is not None:
            unit.require_timeout(request_timeout)

        self._name = name
        self._unit = unit
        self._layout = layout
        self._generation = generation
        self._force_zone_a = force_zone_a
        self._force_zone_b = force_zone_b
        self._force_zone_c = force_zone_c

        self.sensors: Sensors | ISystemSensors | None = None
        self.hot_water: HotWater | ISystemHotWater | None = None
        self.climate_zones: dict[str, ClimateZone | ISystemClimateZone] | None = None
        self.settings: Settings | ISystemSettings | None = None
        self.config: Config | None = None
        self.diagnostics: Diagnostics | None = None
        self.outputs: Outputs | ISystemOutputs | None = None
        self.service: Service | None = None
        self.identity: Identity | ISystemIdentity | None = None
        self.schedule: ScheduleFacade | None = None

        self._pool: ComponentGroup | None = None
        self._bundles: dict[str, Component] = {}
        self._read_once: frozenset[str] = frozenset()
        self._pending_once: dict[str, Component] = {}
        self._write_lock = asyncio.Lock()
        self._setup_complete = False
        self._setup_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        """Return the facade name."""
        return self._name

    @property
    def layout(self) -> RegisterLayout | None:
        """Return the detected or configured register layout."""
        return self._layout

    @property
    def generation(self) -> ControllerGeneration | None:
        """Return the detected or configured controller generation."""
        return self._generation

    async def _async_setup(self) -> None:
        """Detect the layout when needed and construct its register bundles."""
        layout = self._layout
        generation = self._generation
        if layout is None or generation is None:
            detection = await async_detect(self._unit)
            if layout is None:
                layout = (
                    RegisterLayout.ISYSTEM if detection.isystem_detected else RegisterLayout.BASE
                )
            if generation is None:
                generation = detection.generation

        self._layout = RegisterLayout(layout)
        self._generation = None if generation is None else ControllerGeneration(generation)

        if self._layout is RegisterLayout.BASE:
            self._build_base_components()
            read_once = _BASE_READ_ONCE
        else:
            self._build_isystem_components()
            read_once = _ISYSTEM_READ_ONCE

        self._pool = ComponentGroup(
            self._unit,
            [component for name, component in self._bundles.items() if name not in read_once],
        )
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

    async def _poll_bundles(self, updated: set[str], failed: dict[str, ModbusError]) -> None:
        """Poll regular bundles as a pool, falling back to individual reads."""
        if self._pool is None:
            return
        regular = [name for name in self._bundles if name not in self._read_once]
        for _ in range(2):
            try:
                await self._pool.async_update()
            except ModbusConnectionError:
                raise
            except ModbusTimeoutError, ServerDeviceBusyError:
                continue
            except ModbusError:
                await self._poll_individually(regular, updated, failed)
                return
            else:
                updated.update(regular)
                return
        await self._poll_individually(regular, updated, failed)

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
        await self._poll_bundles(updated, failed)
        await self._poll_read_once(updated, failed)
        return UpdateReport(updated=updated, failed=failed)

    async def async_update_readings(self) -> UpdateReport:
        """Refresh GTW26 readings using the unified polling engine."""
        return await self.async_update()

    async def async_update_settings(self) -> UpdateReport:
        """Refresh GTW26 settings using the unified polling engine."""
        return await self.async_update()

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
        raise RuntimeError("GTW26 layout has not been set up")

    async def set_heating_mode(self, designation: str, mode: HeatingMode) -> None:
        """Set one heating circuit mode while preserving hot-water bits."""
        validated = HeatingMode(mode)
        if validated is HeatingMode.HOLIDAY:
            raise ValueError("Holiday mode is read-only. Set it on the control panel.")
        await self.async_ensure_setup()
        policy = self._policy()
        address = policy.mode_addresses[designation]
        async with self._write_lock:
            (current,) = await self._unit.read_holding_registers(address, 1)
            await self._unit.write_registers(
                address, [(current & ~HEATING_MODE_MASK) | int(validated)]
            )
            if policy.nudges_panel and self._generation is ControllerGeneration.GENERATION_4:
                await self._nudge_panel()

    async def set_hot_water_mode(self, mode: HotWaterMode) -> None:
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
                await self._unit.write_registers(
                    address, [(current & ~HOT_WATER_MODE_MASK) | int(validated)]
                )
            if policy.nudges_panel and self._generation is ControllerGeneration.GENERATION_4:
                await self._nudge_panel()

    async def set_clock(self, moment: datetime) -> None:
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

    async def _nudge_panel(self) -> None:
        """Toggle the generation-4 panel refresh register after a mode write."""
        await self._unit.write_registers(PANEL_NUDGE_REGISTER, [1])
        await asyncio.sleep(0.5)
        await self._unit.write_registers(PANEL_NUDGE_REGISTER, [0])

    async def async_read_registers(
        self, address: int, *, count: int = 1, struct_format: str = "=H"
    ) -> tuple[Any, ...]:
        """Read and unpack raw holding registers for diagnostics."""
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
    async def async_health_check(unit: ModbusUnit) -> bool:
        """Return whether the unit can be identified as a GTW26 controller."""
        try:
            await async_detect(unit)
        except Gtw26ProbeError:
            return False
        return True

    @property
    def zone_a_present(self) -> bool:
        """Return whether zone A has a reported sensor or is forced present."""
        if self.climate_zones is None:
            return self._force_zone_a
        zone = self.climate_zones["A"]
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
        """Return whether zone B has a reported sensor or is forced present."""
        if self.climate_zones is None:
            return self._force_zone_b
        zone = self.climate_zones["B"]
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
        """Return whether iSystem zone C has a reported sensor or is forced present."""
        if self._layout is not RegisterLayout.ISYSTEM or self.climate_zones is None:
            return False
        zone = self.climate_zones["C"]
        return bool(
            self._force_zone_c
            or zone.room_temperature is not None
            or zone.calculated_temperature is not None
        )

    @property
    def hot_water_present(self) -> bool:
        """Return whether hot water has a reported temperature sensor."""
        if self.hot_water is None:
            return False
        return bool(
            self.hot_water.temperature is not None
            or (
                self._layout is RegisterLayout.BASE
                and getattr(self.hot_water, "temperature_dpsm", None) is not None
            )
        )
