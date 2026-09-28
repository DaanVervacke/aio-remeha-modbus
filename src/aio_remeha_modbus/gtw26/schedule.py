"""GTW26 weekly comfort schedules."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import time
from itertools import starmap
from typing import Any, ClassVar, Self, override

from modbus_connection import ModbusUnit
from modbus_connection.model import RegisterField

from aio_remeha_modbus.gtw26.const import (
    DAY_STRIDE,
    DAYS,
    SCHEDULE_BASES,
    WEEKDAY_FIELDS,
    Weekday,
)
from aio_remeha_modbus.gtw26.model import Gtw26Component
from aio_remeha_modbus.helpers.gtw26 import (
    DaySchedule,
    decode_day,
    encode_day,
)


@dataclass(frozen=True)
class ComfortPeriod:
    """One comfort period on a single day.

    `end` may be `time(0, 0)`, meaning midnight at the end of the day (24:00).
    """

    start: time
    end: time


class ScheduleDayField(RegisterField[DaySchedule]):
    """One day of a comfort schedule over three half-hour bitmap registers."""

    @override
    def decode(self, words: list[int], scale_exponent: int | None = None) -> DaySchedule:
        """Decode three registers into comfort periods."""
        return decode_day(words)

    @override
    def encode(self, value: Any, scale_exponent: int | None = None) -> list[int]:
        """Encode comfort periods into three registers."""
        return encode_day(value)


def schedule_day(address: int, *, writable: bool = False) -> ScheduleDayField:
    """Create a schedule-day field spanning three registers."""
    return ScheduleDayField(
        address,
        count=DAY_STRIDE,
        writable=writable,
        force_fc16=writable,
    )


class WeekProgram(Gtw26Component):
    """One weekly comfort program represented by seven writable day fields."""

    register_ranges = tuple(
        (day * DAY_STRIDE, day * DAY_STRIDE + DAY_STRIDE - 1) for day in range(DAYS)
    )
    _on_day_written: Callable[[Self], None] | None = None

    monday = schedule_day(0, writable=True)
    tuesday = schedule_day(DAY_STRIDE, writable=True)
    wednesday = schedule_day(2 * DAY_STRIDE, writable=True)
    thursday = schedule_day(3 * DAY_STRIDE, writable=True)
    friday = schedule_day(4 * DAY_STRIDE, writable=True)
    saturday = schedule_day(5 * DAY_STRIDE, writable=True)
    sunday = schedule_day(6 * DAY_STRIDE, writable=True)

    @property
    def week(self) -> dict[Weekday, list[ComfortPeriod]]:
        """Comfort periods keyed by `Weekday`, from Monday through Sunday."""
        days = tuple(getattr(self, field) for field in WEEKDAY_FIELDS)
        return {
            Weekday(day): list(starmap(ComfortPeriod, periods or []))
            for day, periods in enumerate(days)
        }

    async def async_set_day(self, weekday: Weekday, periods: list[ComfortPeriod]) -> None:
        """Write one weekday of the comfort program."""
        day = Weekday(weekday)
        await self.write(WEEKDAY_FIELDS[day], [(period.start, period.end) for period in periods])
        if self._on_day_written is not None:
            self._on_day_written(self)


class ScheduleFacade:
    """Expose the named GTW26 weekly programs through a small schedule API."""

    SCHEDULE_BASES: ClassVar[dict[str, int]] = SCHEDULE_BASES

    def __init__(self, unit: ModbusUnit) -> None:
        """Build one weekly program for each supported schedule block."""
        self._programs: dict[str, WeekProgram] = {
            name: WeekProgram(unit, base_offset=base) for name, base in self.SCHEDULE_BASES.items()
        }

    def _require_schedule(self, name: str) -> WeekProgram:
        """Return a named program or raise ``ValueError`` for an unknown name."""
        if name not in self._programs:
            raise ValueError(f"unknown schedule {name!r}")
        return self._programs[name]

    def bundles(self) -> dict[str, WeekProgram]:
        """Return the named programs for engine registration."""
        return self._programs

    async def async_update(self, name: str) -> None:
        """Poll one named weekly program."""
        await self._require_schedule(name).async_update()

    def get_day(self, schedule: str, weekday: Weekday) -> list[ComfortPeriod]:
        """Return one weekday from a named schedule."""
        return self._require_schedule(schedule).week[Weekday(weekday)]

    def get_week(self, schedule: str) -> dict[Weekday, list[ComfortPeriod]]:
        """Return all weekdays from a named schedule."""
        return self._require_schedule(schedule).week

    async def async_set_day(
        self, schedule: str, weekday: Weekday, periods: list[ComfortPeriod]
    ) -> None:
        """Write one weekday of a named schedule."""
        await self._require_schedule(schedule).async_set_day(weekday, periods)
