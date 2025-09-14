import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.components import uart, sensor, text_sensor
from esphome.const import (
    CONF_ID,
    CONF_MODEL,
    CONF_TEMPERATURE,
    DEVICE_CLASS_VOLTAGE,
    DEVICE_CLASS_CURRENT,
    DEVICE_CLASS_TEMPERATURE,
    STATE_CLASS_MEASUREMENT,
    UNIT_VOLT,
    UNIT_AMPERE,
    UNIT_OHM,
    UNIT_HERTZ,
    UNIT_CELSIUS,
    UNIT_FARAD,
)

DEPENDENCIES = ['uart']
AUTO_LOAD = ['sensor', 'text_sensor']

CONF_VALUE = "value"
CONF_FUNCTION = "function"
CONF_IDN = "idn"
CONF_DEVICE_TYPE = "device_type"

# Supported device types
DEVICE_TYPES = {
    "auto": "Auto-detect from IDN response",
    "owon_xdm": "OWON XDM Series",
    "keysight_34460a": "Keysight/Agilent 34460A",
    "rigol_dm3068": "Rigol DM3068",
    "fluke_8845a": "Fluke 8845A/8846A",
    "generic_scpi": "Generic SCPI Device",
}

# Create namespace for our component
scpi_dmm_ns = cg.esphome_ns.namespace('scpi_dmm')
SCPIDMM = scpi_dmm_ns.class_('SCPIDMM', cg.Component, uart.UARTDevice)

CONFIG_SCHEMA = cv.Schema({
    cv.GenerateID(): cv.declare_id(SCPIDMM),
    cv.Optional(CONF_DEVICE_TYPE, default="auto"): cv.enum(DEVICE_TYPES),
    cv.Optional(CONF_VALUE): sensor.sensor_schema(
        accuracy_decimals=6,
        device_class=DEVICE_CLASS_VOLTAGE,
        state_class=STATE_CLASS_MEASUREMENT,
    ),
    cv.Optional(CONF_FUNCTION): text_sensor.text_sensor_schema(),
    cv.Optional(CONF_IDN): text_sensor.text_sensor_schema(),
}).extend(cv.COMPONENT_SCHEMA).extend(uart.UART_DEVICE_SCHEMA)
