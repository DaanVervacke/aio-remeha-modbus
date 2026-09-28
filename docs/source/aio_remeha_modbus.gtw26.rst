aio\_remeha\_modbus.gtw26 package
=================================

Submodules
----------

aio\_remeha\_modbus.gtw26.climate\_zone module
----------------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.climate_zone
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.config module
---------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.config
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.const module
--------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.const
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.errors module
---------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.errors
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.gtw26 module
--------------------------------------

``async_probe`` detects the register layout and controller generation behind a ``ModbusUnit`` and
returns a fully constructed `GTW26` facade, raising `GTW26ProbeError` when detection fails. The
lower-level ``async_detect`` returns a `GTW26Detection` carrying ``success`` and ``failure_reason``
instead of raising for wrong-device answers; its ``device`` field holds the constructed `GTW26` on
success. Both construct the facade through the `GTW26` constructor, which applies the message
spacing the controller requires through its ``message_spacing_seconds`` parameter.

Beyond ``async_update``, the facade exposes a few helpers. ``async_read_registers`` reads and unpacks
raw holding registers for diagnostics; the register count must be between 1 and 40 and defaults to
unpacking unsigned 16-bit words. ``async_read_all_raw`` reads every mapped bundle, including the
read-once iSystem bundles, as raw register values without notifying the component instances. The
static ``async_health_check`` verifies reachability by reading a single register and raises
`RemehaModbusError` when the read fails.

The constructor accepts ``force_zone_a``, ``force_zone_b`` and ``force_zone_c`` flags that report a
zone as present even without a reported sensor reading; zone C only exists on ``isystem`` layouts,
so passing ``force_zone_c=True`` together with an explicit ``layout=RegisterLayout.BASE`` raises
``ValueError``.
Passing ``request_timeout`` requires a request timeout on the ``ModbusUnit`` instead of leaving its
configured value unchanged. Of the diagnostic components, ``service`` (read-only burner counters
and runtime values) is only populated on ``base`` layouts, while ``diagnostics`` (boiler state and
diagnostic registers) is only populated on ``isystem`` layouts; the other one is ``None``.

.. automodule:: aio_remeha_modbus.gtw26.gtw26
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.hot\_water module
-------------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.hot_water
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.model module
--------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.model
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.schedule module
------------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.schedule
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.sensors module
----------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.sensors
   :members:
   :show-inheritance:
   :undoc-members:

aio\_remeha\_modbus.gtw26.system\_discovery\_table module
----------------------------------------------------------

.. automodule:: aio_remeha_modbus.gtw26.system_discovery_table
   :members:
   :show-inheritance:
   :undoc-members:

Module contents
---------------

.. automodule:: aio_remeha_modbus.gtw26
