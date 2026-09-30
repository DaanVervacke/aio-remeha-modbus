"""Fixtures for testing."""

import json
import pathlib
from datetime import tzinfo
from typing import Any, Final

import pytest
import pytest_asyncio
from dateutil import tz
from modbus_connection import ModbusUnit
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw08 import GTW08

TESTING_TIME_ZONE: Final[str] = "Europe/Amsterdam"


def json_fixture(file_name: str) -> Any:
    """Read a fixture and return it as a `JsonValueType`."""

    path = pathlib.Path(__file__).parent.resolve().joinpath(f"fixtures/{file_name}")
    with pathlib.Path.open(path) as file:
        data = file.read()

    return json.loads(data)


def get_modbus_unit(api: GTW08) -> MockModbusUnit:
    """Return the modbus unit from the given api.

    Raises:
        TypeError if the unit is not a `MockModbusUnit`.

    """

    unit = api._unit  # noqa: SLF001
    if not isinstance(unit, MockModbusUnit):
        msg = f"Not a MockModbusUnit: {type(unit).__qualname__}"
        raise TypeError(msg)

    return unit


def update_raw_data(api: GTW08, data: tuple[int, int] | list[tuple[int, int]]):
    """Update the modbus data used by the given api.

    Args:
        api (GTW08): The api to use.
        data (list[tuple[int, int]]): A list of register/value tuples to update.

    """

    unit = get_modbus_unit(api)
    iterable = data if isinstance(data, list) else [data]
    for register, value in iterable:
        unit.holding[register] = value


def load_modbus_store(unit: MockModbusUnit, file_name: str = "modbus_store.json") -> None:
    """Load a recorded register store into the mock unit."""
    store: dict[str, str] = json_fixture(file_name)["server"]["registers"]
    unit.load_raw({"holding": {int(key): int(value, 16) for key, value in store.items()}})


@pytest.fixture
def remeha_modbus_unit(request, mock_modbus_unit: MockModbusUnit) -> ModbusUnit:
    """Load the contents of the `request.param` json fixture into the modbus unit."""

    json_file = request.param if hasattr(request, "param") else "modbus_store.json"
    load_modbus_store(mock_modbus_unit, json_file)

    return mock_modbus_unit


@pytest_asyncio.fixture
async def gtw_08(
    request,
    remeha_modbus_unit: MockModbusUnit,
) -> GTW08:
    """Create a new GTW08 device instance with a mocked modbus client."""

    # mock_modbus_client MUST be a mock, otherwise a real connection might be made and mess up the appliance.
    if not isinstance(remeha_modbus_unit, MockModbusUnit):
        pytest.fail(
            f"Trying to create GTW08 device with non-mocked modbus client type {type(remeha_modbus_unit).__qualname__}."
        )

    require_update = (
        request.param.get("require_update", True) if hasattr(request, "param") else True
    )
    name = request.param.get("name", "test_api") if hasattr(request, "param") else "test_api"
    time_zone: tzinfo | None = (
        tz.gettz(request.param.get("time_zone", TESTING_TIME_ZONE))
        if hasattr(request, "param")
        else tz.gettz(TESTING_TIME_ZONE)
    )

    api = GTW08(
        name=name,
        unit=remeha_modbus_unit,
        time_zone=time_zone,
    )
    if require_update:
        await api.async_update()

    return api


@pytest.fixture
def finalizer():
    """Return a list of callables that are executed after the test method finishes."""
    callables = []
    yield callables

    for fn in callables:
        fn()
