"""System Discovery Table implementation."""

from enum import IntEnum
from functools import cached_property

from modbus_connection.model import repeating_group, uint32
from pydantic.dataclasses import dataclass

from aio_remeha_modbus.gtw08.const import REMEHA_DEVICE_BOARD_RESERVED_REGISTERS, REMEHA_MAX_SPAN
from aio_remeha_modbus.gtw08.model import RemehaComponent
from aio_remeha_modbus.helpers.fields import BytePosition, uint8, uint16


class DeviceBoardType(IntEnum):
    """Defines the type of device located on the device instance."""

    CU_GH = 0
    """Motherboard for central heating boilers like Tzerra Ace"""

    CU_OH = 1
    """Motherboard for condensing oil boilers like Calora Tower Oil LS"""

    EHC = 2
    """Motherboard for (hybrid) heat pumps like Mercuria Ace"""

    MK = int("14", 16)
    """Appliance control panel like eTwist"""

    SCB = int("19", 16)
    """Circuit control board"""

    EEC = int("1b", 16)
    """Motherboard for gas boilers like GAS 120 Ace"""

    EHC_ALT = int("21", 16)
    """Unknown/alternate heatpump mainboard (seen on Confida)"""

    GATEWAY = int("1e", 16)
    """A gateway, for example GTW-08 (modbus gateway)"""

    def is_mainboard(self) -> bool:
        """Return whether this value represents a mainboard, a.k.a. the main device."""

        return self in {
            DeviceBoardType.CU_GH,
            DeviceBoardType.CU_OH,
            DeviceBoardType.EHC,
            DeviceBoardType.EHC_ALT,
            DeviceBoardType.EEC,
        }


@dataclass(eq=False)
class DeviceBoardCategory:
    """The category of the device located on the appliance."""

    type: DeviceBoardType
    """The device type"""

    generation: int
    """The category generation"""

    def __str__(self):
        """Textual representation of this DeviceBoardCategory."""

        name: str
        match self.type:
            case DeviceBoardType.CU_GH:
                name = "CU-GH"
            case DeviceBoardType.CU_OH:
                name = "CU-OH"
            case DeviceBoardType.GATEWAY:
                name = "GTW"
            case _:
                name = self.type.name

        return f"{name}-{self.generation}"

    def __eq__(self, other: object) -> bool:
        """Compare this `DeviceBoardCategory` to another for equality.

        Only ``type`` is used to determine equality, since the generation might change.

        Returns:
            `bool`: `True` if the objects are considered equal, `False` otherwise.

        """

        if isinstance(other, self.__class__):
            return self.type == other.type

        return False

    def __hash__(self):
        """Return a hash of this device board category."""

        return hash(self.type)


class DeviceBoard(RemehaComponent):
    """A device board on the appliance."""

    max_span = REMEHA_MAX_SPAN

    _type = uint8(address=129, position=BytePosition.HIGH)
    _generation = uint8(address=129)
    _sw_version = uint16(address=130)
    _ct_version = uint16(address=131)
    _hw_version = uint16(address=132)

    @cached_property
    def id(self) -> int:
        """The board sequence id."""

        resolved = self.resolved_fields["_type"]
        address = resolved.address - 129  # normalize address

        return int(address / REMEHA_DEVICE_BOARD_RESERVED_REGISTERS)

    @cached_property
    def board_category(self) -> DeviceBoardCategory | None:
        """The board category of this device."""

        t = self._type
        g = self._generation

        if t is not None and g is not None:
            return DeviceBoardCategory(type=DeviceBoardType(t), generation=g)

        return None

    @property
    def software_version(self) -> tuple[int, int] | None:
        """The software version of the device."""

        if self._sw_version is None:
            return None

        b = self._sw_version.to_bytes(2)
        return (b[0], b[1])

    @property
    def config_table_version(self) -> tuple[int, int] | None:
        """The configuration table version of the device."""

        if self._ct_version is None:
            return None

        b = self._ct_version.to_bytes(2)
        return (b[0], b[1])

    @property
    def hardware_version(self) -> tuple[int, int] | None:
        """The hardware version of the device."""

        if self._hw_version is None:
            return None

        b = self._hw_version.to_bytes(2)
        return (b[0], b[1])

    article_number = uint32(address=133)
    """The article number of the device."""

    def is_mainboard(self) -> bool:
        """Return whether this device is a mainboard."""

        return False if self.board_category is None else self.board_category.type.is_mainboard()

    def __eq__(self, other: object) -> bool:
        """Compare this `DeviceInstance` with another for equality.

        Only `board_category` is considered, to allow HA to update
        the device info after it gets a software upgrade for example.

        Returns:
            `bool`: `True` if the objects are considered equal, `False` otherwise.

        """
        if isinstance(other, self.__class__):
            return self.board_category == other.board_category

        return False

    def __hash__(self):
        """Return a hash of this device instance."""
        return hash(self.board_category)


class SystemDiscoveryTable(RemehaComponent):
    """The table of discovered device boards."""

    max_span = REMEHA_MAX_SPAN
    register_ranges = ((128, 198), (200, 200))

    _reset = uint8(address=200, writable=True)

    device_boards = repeating_group(
        uint8(address=128),  # number of device boards
        component_class=DeviceBoard,
        stride=REMEHA_DEVICE_BOARD_RESERVED_REGISTERS,
    )
    """The list of device boards available on the appliance."""

    number_of_zones = uint8(address=189)
    """The number of zones present on the appliance."""

    async def reset(self):
        """Reset the discovery table.

        This causes rediscovery of the appliance device boards, but does not change the
        current appliance configuration.
        """

        await self.write("_reset", 0x5A)
