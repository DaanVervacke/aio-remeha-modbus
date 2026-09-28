"""GTW26 API exceptions.

The translateable base lives in `gtw08.errors` and is reused here, so a caller
handles one error shape for both gateways.
"""

from typing import TYPE_CHECKING

from aio_remeha_modbus.gtw08.errors import RemehaModbusError

if TYPE_CHECKING:
    from aio_remeha_modbus.gtw26.system_discovery_table import GTW26Detection


class GTW26ProbeError(RemehaModbusError):
    """The controller's register layout could not be identified.

    `detection` carries the probe evidence so a caller can see which blocks
    answered and which failed.
    """

    def __init__(self, detection: GTW26Detection) -> None:
        """Create a new GTW26ProbeError."""
        super().__init__(translation_key="could_not_identify_layout")
        self.detection = detection
