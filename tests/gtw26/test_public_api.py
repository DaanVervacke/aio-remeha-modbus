"""Guard the public gtw26 surface against re-export drift."""

import aio_remeha_modbus.gtw26 as gtw26_package
from aio_remeha_modbus.gtw26 import const, gtw26, schedule, system_discovery_table


def test_all_names_are_importable_from_the_package() -> None:
    """Every ``__all__`` entry must resolve on the package itself."""
    assert all(hasattr(gtw26_package, name) for name in gtw26_package.__all__)


def test_reexports_are_the_canonical_objects() -> None:
    """The public names must alias the defining modules, not stale copies."""
    assert gtw26_package.GTW26 is gtw26.GTW26
    assert gtw26_package.async_detect is system_discovery_table.async_detect
    assert gtw26_package.async_probe is system_discovery_table.async_probe
    assert gtw26_package.GTW26Detection is system_discovery_table.GTW26Detection
    assert gtw26_package.DetectionFailureReason is system_discovery_table.DetectionFailureReason
    assert gtw26_package.RegisterLayout is const.RegisterLayout
    assert gtw26_package.ComfortPeriod is schedule.ComfortPeriod
