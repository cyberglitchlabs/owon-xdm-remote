# ESPHome SCPI Multimeter Component

This ESPHome component provides integration for SCPI-compatible digital multimeters, with specific optimizations for the OWON XDM1041. It supports both native Home Assistant API and MQTT for flexible integration options.

## Features

### Core Functionality
- 📊 Real-time measurement readings
- 🔄 Automatic unit conversion
- 📡 Dual display support
- ⚡ Fast sampling mode
- 🔌 Auto/manual range control
- 🏷️ Multiple measurement functions:
  - DC Voltage
  - AC Voltage
  - DC Current
  - AC Current
  - Resistance
  - Capacitance
  - Continuity
  - Diode Test

### Home Assistant Integration
- 🏠 Native API support
- 📱 Rich device controls
- 📈 Historical data tracking
- 🔔 Automation support
- 🛠️ Custom services
- 📊 Entity management

## Installation

1. Create a `components` directory in your ESPHome configuration directory
2. Copy the `scpi_dmm` component files into this directory:
   ```
   components/
   └── scpi_dmm/
       ├── __init__.py
       ├── scpi_dmm.h
       ├── scpi_dmm.cpp
       └── devices.py
   ```

## Configuration

### Basic Configuration
Basic configuration example:

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `uart_id` | ID | required | The UART bus ID for communication |
| `device_type` | string | `"auto"` | Device type for command set selection |
| `fast_mode` | boolean | `false` | Enable fast sampling mode on startup |
| `value` | object | required | Primary measurement sensor configuration |
| `secondary_value` | object | optional | Secondary measurement sensor configuration |
| `function_select` | object | optional | Function selection dropdown configuration |
| `range_select` | object | optional | Range mode selection configuration |
| `rate_select` | object | optional | Sample rate selection configuration |

### Sampling Mode
The `fast_mode` option determines the initial sampling rate of the multimeter:
- `fast_mode: true` - Enables fast sampling mode on startup (higher sampling rate)
- `fast_mode: false` - Uses normal sampling mode (default, better accuracy)

This can still be changed at runtime using the rate select control or service calls.

```yaml
# Enable Home Assistant API
api:
  encryption:
    key: !secret api_encryption_key

# UART Configuration
uart:
  tx_pin: GPIO21
  rx_pin: GPIO20
  baud_rate: 115200
  id: uart_bus

# SCPI DMM Component
external_components:
  - source: components
    components: [ scpi_dmm ]

scpi_dmm:
  uart_id: uart_bus
  device_type: owon_xdm  # or 'auto' for auto-detection
  fast_mode: true  # Enable fast sampling mode on startup
  
  # Primary measurement sensor
  value:
    name: "DMM Value"
    id: dmm_value
    
  # Function selection
  function_select:
    name: "DMM Function"
    id: dmm_function_select
```

## Available Entities

### Sensors
- **DMM Value**: Primary measurement value
- **DMM Secondary**: Secondary measurement (e.g., frequency in AC modes)
- **DMM Function**: Current measurement function
- **DMM Range**: Current range setting
- **DMM Status**: Device status
- **Device ID**: Device identification string

### Controls
- **Function Select**: Dropdown to choose measurement function
- **Range Select**: Toggle between auto/manual range
- **Rate Select**: Toggle between normal/fast sampling
- **Reset Button**: Reset the device
- **Zero Button**: Set relative zero

## Home Assistant Services

The component provides several services in Home Assistant:

```yaml
# Reset the meter
service: esphome.dmm_reset
target:
  device_id: your_device_id

# Set relative zero
service: esphome.dmm_relative_zero
target:
  device_id: your_device_id

# Change measurement function
service: esphome.dmm_set_function
target:
  device_id: your_device_id
data:
  function: "DC Voltage"

# Change range mode
service: esphome.dmm_set_range
target:
  device_id: your_device_id
data:
  mode: "Auto"
```

## Automation Examples

### Log High Readings
```yaml
automation:
  - trigger:
      platform: state
      entity_id: sensor.dmm_value
    condition:
      condition: template
      value_template: "{{ trigger.to_state.state | float > 10.0 }}"
    action:
      - service: notify.mobile_app
        data:
          title: "High DMM Reading"
          message: "DMM value is {{ trigger.to_state.state }}"
```

### Track Function Changes
```yaml
automation:
  - trigger:
      platform: state
      entity_id: select.dmm_function_select
    action:
      - service: persistent_notification.create
        data:
          title: "DMM Function Changed"
          message: "Function is now {{ trigger.to_state.state }}"
```

## Device-Specific Notes

### OWON XDM1041
- Supports fast sampling mode via `RATE F` command
- Implements proper frequency scaling in AC modes
- Handles firmware-specific response quirks
- Optimized command set for better performance

### Generic SCPI Devices
- Uses standard SCPI command set
- Auto-detects capabilities via `*IDN?`
- Falls back to generic commands if device-specific ones fail

## Troubleshooting

### Common Issues
1. **No Readings**
   - Check UART connections
   - Verify baud rate settings
   - Ensure proper grounding

2. **Incorrect Values**
   - Check function selection
   - Verify range settings
   - Reset device and try again

3. **Connection Issues**
   - Check USB/UART adapter
   - Verify cable connections
   - Ensure proper power supply

### Debug Mode
Enable debug logging in your configuration:
```yaml
logger:
  level: DEBUG
  logs:
    scpi_dmm: DEBUG
```

## Contributing

Contributions are welcome! Please feel free to submit pull requests or create issues for:
- Additional device support
- New features
- Bug fixes
- Documentation improvements

## License

This project is licensed under the MIT License - see the LICENSE file for details.
