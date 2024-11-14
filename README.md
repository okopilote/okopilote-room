# okopilote-room

`okopilote-room` is the room part of the Okopilote suite. It monitors the ambiant
temperature of one or more rooms, reports heat needs to the controller and drive the
optional radiator valve.

Interface with physical devices like sensors and valves are implemented through
optional Python modules.

## Table of Contents

- [Installation](#installation)
- [Usage](#Usage)
- [License](#license)

## Installation

### FUTUR: install packages from PyPi

```console
# Install room program with sensors and relay board modules. Example with
# MCP9808 temperature sensor, controller ambiant sensor (no extra module
# required) and USB-X440 relay board:
pip install okopilote-room[mcp9808,okofen-touch4,usb-x440]

# Or install room program and sensor/valve/relay modules separately
pip install okopilote-room
pip install okopilote-devices-mcp9808
pip install okopilote-devices-usb-x440
```

### PRESENT: build and install packages

Install packages from distribution files:

```console
pip install okopilote_room-a.b.c-py3-none-any.wh
pip install okopilote_devices_common-d.e.f-py3-none-any.whl
pip install okopilote_devices_mcp9808-j.k.l-py3-none-any.whl
pip install okopilote_devices_usb_x440-m.n.o-py3-none-any.whl
```

## Usage

Copy configuration file from repository:

```console
cp -a examples/* /etc/okopilote/
```

Adjust configuration starting with `room.conf` file then run `okopilote-room`:

```console
okopilote-room -c /etc/okopilote/room.conf [-v]
```

## License

`okopilote-room` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
