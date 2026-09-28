"""Modbus components related to climate zone time programs."""

from datetime import time
from enum import IntEnum
from typing import Self, override

from modbus_connection import WordOrder
from modbus_connection.model import RegisterField, WriteValidator, repeating_group
from pydantic.dataclasses import dataclass

from aio_remeha_modbus.gtw08.const import (
    REMEHA_DAY_SCHEDULE_RESERVED_REGISTERS,
    REMEHA_MAX_SPAN,
    REMEHA_TIME_PROGRAM_BYTE_SIZE,
    REMEHA_TIME_PROGRAM_SLOT_SIZE,
    Weekday,
)
from aio_remeha_modbus.gtw08.errors import InvalidZoneSchedule
from aio_remeha_modbus.gtw08.model import RemehaComponent
from aio_remeha_modbus.helpers.fields import decode_bytes, encode_bytes
from aio_remeha_modbus.helpers.gtw08 import SteppedTimeOfDay


class TimeslotActivity(IntEnum):
    """The type of activity that must run during the containing TimeSlot."""

    HEAT_COOL = int("c8", 16)
    DHW = int("00", 16)


class TimeslotSetpointType(IntEnum):
    """The setpoint that must be reached during the containing TimeSlot.

    The names used here are the default names as shown in the Remeha Home app. In the app, these names
    can be changed.
    """

    ECO = 0
    """Reduced setpoint. For `TimeslotActivity.HEAT_COOL` this is named 'Sleeping' in the Remeha Home app. """

    COMFORT = int("10", 16)
    """Comfort setpoint. For `TimeslotActivity.HEAT_COOL` this is named 'At home' in the Remeha Home app."""

    AWAY = int("20", 16)
    """Setpoint in 'away' mode."""

    MORNING = int("30", 16)
    """Setpoint in 'morning' mode."""

    EVENING = int("40", 16)
    """Setpoint in 'evening' mode."""


@dataclass(frozen=True)
class Timeslot:
    """A zone schedule time slot."""

    setpoint_type: TimeslotSetpointType
    """The type of setpoint for this time slot."""

    activity: TimeslotActivity
    """The type of activity for this time slot."""

    switch_time: time
    """The start time of this time slot."""

    def encode(self) -> bytes:
        """Encode this time slot into a `bytes` object."""

        time_steps: int = SteppedTimeOfDay.to_steps(self.switch_time)

        return (
            int(self.activity.value).to_bytes()
            + int(self.setpoint_type.value).to_bytes()
            + time_steps.to_bytes()
        )

    def __lt__(self, other) -> bool:
        """Compare this `Timeslot` to another."""
        if isinstance(other, Timeslot):
            return self.switch_time < other.switch_time

        return False

    def __str__(self):
        """Return a human-readable representation of this time slot."""
        return f"Timeslot(setpoint_type={self.setpoint_type.name}, activity={self.activity.name}, switch_time={self.switch_time})"

    @classmethod
    def create_default(cls, is_dhw: bool) -> Self:
        """Create a default `Timeslot`.

        A default time slot is used to repair an issue where the zone schedule cannot
        be parsed although it has been selected.
        This can mean that there are missing options in our implementation or that
        the data has been corrupted in transit or on the GTW-08.

        Args:
            is_dhw (bool): Whether this schedule is for a DHW zone.

        Returns:
            The time slot.

        """

        return cls(
            setpoint_type=TimeslotSetpointType.ECO,
            activity=(TimeslotActivity.DHW if is_dhw else TimeslotActivity.HEAT_COOL),
            switch_time=time(hour=0),
        )

    @classmethod
    def decode(cls, encoded_time_slot: bytes) -> Self:
        """Decode a `bytes` object intoa a `Timeslot`.

        Args:
            encoded_time_slot (bytes): The encoded time slot. Must be 3 bytes.

        Raises:
            `ValueError`: If `encoded_time_slot` is not exactly 3 bytes.

        """
        # slot_bytes must be exactly 3 bytes.
        if len(encoded_time_slot) != REMEHA_TIME_PROGRAM_SLOT_SIZE:
            raise ValueError(
                f"Cannot decode time program: require time slot of {REMEHA_TIME_PROGRAM_SLOT_SIZE} bytes but got {len(encoded_time_slot)}."
            )

        time_steps = int.from_bytes(encoded_time_slot[2:3])
        setpoint_type = TimeslotSetpointType(int.from_bytes(encoded_time_slot[1:2]))
        activity = TimeslotActivity(int.from_bytes(encoded_time_slot[:1]))

        return cls(
            activity=activity,
            setpoint_type=setpoint_type,
            switch_time=SteppedTimeOfDay.from_steps(time_steps),
        )


class TimeProgramField(RegisterField[list[Timeslot]]):
    """A field that encodes a time program for a single day."""

    max_element_count = int(REMEHA_TIME_PROGRAM_BYTE_SIZE / REMEHA_TIME_PROGRAM_SLOT_SIZE)
    """The maximum amount of `Timeslot` instances in a given or returned `list[Timeslot]`"""

    nan_bytes = b"\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\xff\x00"

    def __init__(
        self,
        address: int,
        *,
        word_order: WordOrder = "big",
        writable: bool | WriteValidator = False,
        stride: int = 0,
        force_fc16: bool = False,
    ) -> None:
        """Create a new TimeProgramField."""

        super().__init__(address, count=10, writable=writable, stride=stride, force_fc16=force_fc16)
        self.word_order: WordOrder = word_order

    @override
    def decode(self, words: list[int], scale_exponent: int | None = None) -> list[Timeslot] | None:
        schedule_bytes = decode_bytes(words=words, word_order=self.word_order)

        if len(schedule_bytes) != REMEHA_TIME_PROGRAM_BYTE_SIZE:
            raise ValueError(
                f"Cannot decode time program: require {REMEHA_TIME_PROGRAM_BYTE_SIZE} bytes but got {len(schedule_bytes)}."
            )

        if schedule_bytes == TimeProgramField.nan_bytes:
            return None

        no_of_slots: int = int.from_bytes(schedule_bytes[0:1])

        def _decode_timeslots():
            for slot_index in range(
                1, no_of_slots * REMEHA_TIME_PROGRAM_SLOT_SIZE, REMEHA_TIME_PROGRAM_SLOT_SIZE
            ):
                slot_bytes: bytes = schedule_bytes[
                    slot_index : slot_index + REMEHA_TIME_PROGRAM_SLOT_SIZE
                ]

                yield Timeslot.decode(encoded_time_slot=slot_bytes)

        try:
            return [time_slot for time_slot in list(_decode_timeslots()) if time_slot is not None]
        except ValueError as ex:
            raise InvalidZoneSchedule(translation_key="invalid_time_program") from ex

    @override
    def encode(self, value: list[Timeslot], scale_exponent: int | None = None) -> list[int]:
        if len(value) > TimeProgramField.max_element_count:
            raise ValueError(
                f"Too many Timeslots to encode. Maximum is {TimeProgramField.max_element_count}, got {len(value)}"
            )

        time_slot_count: bytes = len(value).to_bytes()
        not_padded_slots: bytes = b"".join([
            time_slot_count,
            *[t.encode() for t in value],
        ])

        # Add padding null-bytes until length is REMEHA_TIME_PROGRAM_BYTE_SIZE bytes.
        schedule_bytes = b"".join([
            not_padded_slots,
            *[b"\00" for _ in range(REMEHA_TIME_PROGRAM_BYTE_SIZE - len(not_padded_slots))],
        ])

        return encode_bytes(schedule_bytes, word_order=self.word_order)


def time_slots(
    address: int, *, writable: bool | WriteValidator = False, stride: int = 0
) -> TimeProgramField:
    """Create a field that represents a time program."""

    return TimeProgramField(address=address, writable=writable, stride=stride)


class DaySchedule(RemehaComponent):
    """A component representing the slots in a time program for a single day."""

    max_span = REMEHA_MAX_SPAN

    slots = time_slots(address=689, writable=True, stride=0)
    """The time slots for the related day."""

    async def async_set_time_slots(self, time_slots: list[Timeslot]) -> None:
        """Write the given time slots."""

        await self.write("slots", time_slots)


class TimeProgram(RemehaComponent):
    """Implementation of the Remeha Modbus scheduling format.

    The GTW-08 parameter list shows that a user can choose from 3 distinct heating schedules
    for a given zone. For cooling, one schedule can be used. All schedules are divided in 7 day schedules,
    one for each weekday.

    ### Time program encoding
    A time program is encoded in a binary string, and is 20 bytes (10 registers) in size.
    It is encoded as follows:

    | Byte index  |          Contents           | Data type |
    |:-----------:|:----------------------------|:----------|
    |    `0`      | Number of switches (max 6)  | `UINT8`   |
    |    `1`      | Temperature 1               | `UINT16`  |
    |    `3`      | Switch time 1               | `UINT8`   |
    |    `4`      | Temperature 2               | `UINT16`  |
    |    `6`      | Switch time 2               | `UINT8`   |
    |    ...      |            ...              |   ...     |
    |   `16`      | Temperature 6               | `UINT16`  |
    |   `18`      | Switch time 6               | `UINT8`   |

    #### Temperature encoding
    The switch temperature is encoded into activities (heat/cool, dhw, dhw primary).
    The setpoints of these activities are defined elsewhere. The activities are defined as follows:

    | Name      | MSB     | LSB                     |
    |:----------|:-------:|------------------------:|
    | At home   | `0x10`  |    `0xc8` (heat/cool)   |
    | Morning   | `0x30`  |    `0xc8` (heat/cool)   |
    | Away      | `0x20`  |    `0xc8` (heat/cool)   |
    | Evening   | `0x40`  |    `0xc8` (heat/cool)   |
    | Sleeping  | `0x00`  |    `0xc8` (heat/cool)   |
    | Eco       | `0x00`  |    `0x00` (DHW primary) |
    | Comfort   | `0x10`  |    `0x00` (DHW primary) |


    #### Switch time encoding
    The switch time is encoded as a number, indicating the amount of 10-minute
    steps from 00:00 local time. This means that a value of 10 stands for 01:40AM.
    """

    max_span = REMEHA_MAX_SPAN

    day_schedules = repeating_group(
        len(Weekday), DaySchedule, stride=REMEHA_DAY_SCHEDULE_RESERVED_REGISTERS
    )
