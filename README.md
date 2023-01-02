# ghost-input-filter
Python script for Joystick Gremlin that maps joystick buttons to virtual joysticks, while filtering out ghost inputs

<!-- ABOUT THE PROJECT -->
## About The Project

Written for the Logitech X56 Hotas (but should work for any Hotas), wherein I was having issues with ghost inputs (random button inputs that I didn't press, sent to the game). Most posts online suggest plugging the hotas into the back of the computer--which I did--or getting a powered hub--which I got--in order to fix these issues--which it didn't.

This python plugin for Joystick Gremlin will map all physical buttons on a given device to the same buttons on a vJoy device, EXCEPT where multiple buttons are detected at the same time within a configurable timespan (~50ms by default).

## How It Works

By default, this plugin will map every internal button (1-17 on an X56 Stick and 1-36 on an X56 throttle) to the corresponding button on a vJoy device.

When you press a button on the _physical_ device, the **plugin** determines if this is likely a ghost input. If it is, it is blocked. Otherwise, **Joystick Gremlin** remaps the input to a virtual **vJoy** device. This is the input that is seen by the game. **HidHide** ensures that the game only sees the _virtual_ input, and not the _physical_ device. Thus, all ghosting is ignored. 

You can also add other mappings or JG configurations in the normal gui, and they should work on top of this plugin mapping.

## Getting Started

You'll need a few programs installed and configured.

### Prerequisites

* Logitech Drivers [https://support.logi.com/hc/en-us/articles/360024844133--Downloads-X56-Space-Flight-H-O-T-A-S-](https://support.logi.com/hc/en-us/articles/360024844133--Downloads-X56-Space-Flight-H-O-T-A-S-)
    * First entry under **Windows 10**
* vJoy [https://github.com/jshafer817/vJoy.git](https://github.com/jshafer817/vJoy.git)
* HidHide [https://github.com/ViGEm/HidHide.git](https://github.com/ViGEm/HidHide.git)
* Joystick Gremlin [https://whitemagic.github.io/JoystickGremlin/](https://whitemagic.github.io/JoystickGremlin/)

### Installation

1. Download ghost_input_filter.py
2. Open Joystick Gremlin > Plugins tab
3. Add plugin > ghost_input_filter.py
4. Don't forget to **File > Save Profile**

(For an in-depth rundown of the steps for these different programs, check out the [Installation Guide](https://github.com/high-the-memory/ghost-input-filter/wiki/Installation-Guide) wiki)