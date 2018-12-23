# Harmony Hub Climate Component

I created this custom climate component to control air conidioners through a Harmony Hub. I forked from this [project](https://github.com/vpnmaster/homeassistant-custom-components), which was created for Broadlink RM Devices, so thanks goes to [vpnmaster](https://github.com/vpnmaster) for doing the hard work in creating that component.

#### Installing
Download or clone this project, and place the custom_components folder and its contents into your Home Assistant config folder.



#### Configuration in configuration.yaml:
**name** (Optional): Name of climate component<br />
**host** (Required): The IP address of the Harmony Hub device<br />
**port** (Optional): The Harmony device’s port (default: 5222)<br />
**device_id** (Required): The ID Harmony has assigned to your air conditioner unit (see below for how to obtain)<br />
**min_temp** (Optional): Set minimum set point available (default: 16)<br />
**max_temp** (Optional): Set maximum set point available (default: 30)<br />
**target_temp** (Optional): Set initial target temperature. (default: 20)<br />
**target_temp_step** (Optional): set target temperature step. (default: 1)<br />
**temp_sensor** (Optional): **entity_id** for a temperature sensor, **temp_sensor.state must be temperature.**<br />
**default_operation** (Optional): (default: 'off')<br />
**default_fan_mode** (Optional): (default: auto)<br />
**customize** (Optional): List of options to customize.<br />
  **- operations** (Optional*): List of operation modes (default: idle, heat, cool, auto)<br />
  **- fan_modes** (Optional*): List of fan modes (default: low, mid, high, auto)<br />
  
#### Example:
```
climate:
  - platform: harmony
    name: Living Room
    host: '192.168.0.10'
    device_id: 12345678
    min_temp: 18
    max_temp: 30
    target_temp: 20
    target_temp_step: 1
    temp_sensor: sensor.living_room_temp
    default_operation: 'off'
    default_fan_mode: auto
    customize:
      operations:
        - 'off'
        - cool
        - heat
      fan_modes:
        - low
        - mid
        - high
        - auto
```

#### How to obtain your Air Conditioner's Device ID

This assumes you have already setup the official home assitant [harmony component](https://www.home-assistant.io/components/remote.harmony/) and have added your air conditioner as a device in the [MyHarmony](https://www.myharmony.com) software.
* in your home assistant config folder, delete `harmony_*.conf` if it exists. eg. mine is called `harmony_living_room.conf`
* restart home assistant
* when it boots up it should create a new `harmony_*.conf` file. Open this and find your air conditioner device, it should have an ID number next to it.

#### How to learn and name all the IR commands for your air conditioner
This part is unfortunately going to be manual. Every combination of **operations** (heat, cool, dry, etc), **fan modes** (low, mid, high, auto, etc) and **temperatures**, will need to be learned manually within the MyHarmony software. The naming convention of each command is important for this component to work.

* in MyHarmony, go to devices > your air conditioner and click on **Add or Fix a Command**
* Click on **add a missing command** and enter a name in the following format: *OperationFanmodeTemperature* eg. *CoolHigh18* and then follow the prompts within MyHarmony
    
some important notes about the naming convention for commands:
* capitalise the first letter of the *operation* and *fan-mode*
* **Operation** must be one of the operations listed in your configuration.yaml file
* **Fanmode** must be one of the fan_modes listed in your configuration.yaml file
* **Temperature** must be an integer in the range specified by your min/max temp in configuration.yaml file
* The only exception to these rules is the 'off' command. Just name this as **Off** in MyHarmony (note the capitalised first letter)

Some valid examples of command names based on the above configuration.yaml example
```
Off
CoolAuto18
CoolAuto19
CoolAuto20
...
CoolAuto30
CoolHigh18
CoolHigh19
CoolHigh20
...
CoolHigh30
HeatLow18
HeatLow19
etc
etc 
```