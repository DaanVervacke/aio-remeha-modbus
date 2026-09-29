"""GTW26 component base."""

from typing import Any, override

from modbus_connection.model import Component


class Gtw26Component(Component):
    """A GTW26 register bundle.

    A successful write is retained and returned when the field is read, until the
    next `async_update()`. Register fields are stored in `_values` and bit fields
    in `_bits`.
    """

    @override
    async def write(self, field: str, value: Any) -> None:
        """Write a writable register or coil by attribute name.

        A successful write retains the effective value the validator produced
        (the value actually sent to the controller) and returns it when the
        field is read until the next `async_update()`.

        Raises:
            AttributeError: for an unknown or read-only field.
            ValueError: if the field's write validator rejects the value, or
                the value cannot be scaled.

        """
        resolved = self.resolved_fields.get(field)
        if resolved is not None and callable(resolved.field.writable):
            value = resolved.field.writable(value)
        await super().write(field=field, value=value)
        if field in self._register_fields:
            self._values[field] = value
        elif field in self._bit_fields:
            self._bits[field] = value
