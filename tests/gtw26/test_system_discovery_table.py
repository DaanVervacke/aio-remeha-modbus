import pytest
from modbus_connection import (
    ModbusConnectionError,
    ModbusError,
    ModbusTimeoutError,
    ServerDeviceBusyError,
)
from modbus_connection.exceptions import IllegalDataAddressError
from modbus_connection.mock import MockModbusUnit

from aio_remeha_modbus.gtw08.errors import RemehaModbusError
from aio_remeha_modbus.gtw26 import (
    GTW26,
    ControllerGeneration,
    DetectionFailureReason,
    GTW26ProbeError,
    async_probe,
)


def _seed_base(unit: MockModbusUnit, type_code: int) -> None:
    unit.holding.update({
        3: 400,
        4: 14,
        5: 30,
        6: 2,
        108: 10,
        109: 9,
        110: 25,
        457: type_code,
    })
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
async def test_probe_base_layout(
    mock_modbus_unit: MockModbusUnit, type_code: int, variant: ControllerGeneration
):
    _seed_base(mock_modbus_unit, type_code)

    detection = await GTW26.async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.success is True
    assert detection.failure_reason is None
    assert detection.raw_type_code == type_code
    assert detection.generation is variant
    assert detection.isystem_detected is False
    assert await async_probe(mock_modbus_unit)


@pytest.mark.parametrize("type_code", [20, 24], ids=["diematic_3", "diematic_4"])
@pytest.mark.asyncio
async def test_probe_isystem_layout(mock_modbus_unit: MockModbusUnit, type_code: int):
    _seed_base(mock_modbus_unit, type_code)
    _seed_isystem(mock_modbus_unit)

    detection = await GTW26.async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.success is True
    assert detection.failure_reason is None
    assert detection.raw_type_code == type_code
    assert detection.generation is (
        ControllerGeneration.GENERATION_3 if type_code == 20 else ControllerGeneration.GENERATION_4
    )
    assert detection.isystem_detected is True


@pytest.mark.asyncio
async def test_probe_accepts_isystem_without_base_identity(mock_modbus_unit: MockModbusUnit):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(3, IllegalDataAddressError())
    mock_modbus_unit.fail_read(108, IllegalDataAddressError())
    mock_modbus_unit.fail_read(457, IllegalDataAddressError())

    detection = await GTW26.async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.success is True
    assert detection.raw_type_code is None
    assert detection.generation is None


@pytest.mark.asyncio
async def test_probe_returns_unknown_model_failure(mock_modbus_unit: MockModbusUnit):
    _seed_base(mock_modbus_unit, 21)
    _seed_isystem(mock_modbus_unit)

    detection = await GTW26.async_detect(mock_modbus_unit)

    assert detection.device is None
    assert detection.success is False
    assert detection.failure_reason is DetectionFailureReason.UNKNOWN_MODEL
    assert detection.raw_type_code == 21
    assert detection.isystem_detected is True


@pytest.mark.asyncio
async def test_probe_returns_not_a_gtw26_failure(mock_modbus_unit: MockModbusUnit):
    mock_modbus_unit.fail_read(3, IllegalDataAddressError())
    mock_modbus_unit.fail_read(108, IllegalDataAddressError())
    mock_modbus_unit.fail_read(457, IllegalDataAddressError())
    mock_modbus_unit.fail_read(600, IllegalDataAddressError())
    mock_modbus_unit.fail_read(679, IllegalDataAddressError())

    detection = await GTW26.async_detect(mock_modbus_unit)

    assert detection.device is None
    assert detection.success is False
    assert detection.failure_reason is DetectionFailureReason.NOT_A_GTW26
    assert all(block.outcome == "unsupported" for block in detection.base_probe)
    assert all(block.outcome == "unsupported" for block in detection.isystem_probe)


@pytest.mark.parametrize(
    ("error_type", "error"),
    [
        pytest.param(ModbusConnectionError, ModbusConnectionError("link down"), id="connection"),
        pytest.param(ModbusTimeoutError, ModbusTimeoutError("timeout"), id="timeout"),
    ],
)
@pytest.mark.asyncio
async def test_probe_propagates_transport_errors(
    mock_modbus_unit: MockModbusUnit, error_type: type[ModbusError], error: ModbusError
):
    _seed_isystem(mock_modbus_unit)
    mock_modbus_unit.fail_read(3, error)
    mock_modbus_unit.fail_read(457, error)

    with pytest.raises(error_type):
        await GTW26.async_detect(mock_modbus_unit)


@pytest.mark.asyncio
async def test_probe_retains_register_errors_as_evidence(mock_modbus_unit: MockModbusUnit):
    _seed_base(mock_modbus_unit, 24)
    _seed_isystem(mock_modbus_unit)
    error = ServerDeviceBusyError("busy")
    mock_modbus_unit.fail_read(3, error)

    detection = await GTW26.async_detect(mock_modbus_unit)

    assert isinstance(detection.device, GTW26)
    assert detection.success is True
    assert detection.raw_type_code == 24
    assert detection.generation is ControllerGeneration.GENERATION_4
    block = detection.base_probe[0]
    assert block.outcome == "error"
    assert block.error is error
    assert block.error_type == type(error).__name__
    assert block.error_message == str(error)


@pytest.mark.asyncio
async def test_probe_raises_probe_error_on_failed_detection(mock_modbus_unit: MockModbusUnit):
    _seed_base(mock_modbus_unit, 21)
    _seed_isystem(mock_modbus_unit)

    with pytest.raises(GTW26ProbeError) as caught:
        await async_probe(mock_modbus_unit)

    assert caught.value.detection.failure_reason is DetectionFailureReason.UNKNOWN_MODEL
    assert caught.value.detection.raw_type_code == 21


@pytest.mark.asyncio
async def test_facade_setup_raises_probe_error_on_failed_detection(
    mock_modbus_unit: MockModbusUnit,
):
    mock_modbus_unit.fail_read(3, IllegalDataAddressError())
    mock_modbus_unit.fail_read(108, IllegalDataAddressError())
    mock_modbus_unit.fail_read(457, IllegalDataAddressError())
    mock_modbus_unit.fail_read(600, IllegalDataAddressError())
    mock_modbus_unit.fail_read(679, IllegalDataAddressError())
    device = GTW26("test", mock_modbus_unit)

    with pytest.raises(GTW26ProbeError) as caught:
        await device.async_ensure_setup()

    assert caught.value.detection.failure_reason is DetectionFailureReason.NOT_A_GTW26


@pytest.mark.asyncio
async def test_health_check_reads_one_register(mock_modbus_unit: MockModbusUnit):
    mock_modbus_unit.holding[457] = 24

    assert await GTW26.async_health_check(mock_modbus_unit) is None

    blocks = [
        (event.address, event.count)
        for event in mock_modbus_unit.read_events
        if event.register_type == "holding"
    ]
    assert blocks == [(457, 1)]


@pytest.mark.asyncio
async def test_health_check_raises_translated_error(mock_modbus_unit: MockModbusUnit):
    mock_modbus_unit.fail_read(457, ModbusTimeoutError("timeout"))

    with pytest.raises(RemehaModbusError) as caught:
        await GTW26.async_health_check(mock_modbus_unit)

    assert caught.value.translation_key == "health_check_failed"
