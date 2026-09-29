"""GTW26-specific register field decoders."""

from modbus_connection.model import NumberField

from aio_remeha_modbus.gtw26.const import HEATING_MODE_MASK, MODEL_CODES, HeatingMode
from aio_remeha_modbus.helpers.fields import NO_SENSOR, code_map
from aio_remeha_modbus.helpers.gtw26 import DAYS, PROGRAMS


def controller_type_field() -> NumberField[str | int]:
    """Read register 457 as a controller type label, unknown codes kept as raw ints."""
    return code_map(457, MODEL_CODES)


class _TimeProgram:
    """Map a program-selection register to the P1 to P4 program it selects."""

    def __call__(self, raw: int) -> int | None:
        if raw in NO_SENSOR:
            return None
        # The % PROGRAMS wrap for out-of-range bytes is unverified against the GTW-26 register documentation.
        return (raw & 0xFF) // DAYS % PROGRAMS + 1


def time_program(address: int) -> NumberField[int | None]:
    """Read the selected heating program as a number from 1 to 4."""
    return NumberField(address, signed=False, convert=_TimeProgram())


def permanent_derogation(raw: int) -> bool | None:
    """Decode verified heating override modes independently of hot-water bits.

    `True` for a permanent day or night override, `False` for automatic mode and
    temporary overrides, and `None` for modes whose override semantics are unverified.
    """
    mode = raw & HEATING_MODE_MASK
    if mode in {HeatingMode.PERM_DAY, HeatingMode.PERM_NIGHT}:
        return True
    if mode in {HeatingMode.AUTO, HeatingMode.TEMP_DAY, HeatingMode.TEMP_NIGHT}:
        return False
    return None


def derogation_until_end(raw: int) -> bool | None:
    """Decode the documented timed-override bit for known heating modes."""
    # The 0x20 bit is unverified: the annex documents bit 4 as the timed-override flag, and bits 5+ are undocumented.
    mode = raw & HEATING_MODE_MASK
    if mode in {HeatingMode.PERM_DAY, HeatingMode.PERM_NIGHT}:
        return False
    if mode in {HeatingMode.AUTO, HeatingMode.TEMP_DAY, HeatingMode.TEMP_NIGHT}:
        return bool(raw & 0x20)
    return None
