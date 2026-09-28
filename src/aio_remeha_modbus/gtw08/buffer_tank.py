"""Implementation of the buffer tank sub-unit."""

from aio_remeha_modbus.gtw08.const import REMEHA_MAX_SPAN
from aio_remeha_modbus.gtw08.model import RemehaComponent
from aio_remeha_modbus.helpers.fields import int16


class BufferTank(RemehaComponent):
    """A component that contains the buffer tank measurements.

    See the `BufferTank` sheet of the GTW-08 parameter list.
    """

    max_span = REMEHA_MAX_SPAN
    register_ranges = ((7600, 7601),)

    temperature_bottom = int16(address=7600, scale=0.01, unit="°C")
    """The measured buffer tank temperature at the bottom sensor (parameter BM001)."""

    temperature_top = int16(address=7601, scale=0.01, unit="°C")
    """The measured buffer tank temperature at the top sensor (parameter BM002)."""
