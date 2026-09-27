"""GTW26 codec helpers.

A day's comfort schedule is 48 half-hour slots packed into three registers, a set
bit meaning comfort. `decode_day` and `encode_day` convert between that bitmap and
a list of `(start, end)` times.
"""

from datetime import time

DaySchedule = list[tuple[time, time]]
"""Comfort periods for one day, as half-hour-aligned `(start, end)` times."""

WeekSchedule = dict[int, DaySchedule]
"""Comfort periods keyed by weekday, 1 for Monday through 7 for Sunday."""

SLOTS_PER_REGISTER = 16
REGISTERS_PER_DAY = 3
DAYS = 7
PROGRAMS = 4


def _slot_time(slot: int) -> time:
    minutes = slot * 30
    return time(minutes // 60 % 24, minutes % 60)


def decode_day(words: list[int]) -> DaySchedule:
    """Decode three registers into comfort periods, a set bit meaning comfort.

    A period that runs to the end of the day ends at `time(0, 0)`.
    """
    occupied: list[int] = []
    for register in words:
        occupied.extend(
            register >> (SLOTS_PER_REGISTER - 1 - bit) & 1 for bit in range(SLOTS_PER_REGISTER)
        )

    intervals: DaySchedule = []
    start: int | None = None
    total = SLOTS_PER_REGISTER * REGISTERS_PER_DAY
    for slot in range(total):
        if occupied[slot] and start is None:
            start = slot
        elif not occupied[slot] and start is not None:
            intervals.append((_slot_time(start), _slot_time(slot)))
            start = None
    if start is not None:
        intervals.append((_slot_time(start), _slot_time(total)))
    return intervals


def encode_day(intervals: DaySchedule) -> list[int]:
    """Encode comfort periods into three registers, a set bit meaning comfort.

    A period ending at `time(0, 0)` runs to the end of the day.

    Raises:
        ValueError: if a time is not on a half-hour boundary, or a period is reversed.

    """
    total = SLOTS_PER_REGISTER * REGISTERS_PER_DAY
    words = [0] * REGISTERS_PER_DAY
    for start, end in intervals:
        if start.minute % 30:
            raise ValueError(
                f"schedule start {start} has minute {start.minute}, not a multiple of 30"
            )
        if end.minute % 30:
            raise ValueError(f"schedule end {end} has minute {end.minute}, not a multiple of 30")
        low = (start.hour * 60 + start.minute) // 30
        high = total if end == time(0, 0) else (end.hour * 60 + end.minute) // 30
        if not 0 <= low < high <= total:
            raise ValueError(f"invalid comfort period {start}-{end}")
        for slot in range(low, high):
            register, offset = divmod(slot, SLOTS_PER_REGISTER)
            words[register] |= 1 << (SLOTS_PER_REGISTER - 1 - offset)
    return words
