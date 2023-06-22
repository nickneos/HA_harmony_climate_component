"""
Support for Harmony Hub devices as a Climate Component.

https://github.com/so3n/HA_harmony_climate_component
"""
import asyncio
import logging
import voluptuous as vol
import homeassistant.helpers.config_validation as cv


from homeassistant.components.climate import ClimateEntity, PLATFORM_SCHEMA
from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_HEAT, HVAC_MODE_COOL,
    HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_AUTO,
    SUPPORT_TARGET_TEMPERATURE, SUPPORT_FAN_MODE,
    HVAC_MODES, ATTR_HVAC_MODE)
from homeassistant.const import (
    CONF_NAME, CONF_CUSTOMIZE, STATE_ON, STATE_UNKNOWN, ATTR_TEMPERATURE,
    PRECISION_TENTHS, PRECISION_HALVES, PRECISION_WHOLE)
from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = (
    SUPPORT_TARGET_TEMPERATURE | 
    SUPPORT_FAN_MODE
)

CONF_REMOTE_ENTITY = 'remote_entity'
CONF_MIN_TEMP = 'min_temp'
CONF_MAX_TEMP = 'max_temp'
CONF_TARGET_TEMP = 'target_temp'
CONF_TARGET_TEMP_STEP = 'target_temp_step'
CONF_TEMP_SENSOR = 'temp_sensor'
CONF_OPERATIONS = 'operations'
CONF_FAN_MODES = 'fan_modes'
CONF_NO_TEMP_OPERATIONS = 'no_temp_operations'
CONF_DEVICE_ID = 'device_id'
CONF_DEBUG_MODE = 'debug_mode'

DEFAULT_NAME = 'Harmony Climate Controller'
DEFAULT_MIN_TEMP = 16
DEFAULT_MAX_TEMP = 30
DEFAULT_TARGET_TEMP = 20
DEFAULT_TARGET_TEMP_STEP = 1
DEFAULT_OPERATION_LIST = [HVAC_MODE_HEAT, HVAC_MODE_COOL, HVAC_MODE_AUTO]
DEFAULT_NO_TEMP_OPERATION_LIST = []
DEFAULT_FAN_MODE_LIST = ['auto', 'low', 'mid', 'high']
DEFAULT_DEBUG_MODE = False

CUSTOMIZE_SCHEMA = vol.Schema({
    vol.Optional(CONF_OPERATIONS): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_FAN_MODES): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_NO_TEMP_OPERATIONS): vol.All(cv.ensure_list, [cv.string])
})

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): 
        cv.string,
    vol.Required(CONF_REMOTE_ENTITY): 
        cv.entity_id,
    vol.Required(CONF_DEVICE_ID): 
        cv.string,
    vol.Optional(CONF_MIN_TEMP, default=DEFAULT_MIN_TEMP):
        cv.positive_int,
    vol.Optional(CONF_MAX_TEMP, default=DEFAULT_MAX_TEMP):
        cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP, default=DEFAULT_TARGET_TEMP):
        cv.positive_int,
    vol.Optional(CONF_TARGET_TEMP_STEP, default=DEFAULT_TARGET_TEMP_STEP): 
        cv.positive_int,
    vol.Optional(CONF_TEMP_SENSOR): 
        cv.entity_id,
    vol.Optional(CONF_DEBUG_MODE, default=DEFAULT_DEBUG_MODE): 
        cv.boolean,
    vol.Optional(CONF_CUSTOMIZE, default={}): 
        CUSTOMIZE_SCHEMA
})

async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the Harmony Hub Climate platform."""
    name = config.get(CONF_NAME)
    remote_entity = config.get(CONF_REMOTE_ENTITY)
    device_id = config.get(CONF_DEVICE_ID)
      
    min_temp = config.get(CONF_MIN_TEMP)
    max_temp = config.get(CONF_MAX_TEMP)
    target_temp = config.get(CONF_TARGET_TEMP)
    target_temp_step = config.get(CONF_TARGET_TEMP_STEP)
    temperature_sensor = config.get(CONF_TEMP_SENSOR)
    debug_mode = config.get(CONF_DEBUG_MODE)
    operation_list = (
        config.get(CONF_CUSTOMIZE).get(CONF_OPERATIONS, []) or 
        DEFAULT_OPERATION_LIST)
    fan_list = (
        config.get(CONF_CUSTOMIZE).get(CONF_FAN_MODES, []) or 
        DEFAULT_FAN_MODE_LIST)
    no_temp_operations_list = (
        config.get(CONF_CUSTOMIZE).get(CONF_NO_TEMP_OPERATIONS, []) or 
        DEFAULT_NO_TEMP_OPERATION_LIST)
         
    async_add_entities([
        HarmonyIRClimate(hass, name, remote_entity, device_id, min_temp, 
                         max_temp, target_temp, target_temp_step,
                         temperature_sensor, operation_list, fan_list, 
                         debug_mode, no_temp_operations_list)
    ])

class HarmonyIRClimate(ClimateEntity, RestoreEntity):

    def __init__(self, hass, name, remote_entity, device_id, min_temp, 
                max_temp, target_temp, target_temp_step, 
                temperature_sensor, operation_list, fan_list, 
                debug_mode, no_temp_operations_list):
        """Initialize Harmony IR Climate device."""
        self.hass = hass
        self._name = name
        self._remote_entity = remote_entity
        self._device_id = device_id
        self._min_temp = min_temp
        self._max_temp = max_temp
        self._target_temperature = target_temp
        self._target_temperature_step = target_temp_step
        self._temperature_sensor = temperature_sensor
        self._debug_mode = debug_mode

        valid_hvac_modes = [x for x in operation_list if x in HVAC_MODES]
        valid_no_temp_operation_modes = [x for x in no_temp_operations_list if x in HVAC_MODES]
        
        self._operation_modes = [HVAC_MODE_OFF] + valid_hvac_modes
        self._no_temp_operation_modes = valid_no_temp_operation_modes
        self._fan_modes = fan_list

        self._hvac_mode = HVAC_MODE_OFF
        self._current_fan_mode = self._fan_modes[0]
        self._last_on_operation = None

        self._current_temperature = None
        self._unit_of_measurement = hass.config.units.temperature_unit
        self._support_flags = SUPPORT_FLAGS


    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()
    
        last_state = await self.async_get_last_state()
        
        if last_state is not None:
            self._hvac_mode = last_state.state
            self._current_fan_mode = last_state.attributes['fan_mode']
            self._target_temperature = last_state.attributes['temperature']

            if 'last_on_operation' in last_state.attributes:
                self._last_on_operation = last_state.attributes['last_on_operation']

        if self._temperature_sensor:
            async_track_state_change(self.hass, self._temperature_sensor, 
                                     self._async_temp_sensor_changed)

            temp_sensor_state = self.hass.states.get(self._temperature_sensor)
            if temp_sensor_state and temp_sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(temp_sensor_state)

    @property
    def name(self):
        """Return the name of the climate device."""
        return self._name

    @property
    def state(self):
        """Return the current state."""
        if self.hvac_mode != HVAC_MODE_OFF:
            return self.hvac_mode
        return HVAC_MODE_OFF

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit_of_measurement

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
        return self._target_temperature_step

    @property
    def hvac_modes(self):
        """Return the list of available operation modes."""
        return self._operation_modes

    @property
    def hvac_mode(self):
        """Return hvac mode ie. heat, cool."""
        return self._hvac_mode

    @property
    def last_on_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_on_operation
    
    @property
    def fan_modes(self):
        """Return the list of available fan modes."""
        return self._fan_modes
        
    @property
    def fan_mode(self):
        """Return the fan setting."""
        return self._current_fan_mode

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._current_temperature

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags
        
    @property
    def should_poll(self):
        """Return the polling state."""
        return False
        
    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)  
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return
            
        if temperature < self._min_temp or temperature > self._max_temp:
            _LOGGER.warning('The temperature value is out of min/max range') 
            return

        if self._target_temperature_step == PRECISION_WHOLE:
            self._target_temperature = round(temperature)
        else:
            self._target_temperature = round(temperature, 1)

        if hvac_mode:
            await self.async_set_hvac_mode(hvac_mode)
            return
        
        if not self._hvac_mode.lower() == HVAC_MODE_OFF:
            await self.async_send_command()

        await self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set operation mode."""        
        self._hvac_mode = hvac_mode
        
        if not hvac_mode == HVAC_MODE_OFF:
            self._last_on_operation = hvac_mode

        await self.async_send_command()
        await self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        self._current_fan_mode = fan_mode
        
        if not self._hvac_mode.lower() == HVAC_MODE_OFF:
            await self.async_send_command()
        await self.async_write_ha_state()

    async def async_turn_off(self):
        """Turn off."""
        await self.async_set_hvac_mode(HVAC_MODE_OFF)

    async def async_turn_on(self):
        """Turn on."""
        if self._last_on_operation is not None:
            await self.async_set_hvac_mode(self._last_on_operation)
        else:
            await self.async_set_hvac_mode(self._operation_modes[1])

    async def async_send_command(self):     
        """Send command to harmony device"""

        operation_mode = self._hvac_mode
        operation_mode_command_string = "".join(x.capitalize() or '_' for x in self._hvac_mode .split('_')) # Remove underscores and capitalize each word
        fan_mode = self._current_fan_mode
        target_temperature = '{0:g}'.format(self._target_temperature)

        if operation_mode.lower() == HVAC_MODE_OFF:
            command = 'Off'
        elif operation_mode.lower() in self._no_temp_operation_modes:
            command = operation_mode_command_string + fan_mode.capitalize()
        else:
            command = operation_mode_command_string + fan_mode.capitalize() + target_temperature.capitalize()

        service_data = {
            'entity_id': self._remote_entity,
            'device': self._device_id,
            'command': command
        }

        _LOGGER.debug(
            "remote.send_command %s", service_data
        )

        if self._debug_mode:
            return

        await self.hass.services.async_call(
            'remote', 'send_command', service_data) 
            
    async def _async_temp_sensor_changed(self, entity_id, old_state, 
                                         new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_temp(new_state)
        await self.async_write_ha_state()
        
    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != STATE_UNKNOWN:
                self._current_temperature = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)  
            