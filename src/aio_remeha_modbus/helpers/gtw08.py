"""GTW-08 helper functions."""

from datetime import datetime, time, timedelta, tzinfo
from typing import TYPE_CHECKING, Final, overload

from dateutil import relativedelta

from aio_remeha_modbus.gtw08.const import REMEHA_TIME_STEP_MINUTES, Weekday

if TYPE_CHECKING:
    from aio_remeha_modbus.gtw08.time_program import Timeslot


class SteppedTimeOfDay:
    """Encoding to and from 'stepped' time.

    This concerns time encoded using the amount of ten-minute
    steps since midnight.
    """

    @overload
    @classmethod
    def from_steps(cls, steps: int, step_minutes: int = REMEHA_TIME_STEP_MINUTES) -> time: ...

    @overload
    @classmethod
    def from_steps(
        cls, steps: int | None, step_minutes: int = REMEHA_TIME_STEP_MINUTES
    ) -> time | None: ...

    @classmethod
    def from_steps(
        cls, steps: int | None, step_minutes: int = REMEHA_TIME_STEP_MINUTES
    ) -> time | None:
        """Decode time steps to a time of day.

        Args:
          steps (int): The amount of time steps since midnight.
          step_minutes (int): The step size in minutes. Defaults to `REMEHA_TIME_STEP_MINUTES`.

        """

        if steps is None:
            return None

        delta = relativedelta.relativedelta(minutes=steps * step_minutes)
        return time(delta.hours, delta.minutes, 0)

    @classmethod
    def to_steps(cls, time_of_day: time, step_minutes: int = REMEHA_TIME_STEP_MINUTES) -> int:
        """Encode a time of day to time steps since midnight.

        Args:
          time_of_day (time): The time of day to encode.
          step_minutes (int): The step size in minutes. Defaults to `REMEHA_TIME_STEP_MINUTES`.

        Returns:
          The amount of time steps since midnight.
          Non-integer steps are ignored, meaning 1.9 steps will count as 1.

        """

        minutes = time_of_day.hour * 60 + time_of_day.minute
        return int(minutes / step_minutes)


class TimeOfDay:
    """Encoding to and decoding from a CiA 301 TIME_OF_DAY struct."""

    _CIA301_TOD_BASE_DATE: Final[datetime] = datetime(year=1984, month=1, day=1, hour=0, minute=0)

    @classmethod
    def from_bytes(cls, data: bytes, time_zone: tzinfo | None = None) -> datetime:
        """Decode a CiA 301 TIME_OF_DAY to a `datetime` object.

        `TIME_OF_DAY` is a struct that is defined as follows:

        ===============  ==============  ===========
        Field            Type            Size (bits)
        ===============  ==============  ===========
        ``ms``           unsigned int    28
        ``<padding>``    N/A             4
        ``days``         unsigned int    16
        ===============  ==============  ===========

        * `TIME_OF_DAY.ms` is the amount of milliseconds since midnight
        * `TIME_OF_DAY.days` is the amount of days since 1984-01-01.

        **Notes**:
          * This method assumes that naive `datetime` instances are in `time_zone`.
          * This method assumes that the Remeha appliance operates in time zone `time_zone`.

        Args:
          data (bytes): The encoded TIME_OF_DAY struct.
          time_zone (str): The name of the Home Assistant time zone, defaults to the local time zone of the running OS.

        Returns:
          datetime: The decoded `TIME_OF_DAY` struct.

        Raises:
          `ValueError` if `time_zone` is an invalid time zone string or if `len(data) != 6`.

        """

        if len(data) != 6:
            raise ValueError(
                f"Cannot decode data into datetime: data must be exactly 6 bytes, but got {len(data)}"
            )

        ms = int.from_bytes(
            data[2:4] + data[0:2],
        ) & int("0fffffff", 16)
        days = int.from_bytes(
            data[4:],
        )

        return cls._CIA301_TOD_BASE_DATE.replace(tzinfo=time_zone) + timedelta(
            days=days, milliseconds=ms
        )

    @classmethod
    def to_bytes(cls, dt: datetime) -> bytes:
        """Encode a `datetime` object to a CiA 301 TIME_OF_DAY.

        Args:
          dt (datetime): The datetime to encode into a `TIME_OF_DAY` struct.

        Returns:
          The timestamp, encoded in a `TIME_OF_DAY` struct.

        """
        delta: timedelta = dt - cls._CIA301_TOD_BASE_DATE.replace(tzinfo=dt.tzinfo)

        ms = int(delta.seconds * 1000 + delta.microseconds / 1000) & int("0fffffff", 16)
        days = delta.days

        ms_bytes: bytes = ms.to_bytes(4)
        return ms_bytes[2:4] + ms_bytes[0:2] + days.to_bytes(2)


def get_current_timeslot(
    schedule: dict[Weekday, list[Timeslot] | None],
    time_zone: tzinfo | None,
) -> Timeslot | None:
    """Retrieve the current schedule time slot.

    Args:
        schedule (list[DaySchedule]): The selected schedule
        time_zone (datetime.tzinfo): The appliance time zone

    Returns:
        The current schedule time slot, or `None` if `schedule` is `None`.

    """

    if schedule is None:
        return None

    now: datetime = datetime.now(time_zone)
    weekday = now.weekday()
    time_slots: list[Timeslot] | None = schedule.get(Weekday(weekday))

    return (
        next(
            reversed([
                time_slot for time_slot in time_slots if time_slot.switch_time.hour <= now.hour
            ]),
            None,
        )
        if time_slots is not None
        else None
    )
