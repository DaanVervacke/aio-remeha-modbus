import pytest
from modbus_connection import ModbusConnectionError, ModbusTimeoutError
from modbus_connection.exceptions import IllegalDataAddressError

from aio_remeha_modbus.gtw26 import (
    GTW26,
    ControllerGeneration,
    Gtw26ProbeError,
    async_detect,
    async_probe,
)


def _seed_base(unit, type_code: int) -> None:
    unit.holding.update(
        {
            3: 400,
            4: 14,
            5: 30,
            6: 2,
            108: 10,
            109: 9,
            110: 25,
            457: type_code,
        }
    )
    unit.fail_read(600, IllegalDataAddressError())
    unit.fail_read(679, IllegalDataAddressError())


def _seed_isystem(unit) -> None:
    unit.holding.update({600: 412, 679: 12, 680: 30, 681: 2, 682: 10, 683: 9, 684: 25})
    unit.fail_read(600, None)
    unit.fail_read(679, None)


@pytest.mark.parametrize(
    ("type_code", "variant"),
    [
        pytest.param(20, ControllerGeneration.GENERATION_3, id="diematic_3"),
        pytest.param(22, ControllerGeneration.GENERATION_3, id="diematic_m3"),
        pytest.param(24, ControllerGeneration.GENERATION_4, id="diematic_4"),
    ],
)
@pytest.mark.asyncio
async def test_probe_base_layout(mock_modbus_unit, type_code, variant):
    _seed_base(mock_modbus_unit, type_code)

    detection = await async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.raw_type_code == type_code
    assert detection.generation is variant
    assert detection.isystem_detected is False
    assert await async_probe(mock_modbus_unit)


@pytest.mark.parametrize("type_code", [20, 24], ids=["diematic_3", "diematic_4"])
@pytest.mark.asyncio
async def test_probe_isystem_layout(mock_modbus_unit, type_code):
    _seed_base(mock_modbus_unit, type_code)
    _seed_isystem(mock_modbus_unit)

    detection = await async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.raw_type_code == type_code
    assert detection.generation is (
        ControllerGeneration.GENERATION_3 if type_code == 20 else ControllerGeneration.GENERATION_4
    )
    assert detection.isystem_detected is True


@pytest.mark.asyncio
async def test_probe_accepts_isystem_without_base_identity(mock_modbus_unit):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(3, IllegalDataAddressError())
    mock_modbus_unit.fail_read(108, IllegalDataAddressError())
    mock_modbus_unit.fail_read(457, IllegalDataAddressError())

    detection = await async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.raw_type_code is None
    assert detection.generation is None


@pytest.mark.asyncio
async def test_probe_rejects_unknown_type(mock_modbus_unit):
    _seed_base(mock_modbus_unit, 21)
    _seed_isystem(mock_modbus_unit)

    with pytest.raises(Gtw26ProbeError) as caught:
        await async_detect(mock_modbus_unit)

    assert caught.value.detection.raw_type_code == 21
    assert caught.value.detection.isystem_detected is True


@pytest.mark.asyncio
async def test_probe_rejects_when_both_layouts_fail(mock_modbus_unit):
    mock_modbus_unit.fail_read(3, IllegalDataAddressError())
    mock_modbus_unit.fail_read(108, IllegalDataAddressError())
    mock_modbus_unit.fail_read(457, IllegalDataAddressError())
    mock_modbus_unit.fail_read(600, IllegalDataAddressError())
    mock_modbus_unit.fail_read(679, IllegalDataAddressError())

    with pytest.raises(Gtw26ProbeError) as caught:
        await async_detect(mock_modbus_unit)

    assert all(block.outcome == "unsupported" for block in caught.value.detection.base_probe)
    assert all(block.outcome == "unsupported" for block in caught.value.detection.isystem_probe)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(ModbusConnectionError("link down"), id="connection"),
        pytest.param(ModbusTimeoutError("timeout"), id="timeout"),
    ],
)
@pytest.mark.asyncio
async def test_probe_reports_transport_errors(mock_modbus_unit, error):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(3, error)
    mock_modbus_unit.fail_read(457, error)

    detection = await async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    block = detection.base_probe[0]
    assert block.outcome == "error"
    assert block.error is error
    assert block.error_type == type(error).__name__
    assert block.error_message == str(error)


@pytest.mark.asyncio
async def test_probe_failure_retains_known_variant(mock_modbus_unit):
    _seed_base(mock_modbus_unit, 24)
    _seed_isystem(mock_modbus_unit)
    error = ModbusTimeoutError("timeout")
    mock_modbus_unit.fail_read(3, error)

    detection = await async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.raw_type_code == 24
    assert detection.generation is ControllerGeneration.GENERATION_4
    assert detection.base_probe[0].error is error
