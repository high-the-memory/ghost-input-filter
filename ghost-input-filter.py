# python imports
import threading
import math
import time
from collections import defaultdict
# gremlin (user plugin) imports
import gremlin
from gremlin.user_plugin import *
# gremlin (developer) imports
import gremlin.joystick_handling
import gremlin.input_devices
import gremlin.control_action
from gremlin.spline import CubicSpline


# Classes

class Logger:
    def __init__(self, device, enabled, is_verbose, summary_key):

        self.device = device

        self.enabled = enabled
        self.is_verbose = is_verbose
        self.summary_key = summary_key
        self.summary = {
            'percentage': 0.0,
            'start_time': time.localtime(),
            'elapsed_time': 0.0,
            'rate': 0.0
        }
        self.counts = {
            'total': 0,
            'total_blocked': 0,
            'total_allowed': 0,
            'by_button': defaultdict(int),
            'by_simultaneity': defaultdict(int),
            'by_combination': defaultdict(int)
        }
        self.last_combination = set()

        # log a summary every time summary button is pressed (user configurable)
        @gremlin.input_devices.keyboard(self.summary_key, self.device.mode)
        def summary_callback(event):
            if event.is_pressed:
                self.summarize()

        self.starting()

    def starting(self):

        if not self.enabled:
            return

        # output general setup info

        log("")
        log("  Remapping \"" + self.device.name + "\"", str(self.device.physical_guid))
        log("     to VJoy #" + str(self.device.vjoy_id), str(self.device.virtual_guid))
        log("     on Profile", "[" + self.device.mode + "]")
        if self.device.button_filtering:
            log("        ... Button Filtering enabled")
        if self.is_verbose:
            log("        ... Verbose logging enabled")

    def ready(self):
        log("          \"" + self.device.name + "\" to VJoy #" + str(self.device.vjoy_id) + " is Ready!")

    def evaluate_ghost(self, button):

        if not self.enabled:
            return

        # on press, increment the counters
        self.counts['total_blocked'] += 1
        self.counts['by_button'][button] += 1
        self.counts['by_simultaneity'][len(self.device.concurrent_presses)] += 1.0 / len(self.device.concurrent_presses)
        self.counts['by_combination'][str(sorted(self.device.concurrent_presses))] += 1.0 / len(
            self.device.concurrent_presses)

        combination = self.device.concurrent_presses

        # if this set is the same size or bigger, save it as latest
        if len(combination) >= len(self.last_combination):
            self.last_combination = set(combination)

    def log_ghost(self):
        # on release, log the highest ghosting event
        if len(self.last_combination) > 0:
            log("> GHOST INPUTS blocked! [" + self.device.mode + "] " + self.device.name + " pressed " + str(
                len(self.last_combination)) + " buttons at once",
                str(self.last_combination), 90)
            self.last_combination = set()

    def log_legitimate(self, event):

        if not self.enabled:
            return

        # increment counters
        self.counts['total_allowed'] += 1
        if self.is_verbose:
            log("USER pressed: " + self.device.name + " button " + str(event.identifier))

    def update(self):
        self.counts['total'] = self.counts['total_blocked'] + self.counts['total_allowed']
        self.summary['percentage'] = (self.counts['total_blocked'] / self.counts['total']) * 100 if self.counts[
                                                                                                        'total'] > 0 else 0.0
        self.summary['elapsed_time'] = time.mktime(time.localtime()) - time.mktime(self.summary['start_time'])
        self.summary['per_minute'] = (self.counts['total_blocked'] / self.summary['elapsed_time']) * 60
        self.summary['per_hour'] = self.summary['per_minute'] * 60

    def summarize(self):
        if not self.enabled:
            return

        self.update()

        # output a summary
        log("")
        log("//////////////////////////////////////////////////////////////////")
        log("   Summary for \"" + self.device.name + "\"", "on Profile [" + self.device.mode + "]")
        log("   |      Total Inputs Allowed", str(self.counts['total_allowed']))
        log("   |      Total Ghost Inputs Blocked", str(self.counts['total_blocked']))
        log("   | ")
        log("   |      Elapsed Time", str(self.summary['elapsed_time']) + " seconds" + "   (" + str(
            round(self.summary['elapsed_time'] / 60, 1)) + " minutes)    (" + str(
            round(self.summary['elapsed_time'] / 3600, 1)) + " hours)")
        log("   |      Ghost Input %", str(round(self.summary['percentage'], 3)) + "%")
        log("   |      Ghost Input rate", str(round(self.summary['per_minute'], 3)) + "/min   (" + str(
            round(self.summary['per_hour'])) + "/hr)")
        if self.counts['total_blocked'] > 0:
            log("   | ")
            log("   |      By Button")
            # output how many times each button was ghosted, starting with the most common one
            for btn, cnt in sorted(self.counts['by_button'].items(), key=lambda item: item[1], reverse=True):
                log("   |            (Joy " + str(btn) + ")", str(cnt))
            log("   |      By Simultaneity")
            # output how many buttons were pressed at the same time, starting with the most common number
            for simul, cnt in sorted(self.counts['by_simultaneity'].items(), key=lambda item: item[1],
                                     reverse=True):
                log("   |            (" + str(simul) + " at once)", str(int(cnt)))
            log("   |      By Combination")
            # output which combinations of buttons were pressed at the same time, starting with the most common group
            for combo, cnt in sorted(self.counts['by_combination'].items(), key=lambda item: item[1],
                                     reverse=True):
                log("   |            " + str(combo), str(int(cnt)))

    def log(self, msg):

        if not self.enabled:
            return

        # output the message
        log(msg)


# class for each physical joystick device, for filtering and mapping
class FilteredDevice:
    def __init__(self,
                 # device
                 physical_device, name, vjoy_id, mode,
                 # buttons
                 button_remapping_enabled, button_filtering, button_timespan, button_threshold,
                 # axes
                 axis_remapping_enabled, axis_curve,
                 # hats
                 hat_remapping_enabled,
                 # debugging
                 logging_enabled, logging_is_verbose, logging_summary_key
                 ):

        self.mode = mode
        self.physical_device = physical_device
        self.physical_guid = self.physical_device._info.device_guid
        self.name = name
        self.vjoy_id = vjoy_id
        self.virtual_guid = (gremlin.joystick_handling.vjoy_devices())[self.vjoy_id - 1].device_guid
        self.virtual_device = (gremlin.joystick_handling.VJoyProxy())[self.vjoy_id]

        self.tick_len = .01666

        self.button_remapping = button_remapping_enabled
        self.button_filtering = button_filtering
        self.button_timespan = [math.ceil(float(button_timespan) / 2) * self.tick_len,
                                math.floor(float(button_timespan) / 2) * self.tick_len] if button_filtering else [0, 0]
        self.button_threshold = button_threshold
        self.button_callbacks = {'press': defaultdict(list), 'release': defaultdict(list)}

        self.axis_remapping = axis_remapping_enabled
        self.axis_curve = axis_curve

        self.hat_remapping = hat_remapping_enabled

        self.concurrent_presses = set()

        # Initialize debugging logging
        self.logger = Logger(self, logging_enabled, logging_is_verbose, logging_summary_key)

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        self.initialize_inputs(True)

        self.logger.ready()

    # set all the virtual inputs for this device to the current physical status
    def initialize_inputs(self, first_time=False):
        # for each button on the device
        if self.button_remapping:
            self.initialize_buttons(first_time)

        # for each axis on the device
        if self.axis_remapping:
            self.initialize_axes(first_time)

        # for each hat on the device
        if self.hat_remapping:
            self.initialize_hats(first_time)

    def initialize_buttons(self, first_time=False):
        self.logger.log("        ... Initializing buttons on " + self.name)
        for btn in self.physical_device._buttons:
            if btn:
                # initialize value
                try:
                    self.virtual_device.button(btn._index).is_pressed = self.physical_device.button(
                        btn._index).is_pressed
                except:
                    self.logger.log("> Error initializing button " + str(btn._index) + " value")
                else:
                    # if this is the first time, set up the decorators
                    if first_time:
                        # add a decorator function for when that button is pressed
                        @self.decorator.button(btn._index)
                        # pass that info to the function that will check other button presses
                        def callback(event, vjoy, joy):
                            # increment total buttons counter for this device (if this is a press)
                            if event.is_pressed:
                                self.start_button_monitoring(event.identifier)

                            # wait the first half of the delay timespan (set number of ticks), then check for ghost inputs
                            defer(self.button_timespan[0], self.filter_the_button, event, vjoy, joy)

    def initialize_axes(self, first_time=False):
        self.logger.log("        ... Initializing axes on " + self.name)
        # by default, axes don't seem to map 1:1, so make sure VJoy devices has all 8 axes(?)
        for aid in self.physical_device._axis:
            if aid:
                # set curve (perhaps later: customizable cubic spline? Filtering algorithm? Right now, 1:1 or S)
                curve = CubicSpline([
                    (-1.0, -1.0),
                    (-0.5, -0.25),
                    (0.0, 0.0),
                    (0.5, 0.25),
                    (1.0, 1.0)
                ])

                # initialize value
                try:
                    value = self.physical_device.axis(aid).value
                    self.virtual_device.axis(aid).value = curve(value) if self.axis_curve else value
                except:
                    self.logger.log("> Error initializing axis " + str(aid) + " value")
                else:
                    # if this is the first time, set up the decorators
                    if first_time:
                        # add a decorator function for when that axis is moved
                        @self.decorator.axis(aid)
                        def callback(event, vjoy):
                            # Map the physical axis input to the virtual one
                            vjoy[self.vjoy_id].axis(event.identifier).value = curve(
                                event.value) if self.axis_curve else event.value

    def initialize_hats(self, first_time=False):
        self.logger.log("        ... Initializing hats on " + self.name)
        for hat in self.physical_device._hats:
            if hat:
                # initialize value
                try:
                    self.virtual_device.hat(hat._index).direction = self.physical_device.hat(hat._index).direction
                except:
                    self.logger.log("> Error initializing hat " + str(hat._index) + " value")
                else:
                    # if this is the first time, set up the decorators
                    if first_time:
                        # add a decorator function for when that hat is used
                        @self.decorator.hat(hat._index)
                        def callback(event, vjoy):
                            # Map the physical hat input to the virtual one
                            # (perhaps later: Filtering algorithm? Right now, 1:1)
                            vjoy[self.vjoy_id].hat(event.identifier).direction = event.value

    def start_button_monitoring(self, btn_id):
        self.concurrent_presses.add(btn_id)

    def end_button_monitoring(self, btn_id):
        self.concurrent_presses.discard(btn_id)
        if len(self.concurrent_presses) <= 0:
            self.logger.log_ghost()

    # checks total number of buttons pressed, every time a new button is pressed within the configured timespan
    # and maps the physical device to the virtual device if NOT a ghost input
    def filter_the_button(self, event, vjoy, joy):

        # get the current state (after this much delay)
        still_pressed = joy[event.device_guid].button(event.identifier).is_pressed

        # if we're filtering:
        # if <threshold> or more buttons (including this callback's triggered button) are pressed,
        # and this button is no longer still pressed, this is likely a ghost input
        is_ghost = self.button_filtering and len(self.concurrent_presses) >= self.button_threshold and not still_pressed

        # if this was initially a press
        if event.is_pressed:
            # if this is a ghost input, log it
            if is_ghost:
                self.logger.evaluate_ghost(event.identifier)
            else:
                # otherwise, update the virtual joystick
                self.trigger_the_button(event, vjoy, still_pressed)

            # log a legitimate press and end monitoring
            if not is_ghost and still_pressed:
                self.logger.log_legitimate(event)
                self.end_button_monitoring(event.identifier)
            else:
                # otherwise, if it could still be part of a ghost press, wait the rest of the delay, then end
                # enough time will have passed that this press should no longer be used to determine a Ghost Input
                defer(self.button_timespan[1], self.end_button_monitoring, event.identifier)
        else:
            # always process every release
            self.trigger_the_button(event, vjoy, still_pressed)

    # update the virtual joystick
    def trigger_the_button(self, event, vjoy, new_value):
        the_button = vjoy[self.vjoy_id].button(event.identifier)
        the_button.is_pressed = new_value

        # execute any decorated callbacks from custom code that match this key
        # via @filtered_device.on_virtual_press(id)
        if event.is_pressed and event.identifier in self.button_callbacks['press']:
            # allowing for multiple callbacks per button
            for callback in self.button_callbacks['press'][event.identifier]:
                callback()
        # via @filtered_device.on_virtual_release(id)
        if not event.is_pressed and event.identifier in self.button_callbacks['release']:
            # allowing for multiple callbacks per button
            for callback in self.button_callbacks['release'][event.identifier]:
                callback()

    # decorator for registering custom callbacks when a virtual button was successfully pressed
    def on_virtual_press(self, btn):
        def wrap(callback=None):
            # add the decorated function into the callbacks for this button id
            if callback:
                self.button_callbacks['press'][btn].append(callback)

        return wrap

    # decorator for registering custom callbacks when a virtual button was successfully released
    def on_virtual_release(self, btn):
        def wrap(callback=None):
            # add the decorated function into the callbacks for this button id
            if callback:
                self.button_callbacks['release'][btn].append(callback)

        return wrap


# Functions

# execute function after delay (via threading)
def defer(time, func, *args, **kwargs):
    timer = threading.Timer(time, func, args, kwargs)
    timer.start()


# write to log (optionally as ~two columns)
def log(str1, str2="", width=80):
    gremlin.util.log(((str(str1) + " ").ljust(width, ".") + " " + str(str2)) if str2 else str(str1))


# update all virtual devices with the current status from the physical devices
def initialize_inputs():
    global filtered_devices
    for id, filtered_device in filtered_devices.items():
        filtered_device.initialize_inputs()


# switch modes and update all input states (prevents latched buttons during a mode switch)
def switch_mode(mode=None):
    if mode is None:
        gremlin.control_action.switch_to_previous_mode()
    else:
        gremlin.control_action.switch_mode(mode)
    initialize_inputs()


# Plugin UI Configuration
ui_button_remapping = BoolVariable("Enable Button Remapping?",
                                   "Actively remap button input? Required for filtering ghost inputs", True)
ui_button_filtering = BoolVariable("  -  Enable Button Filtering?", "Actively filter ghost input?", True)
ui_button_threshold = IntegerVariable("          Button Filtering Sensitivity",
                                      "How many *buttons* pressed at once (within a timespan) constitute a Ghost Input (on a single device)? Default: 2",
                                      2, 0, 100)
ui_button_timespan = IntegerVariable("          Button Filtering Strength",
                                     "Determines the timespan after a button press before checking for ghost input? Default Strength: 6",
                                     6, 1, 20)
ui_axis_remapping = BoolVariable("Enable Axis Remapping?",
                                 "Actively remap axes? Disable if remapping them through JG GUI", True)
ui_axis_curve = BoolVariable("  -  Smooth Response Curve?",
                             "Adds an S curve to the vjoy output, otherwise linear",
                             True)
ui_hat_remapping = BoolVariable("Enable Hat Remapping?",
                                "Actively remap hats? Disable if remapping them through JG GUI", True)
ui_logging_enabled = BoolVariable("Enable Logging?", "Output useful debug info to log", True)
ui_logging_is_verbose = BoolVariable("  -  Verbose Logging",
                                     "Log every legitimate button press (instead of just Ghost Inputs)",
                                     False)
ui_logging_summary_key = StringVariable("  -  Generate a Summary with Key",
                                        "Which keyboard key to press to get a Ghost Input summary breakdown in the log?",
                                        "f8")

# Grab general user config
button_remapping_enabled = bool(
    ui_button_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
button_filtering = bool(ui_button_filtering.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
button_timespan = ui_button_timespan.value
button_threshold = ui_button_threshold.value

axis_remapping_enabled = bool(ui_axis_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
axis_curve = bool(ui_axis_curve.value)  # joystick gremlin has an issue with BoolVariable persistence(?)

hat_remapping_enabled = bool(ui_hat_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)

logging_enabled = bool(ui_logging_enabled.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
logging_is_verbose = bool(ui_logging_is_verbose.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
logging_summary_key = ui_logging_summary_key.value

vjoy_devices = sorted(gremlin.joystick_handling.vjoy_devices(), key=lambda x: x.vjoy_id)
filtered_devices = {}
nicknames = defaultdict(list)

log("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
log("Ghost Input Filter", "Script starting")

# Output VJoy configuration to log, to show Windows (GUIDs) <-> Joystick Gremlin (Vjoy IDs) assignment
log("The following VJoy devices were detected:")
for vjoy in vjoy_devices:
    log("   VJoy #" + str(vjoy.vjoy_id), vjoy.device_guid)

# Loop through vjoy devices
for vjoy in vjoy_devices:
    vjoy_id = str(vjoy.vjoy_id)

    # create config for each one (because JG won't create the UI elements if simply stored in a list/dict.. must be top-level variables?)
    vars()["ui_mode_" + vjoy_id] = (ModeVariable("VJoy #" + vjoy_id, "The mode to apply this filtering to"))
    vars()["ui_physical_device_" + vjoy_id] = PhysicalInputVariable("  -  Physical Device to map to VJoy #" + vjoy_id,
                                                                    "Assign the physical device that should map to this device in the selected mode",
                                                                    is_optional=True)
    # if we have a physical device set for this remapping
    if vars()["ui_physical_device_" + vjoy_id].value is not None:
        # grab config for each one
        mode = vars()["ui_mode_" + vjoy_id].value
        device_guid = str(vars()["ui_physical_device_" + vjoy_id].value['device_id'])

        # create physical device proxy
        device = (gremlin.input_devices.JoystickProxy())[gremlin.profile.parse_guid(device_guid)]

        # generate a unique but shorter name for this device
        name = device._info.name
        nickname = "Stick" if "stick" in name.lower() else "Throttle" if "throttle" in name.lower() else name
        nickname = nickname if nickname not in nicknames or device_guid in nicknames[
            nickname] else nickname + " " + str(len(nicknames[nickname]) + 1)
        nicknames[nickname].append(device_guid)

        # create a filtered device for each vjoy device that is getting remapped
        # Initialize filtered device (which creates decorators to listen for and filter input)
        filtered_device = FilteredDevice(
            device,
            nickname,
            int(vjoy_id),
            mode,
            button_remapping_enabled,
            button_filtering,
            button_timespan,
            button_threshold,
            axis_remapping_enabled,
            axis_curve,
            hat_remapping_enabled,
            logging_enabled,
            logging_is_verbose,
            logging_summary_key
        )
        filtered_devices[int(vjoy_id)] = filtered_device

        # Custom Callbacks
        # Add any custom callback functions here, for events you want to happen IF a virtual input is successfully pressed

        # Example:
        # if name == "Stick":
        #     @filtered_device.on_virtual_press(<button id>)
        #     def custom_callback():
        #         # do something here

        #     @filtered_device.on_virtual_release(<button id>)
        #     def custom_callback():
        #         # do something here

        pass
