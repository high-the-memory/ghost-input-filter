# ghost-input-filter
Python script for Joystick Gremlin that maps joystick buttons to virtual joysticks, while filtering out ghost inputs

<!-- ABOUT THE PROJECT -->
## About The Project

Written for the Logitech X56 Hotas (but should work for any Hotas), wherein I was having issues with ghost inputs (random button inputs that I didn't press, sent to the game). Most posts online suggest plugging the hotas into the back of the computer--which I did--or getting a powered hub--which I got--in order to fix these issues--which it didn't.

This python plugin for Joystick Gremlin will map all physical buttons on a given device to the same buttons on a vJoy device, EXCEPT where multiple buttons are detected at the same time within a configurable timespan (~50ms by default).

<!-- GETTING STARTED -->
## Getting Started

You'll need a few programs installed and configured.

### Prerequisites

* vJoy [https://github.com/jshafer817/vJoy.git](https://github.com/jshafer817/vJoy.git)
* Joystick Gremlin [https://whitemagic.github.io/JoystickGremlin/](https://whitemagic.github.io/JoystickGremlin/)
* HidHide [https://github.com/ViGEm/HidHide.git](https://github.com/ViGEm/HidHide.git)

### Installation

1. Download ghost_inputs.py
2. Open Joystick Gremlin > Plugins tab
3. Add plugin > ghost_inputs.py

<!-- USAGE EXAMPLES -->
## Usage

### In Joystick Gremlin:
- Click the Configuration button on the plugin
- Open Tools > Device Information
- Copy the GUID for the physical device, and paste it in the Physical Device GUID section
- Copy the GUID for the virtual device to map to, and paste it in the Virtual Device GUID section
- Configure the number of simultaneous button presses that should be considered a Ghost Input
- Configure the amount of ticks during which a button press should be evaluated

#### Multiple Instances
You can create multiple instances of the plugin for each physical device and/or each JG Mode you need to filter
- Click the plus (+) button on the plugin
- Change the GUIDs of the physical and virtual devices, and the Mode that should be used

### vJoy
By default, this plugin will map every internal button (1-17 on my X56 Stick and 1-36 on my X56 throttle) to the corresponding button on a vJoy device. It is very similar to JG's "1-to-1 Mapping" preset. It will also map all axes and hats by default. Make sure vJoy is configured with enough buttons and hats for your device(s) (and ideally keep all axes on, since JG doesn't always map axes 1:1).

You can also add other mappings or JG configurations in the normal gui, and they should work on top of this plugin mapping.

### HidHide
HidHide allows you to hide your <i>physical</i> joystick from certain programs (such as your game). Configuring that will allow you to only pass vJoy inputs to your game, and thus filter out ghost inputs.
