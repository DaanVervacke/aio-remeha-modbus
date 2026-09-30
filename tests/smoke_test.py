"""Test that required files have been included in a build."""


def test_smoke():
    """Test that the API can be imported."""
    from aio_remeha_modbus.gtw08 import const  # noqa: PLC0415

    assert const.Limits.CH_MAX_TEMP is not None


def test_remeha_query_entry_point():
    """Test that the remeha-query console script resolves to the packaged module."""
    from importlib.metadata import entry_points  # noqa: PLC0415

    (script,) = (
        entry for entry in entry_points(group="console_scripts") if entry.name == "remeha-query"
    )
    assert script.value == "aio_remeha_modbus.query:run"
    assert callable(script.load())


if __name__ == "__main__":
    test_smoke()
    test_remeha_query_entry_point()
