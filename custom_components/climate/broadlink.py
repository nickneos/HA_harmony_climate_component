import asyncio
import logging
import binascii
import socket
import os.path
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.core import callback
from homeassistant.components.climate import (
    ClimateDevice, PLATFORM_SCHEMA, STATE_OFF, STATE_ON,
    STATE_HEAT, STATE_COOL, STATE_AUTO,
    ATTR_OPERATION_MODE, SUPPORT_OPERATION_MODE, 
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE,
    SUPPORT_ON_OFF)
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE, 
    CONF_NAME, CONF_HOST, CONF_MAC, CONF_TIMEOUT, 
    CONF_CUSTOMIZE, PRECISION_HALVES,
    PRECISION_TENTHS, PRECISION_WHOLE)
from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.helpers.restore_state import RestoreEntity
from configparser import ConfigParser
from base64 import b64encode, b64decode

REQUIREMENTS = ['broadlink==0.9.0']

_LOGGER = logging.getLogger(__name__)

VERSION = '1.1.2'

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_OPERATION_MODE | SUPPORT_FAN_MODE | SUPPORT_ON_OFF

CONF_IRCODES_INI = 'ircodes_ini'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_PRECISION = 'precision'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_OPERATIONS = 'operations'
CONF_FAN_MODES = 'fan_modes'
CONF_DEFAULT_FAN_MODE = 'default_fan_mode'

DEFAULT_NAME = 'Broadlink IR Climate'
DEFAULT_TIMEOUT = 10
DEFAULT_RETRY = 3
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_PRECISION = PRECISION_WHOLE
DEFAULT_OPERATION_LIST = [STATE_AUTO]
DEFAULT_FAN_MODE_LIST = ['auto']

CUSTOMIZE_SCHEMA = vol.Schema({
    vol.Optional(CONF_OPERATIONS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_FAN_MODES): vol.All(cv.ensure_list, [cv.string])
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_MAC): cv.string,
    vol.Required(CONF_IRCODES_INI): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int, 
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP): vol.Coerce(float),
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP): vol.Coerce(float),
    vol.Optional(CONF_PRECISION, default=DEFAULT_PRECISION): vol.In(
        [PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE]),
    vol.Optional(CONF_TEMP_SENSOR): cv.entity_id,
    vol.Optional(CONF_CUSTOMIZE, default={}): CUSTOMIZE_SCHEMA
})

async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the Broadlink IR Climate platform."""
    name = config.get(CONF_NAME)
    ip_addr = config.get(CONF_HOST)
    mac_addr = binascii.unhexlify(config.get(CONF_MAC).encode().replace(b':', b''))
      
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    precision = config.get(CONF_PRECISION)
    temp_sensor_entity_id = config.get(CONF_TEMP_SENSOR)
    operation_list = config.get(CONF_CUSTOMIZE).get(CONF_OPERATIONS, []) or DEFAULT_OPERATION_LIST
    operation_list = [STATE_OFF] + operation_list
    fan_list = config.get(CONF_CUSTOMIZE).get(CONF_FAN_MODES, []) or DEFAULT_FAN_MODE_LIST
        
    import broadlink
    
    broadlink_device = broadlink.rm((ip_addr, 80), mac_addr, None)
    broadlink_device.timeout = config.get(CONF_TIMEOUT)

    try:
        broadlink_device.auth()
    except socket.timeout:
        _LOGGER.error("Failed to connect to Broadlink RM Device")
     
    ircodes_ini_file = config.get(CONF_IRCODES_INI)
    
    if ircodes_ini_file.startswith("/"):
        ircodes_ini_file = ircodes_ini_file[1:]
        
    ircodes_ini_path = hass.config.path(ircodes_ini_file)
    
    if os.path.exists(ircodes_ini_path):
        ircodes_ini = ConfigParser()
        ircodes_ini.read(ircodes_ini_path)
    else:
        _LOGGER.error("The ini file was not found. (" + ircodes_ini_path + ")")
        return
    
    async_add_devices([
        BroadlinkIRClimate(hass, name, broadlink_device, ircodes_ini, min_temp, max_temp, precision, temp_sensor_entity_id, operation_list, fan_list)
    ])

class BroadlinkIRClimate(ClimateDevice, RestoreEntity):

    def __init__(self, hass, name, broadlink_device, ircodes_ini, min_temp, max_temp, precision, temp_sensor_entity_id, operation_list, fan_list):
                 
        """Initialize the Broadlink IR Climate device."""
        self.hass = hass
        self._name = name

        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = min_temp
        self._precision = precision
        self._unit_of_measurement = hass.config.units.temperature_unit           
        
        self._operation_list = operation_list
        self._fan_list = fan_list
        
        self._current_operation = STATE_OFF
        self._current_fan_mode = fan_list[0]
        
        self._current_temperature = None
        self._temp_sensor_entity_id = temp_sensor_entity_id 
        
        self._last_on_operation = None
                        
        self._broadlink_device = broadlink_device
        self._commands_ini = ircodes_ini
        
        self._temp_lock = asyncio.Lock()
        
        if temp_sensor_entity_id:
            async_track_state_change(
                hass, temp_sensor_entity_id, self._async_temp_sensor_changed)
                
            sensor_state = hass.states.get(temp_sensor_entity_id)    
                
            if sensor_state:
                self._async_update_current_temp(sensor_state)
    
    
    async def send_ir(self):
        async with self._temp_lock:
            section = self._current_operation.lower()
            
            value = self._current_fan_mode.lower() + "_" + '{0:g}'.format(self._target_temperature) if not section == 'off' else 'off_command'
            command = self._commands_ini.get(section, value)
            
            for retry in range(DEFAULT_RETRY):
                try:
                    payload = b64decode(command)
                    _LOGGER.debug("Sending command [%s %s] to %s", section, value, self._name)
                    _LOGGER.debug("IR Code: %s", command)
                    self._broadlink_device.send_data(payload)
                    break
                except (socket.timeout, ValueError):
                    try:
                        self._broadlink_device.auth()
                    except socket.timeout:
                        if retry == DEFAULT_RETRY-1:
                            _LOGGER.error("Failed to send packet to Broadlink RM Device")
        
    
    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_current_temp(new_state)
        await self.async_update_ha_state()
        
    @callback
    def _async_update_current_temp(self, state):
        """Update thermostat with latest state from sensor."""
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)

        try:
            _state = state.state
            if self.represents_float(_state):
                self._current_temperature = self.hass.config.units.temperature(
                    float(_state), unit)
        except ValueError as ex:
            _LOGGER.error('Unable to update from sensor: %s', ex)    

    def represents_float(self, s):
        try: 
            float(s)
            return True
        except ValueError:
            return False     

    
    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature
        
    @property
    def min_temp(self):
        """Return the polling state."""
        return self._min_temp
        
    @property
    def max_temp(self):
        """Return the polling state."""
        return self._max_temp    
        
    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature
        
    @property
    def target_temperature_step(self):
        """Return the supported step of target temperature."""
        return self._precision
        
    @property
    def precision(self):
        return self._precision

    @property
    def current_operation(self):
        """Return current operation ie. heat, cool."""
        return self._current_operation
        
    @property
    def last_on_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_on_operation
        
    @property
    def last_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_operation

    @property
    def operation_list(self):
        """Return the list of available operation modes."""
        return self._operation_list

    @property
    def current_fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def fan_list(self):
        """Return the list of available fan modes."""
        return self._fan_list
        
    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_FLAGS
    
    @property
    def is_on(self):
        return None
    
    @property
    def state_attributes(self):
        data = super().state_attributes
        data['last_on_operation'] = self._last_on_operation
        return data
 
    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        
        if temperature is None:
            return
            
        if temperature < self._min_temp or temperature > self._max_temp:
            _LOGGER.warning('The temperature value is out of min/max range') 
            return
                    
        self._target_temperature = round(temperature) if self._precision == PRECISION_WHOLE else round(temperature, 1)
        
        if not (self._current_operation.lower() == 'off'):
            await self.send_ir()
                
        await self.async_update_ha_state()

    async def set_operation_mode(self, operation_mode):
        """Set new target temperature."""
        self._current_operation = operation_mode
        
        if not operation_mode == 'off':
            self._last_on_operation = operation_mode

        await self.send_ir()
        await self.async_update_ha_state()
        
    async def set_fan_mode(self, fan):
        """Set new target temperature."""
        self._current_fan_mode = fan
        
        if not (self._current_operation.lower() == 'off'):
            await self.send_ir()
            
        await self.async_update_ha_state()
        
    async def async_turn_off(self):
        """Turn thermostat off."""
        await self.async_set_operation_mode(STATE_OFF)
        
    async def async_turn_on(self):
        """Turn thermostat off."""
        if self._last_on_operation is not None:
            await self.async_set_operation_mode(self._last_on_operation)
        else:
            await self.async_set_operation_mode(self._operation_list[1])
            
    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
    
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            self._target_temperature = last_state.attributes['temperature']
            self._current_operation = last_state.attributes['operation_mode']
            self._current_fan_mode = last_state.attributes['fan_mode']
            
            if 'last_on_operation' in last_state.attributes:
                self._last_on_operation = last_state.attributes['last_on_operation']
