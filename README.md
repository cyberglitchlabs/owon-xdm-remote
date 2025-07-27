# OWON XDM Remote

After I was a bit annoyed by the fact that the XDM1041 starts in low sampling mode and is not saving last settings at power down, I had the idea to have an ESP32 automatically set the sampling mode to high via SCPI after starting. During the development I came up with additionally integrating the multimeter into my home automation via WiFi/MQTT. It enables reliable SCPI communication over Wi-Fi, ideal for remote measurement retrieval and automation.

<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/OWON%20XDM1041.png">

## Features

* Setting custom startup configuration: sampling mode set to high (can easily be modified and extended for measurement mode or range, etc.)
* MQTT integration:

  * Commands via `xdm1041/cmd`
  * Responses via `xdm1041/resp`
  * Device status via `xdm1041/status` (retained)
  * Wi-Fi quality via `xdm1041/wifiquality`
  * Heartbeat via `xdm1041/heartbeat`
* LED feedback: startup states and errors indicated by onboard LED
* Separation of sensitive data via `secrets.py`

## Hardware
To connect the ESP32 to the multimeter via UART, the original UART module is removed and replaced by the custom PCBA provided in this repository. The PCBA is powered directly from the internal supply of the OWON XDM1041, so no external power source is required.
### Original UART PCBA
<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/OWON%20XDM%201041%20with%20original%20UART%20PCBA.png">

### Modified Communication PCBA
<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/OWON%20XDM%201041%20with%20remote%20PCBA.png">

The PCB is a simple two-layer design. The bottom layer is a ground plane, while the top layer is split into V_IN and 3.3 V power planes.

<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/OWON%20XDM%20Remote%20PCB%20Layout%20Top%20V1.1.png">
<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/OWON%20XDM%20Remote%20PCBA%20V1.1.png">

The ESP32 module used is an ESP32-C3 Super Mini Plus, which includes an external antenna. This antenna is attached inside the case for improved signal strength. In contrast, the standard ESP32-C3 Super Mini (without external antenna) showed significantly poor Wi-Fi range in testing and is therefore not recommended.

<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/ESP32%20C3%20Super%20Mini%20Plus.png">

The connection to the OWON Mainboard is done via a JST XH cable.

<img width="400" alt="image" src="https://github.com/Elektroarzt/owon-xdm-remote/blob/main/assets/JST%20XH%20Cable.png">

The USB connection of the ESP32 can be used for debugging while the board is powered by the multimeter, thanks to a Schottky diode that isolates the onboard supply from USB power.

All files required for production with JLCPCB are provided in the production folder. The ZIP file can be uploaded directly to the JLCPCB order interface.

## Partslist
| Reference |  Part                    | Remark                                | Source      |
| --------  | ------------------------ | ------------------------------------- | ----------- |
| D1        | Schottky Diode           | Type: SS14 or similar                 | Everywhere  |
| J1        | JST XH Connector         | 2,54mm pitch, 90° angled              | Ali Express |
| U1        | ESP32 C3 Super Mini Plus | Including Antenna                     | Ali Express |
|           | JST XH Cable             | Type: Reverse side, 5 pin, XH 2,54mm  | Ali Express |
|           | PCB                      | Production file has JLCPCB format     | JLCPCB      |

## Compatibility

The hard- and software is tested on a XDM1041 and might be compatible to further OWON XDM models. Please confirm, if you successfully tested other models, and I will update this list.

## Installation

1. **Flash MicroPython**
   using Thonny or follow [instructions on micropython.org](https://micropython.org/download/ESP32_GENERIC_C3/)

2. **Upload files**
   to the ESP32:

   * `main.py`
   * `secrets.py` (adjust to your environment)

3. **Screw in and connect the PCBA** via the JST cable and power up the XDM multimeter. The ESP connects to Wi-Fi and MQTT, initializes the multimeter, and starts processing commands.

## MQTT Topics
To communicate withe the multimeter, send a valid command to the corresponding topic xdm1041/cmd. If there is an answer to the command, it will be returned on xdm1041/resp. The command set can be found at [this OWON page](https://files.owon.com.cn/software/Application/XDM1000_Digital_Multimeter_Programming_Manual.pdf).

| Topic                 | Description                      | Type      |
| --------------------- | -------------------------------- | --------- |
| `xdm1041/cmd`         | SCPI commands (e.g. `MEAS1?`)    | Publish   |
| `xdm1041/resp`        | Response to SCPI commands        | Subscribe |
| `xdm1041/status`      | `online` / `offline` (retained)  | Subscribe |
| `xdm1041/heartbeat`   | Every 60 s: `alive`              | Subscribe |
| `xdm1041/wifiquality` | Wi-Fi quality in percent (0–100) | Subscribe |

## Typical Usage

In a Node-RED dashboard or a Home Assistant MQTT sensor, the ESP32 can be used as if the OWON XDM1041 was directly network-enabled.

Example command to `xdm1041/cmd`:

```plain
MEAS1?
```

Expected response on `xdm1041/resp`:

```plain
5.123456E-03
```

If you just like to have your custom parameters set at startup of the multimeter, just don't use the WiFi / MQTT part.

## Startup Behavior

On startup, the controller runs a three-stage initialization:

1. Check for UART line idle timeout
2. Identify device via `*IDN?`
3. Enable and verify fast-sampling mode (`RATE F`, `RATE?`)

Errors are indicated using LED signals (GPIO 8). A successful startup results in a retained MQTT `online` message.

## Contribution
If you’d like to contribute to the project, you’re very welcome. The current firmware is written in MicroPython and was vibe-coded with GPT o4-mini-high. I’m open to improvements and collaboration.

## Notes
In some pictures you see V1.0 PCB. All changes to V1.1 are tested. I will update the pictures, once I receive the V1.1 boards.

## Disclaimer
> :warning: **WARNING**: You may only **USE THIS PROJECT AT YOUR OWN RISK**. The
  information provided is meant to be helpful but may contain errors or may be
  misinterpreted. Neither myself nor any of the contributors to this project
  provide any warranty or will assume any responsibility for any damage you
  cause yourself or others by using this project.

---

## License

This project is licensed under the GNU General Public License v3.0. See the `LICENSE` file for details.
