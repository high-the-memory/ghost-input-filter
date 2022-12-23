# ghost-input-filter
Python script for Joystick Gremlin that maps joystick buttons to virtual joysticks, while filtering out ghost inputs

<!-- ABOUT THE PROJECT -->
## About The Project

Written for the Logitech X56 Hotas, wherein I was having issues with ghost inputs (random button inputs that I didn't press, sent to the game). Most posts online suggest plugging the hotas into the back of the computer--which I did--or getting a powered hub--which I got--in order to fix these issues--which it didn't.

This python plugin for Joystick Gremlin will map all physical buttons on a given device to the same buttons on a vJoy device, EXCEPT where multiple buttons are detected at the same time within a configurable timespan (~50ms by default).

<!-- GETTING STARTED -->
## Getting Started

You'll need a few programs installed and configured.

### Prerequisites

* vJoy [https://github.com/jshafer817/vJoy.git](https://github.com/jshafer817/vJoy.git)
* Joystick Gremlin [https://whitemagic.github.io/JoystickGremlin/](https://whitemagic.github.io/JoystickGremlin/)

### Installation

1. Download ghost_inputs.py
2. Open Joystick Gremlin > Plugins tab
3. Add plugin > ghost_inputs.py

<!-- USAGE EXAMPLES -->
## Usage

### In Joystick Gremlin:
- Click the Configuration button on the plugin
- Open Tools > Device Information
- Copy the GUID for the physical device
- Paste it in the Physical Device GUID section
- Set the vJoy device index (based on the ordering of the list of vJoy devices in Tools > Device Information)
- Configure the number of simultaneous button presses that should be considered a Ghost Input
- Configure the amount of ticks during which a button press should be evaluated

### Multiple Instances
You can create multiple instances of the plugin for each physical device and/or each JG Mode you need to filter
- Click the plus (+) button on the plugin
- Change the GUID of the physical device, the index of the vJoy device, and the Mode that should be used

### Notes
By default, this plugin will map every button (1-17 on my X56 Stick and 1-35 on my X56 throttle) to the corresponding button on a vJoy device. It is very similar to JG's "1-to-1 Mapping" preset. Make sure vJoy is configured with enough buttons for your device(s).

You can also add other mappings or JG configurations in the normal gui, and they should work on top of this plugin mapping.
