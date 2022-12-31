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

# Plugin UI Configuration
ui_mode = ModeVariable("*** Apply Filtering to", "The mode to apply this filtering to")
ui_device_name = StringVariable("Physical Device Label", "What to call this device in the log?", "Stick")
ui_physical_guid = StringVariable("  -  Physical Device GUID", "Copy and paste from Tools > Device Information", "")
ui_virtual_guid = StringVariable("  -  Virtual Device GUID", "Copy and paste from Tools > Device Information", "")
ui_button_remapping = BoolVariable("Button Remapping Enabled?",
                                   "Actively remap button input? Required for filtering ghost inputs", True)
ui_button_filtering = BoolVariable("  -  Button Filtering Enabled?", "Actively filter ghost input?", True)
ui_button_threshold = IntegerVariable("       -  Button Limit Threshold",
                                      "How many *buttons* pressed at once (within the Monitoring Timespan) constitute a Ghost Input (on a single device)? Default: 2",
                                      2, 0, 100)
ui_button_timespan = IntegerVariable("       -  Button Monitoring Timespan",
                                     "How many ticks (16.66ms) to wait after a button press before checking for ghost input? Default: 5",
                                     5, 1, 20)
ui_axis_remapping = BoolVariable("Axis Remapping Enabled?",
                                 "Actively remap axes? Disable if remapping them through JG GUI", True)
ui_axis_curve = BoolVariable("  -  Smooth Response Curve?",
                             "Adds an S curve to the vjoy output, otherwise linear",
                             True)
ui_hat_remapping = BoolVariable("Hat Remapping Enabled?",
                                "Actively remap hats? Disable if remapping them through JG GUI", True)
ui_logging_enabled = BoolVariable("Enable Logging?", "Output useful debug info to log", True)
ui_logging_is_verbose = BoolVariable("  -  Verbose Logging",
                                     "Log every legitimate button press (instead of just Ghost Inputs)",
                                     False)
ui_logging_summary_key = StringVariable("  -  Generate a Summary with Key",
                                        "Which keyboard key to press to get a Ghost Input summary breakdown in the log?",
                                        "f8")


class Debugger:
    def __init__(self, mode, enabled, is_verbose, summary_key):
        self.mode = mode
        self.enabled = enabled
        self.is_verbose = is_verbose
        self.summary_key = summary_key
        self.summary = {
            'period': {
                'ghost': 10,
                'legitimate': 100
            },
            'recent': False,
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
        @gremlin.input_devices.keyboard(self.summary_key, self.mode)
        def summary_callback(event):
            if event.is_pressed:
                self.summarize()

    def ready(self, device):

        if not self.enabled:
            return

        # output general setup info
        log("/////////////////////////////////////////////////////////////////////////////////////////////////////////////////")
        log("Ghost Input Filtering", "on Profile [" + device.mode + "]")
        log("  for Physical Device \"" + device.name + "\"", str(device.physical_guid))
        log("  mapping to Virtual Device " + str(device.vjoy_id), str(device.virtual_guid))
        if device.button_filtering:
            log("   ... Button Filtering enabled")
        if self.is_verbose:
            log("   ... Verbose logging enabled")

    def evaluate_ghost(self, device, button):

        if not self.enabled:
            return

        # on press, increment the counters
        self.counts['total_blocked'] += 1
        self.counts['by_button'][button] += 1
        self.counts['by_simultaneity'][len(device.concurrent_presses)] += 1.0 / len(device.concurrent_presses)
        self.counts['by_combination'][str(sorted(device.concurrent_presses))] += 1.0 / len(device.concurrent_presses)

        combination = device.concurrent_presses

        # if this set is the same size or bigger, save it as latest
        if len(combination) >= len(self.last_combination):
            self.last_combination = set(combination)

    def log_ghost(self, device):
        # on release, log the highest ghosting event
        if len(self.last_combination) > 0:
            log("> GHOST INPUTS blocked! [" + device.mode + "] " + device.name + " pressed " + str(
                len(self.last_combination)) + " buttons at once",
                str(self.last_combination), 90)
            self.last_combination = set()

    def legitimate(self, device, event):

        if not self.enabled:
            return

        # increment counters
        self.counts['total_allowed'] += 1
        if self.is_verbose:
            log("USER pressed: " + device.name + " button " + str(event.identifier))

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

        global filtered_device

        # output a summary
        log("//////////////////////////////////////////////////////////////////")
        log("   Summary for \"" + filtered_device.name + "\"", "on Profile [" + filtered_device.mode + "]")
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
                 physical_guid, virtual_guid, name, mode,
                 # buttons
                 button_remapping, button_filtering, button_timespan, button_threshold,
                 # axes
                 axis_remapping, axis_curve,
                 # hats
                 hat_remapping
                 ):

        self.name = name
        self.mode = mode
        self.physical_guid = physical_guid
        self.virtual_guid = virtual_guid
        self.vjoy_id = gremlin.joystick_handling.vjoy_id_from_guid(gremlin.profile.parse_guid(str(virtual_guid)))
        self.physical_device = (gremlin.input_devices.JoystickProxy())[gremlin.profile.parse_guid(self.physical_guid)]
        self.virtual_device = (gremlin.joystick_handling.VJoyProxy())[self.vjoy_id]
        self.tick_len = .01666

        self.button_remapping = button_remapping
        self.button_filtering = button_filtering
        self.button_timespan = [math.ceil(float(button_timespan) / 2) * self.tick_len,
                                math.floor(float(button_timespan) / 2) * self.tick_len] if button_filtering else [0, 0]
        self.button_threshold = button_threshold
        self.button_callbacks = {'press': defaultdict(list), 'release': defaultdict(list)}

        self.axis_remapping = axis_remapping
        self.axis_curve = axis_curve

        self.hat_remapping = hat_remapping

        self.concurrent_presses = set()

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        # for each button on the device
        if self.button_remapping:
            self.initialize_buttons(True)

        # for each axis on the device
        if self.axis_remapping:
            self.initialize_axes(True)

        # for each hat on the device
        if self.hat_remapping:
            self.initialize_hats(True)

        # Log that device is ready
        debugger.ready(self)

    def initialize_buttons(self, first_time=False):
        for btn in self.physical_device._buttons:
            if btn:
                # initialize value
                try:
                    self.virtual_device.button(btn._index).is_pressed = self.physical_device.button(
                        btn._index).is_pressed
                except:
                    debugger.log("Error initializing button " + str(btn._index) + " value")
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
                    debugger.log("Error initializing axis " + str(aid) + " value")
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
        for hat in self.physical_device._hats:
            if hat:
                # initialize value
                try:
                    self.virtual_device.hat(hat._index).direction = self.physical_device.hat(hat._index).direction
                except:
                    debugger.log("Error initializing hat " + str(hat._index) + " value")
                else:
                    # if this is the first time, set up the decorators
                    if first_time:
                        # add a decorator function for when that hat is used
                        @self.decorator.hat(hat._index)
                        def callback(event, vjoy):
                            # Map the physical hat input to the virtual one
                            # (perhaps later: Filtering algorithm? Right now, 1:1)
                            vjoy[self.vjoy_id].hat(event.identifier).direction = event.value

    def get_count(self, input):
        joy_proxy = gremlin.input_devices.JoystickProxy()
        dev = joy_proxy[gremlin.profile.parse_guid(self.physical_guid)]
        return len(dev._buttons) if input == "button" else len(dev._axis) if input == "axis" else len(
            dev._hats) if input == "hat" else 0

    def start_button_monitoring(self, btn_id):
        self.concurrent_presses.add(btn_id)

    def end_button_monitoring(self, btn_id):
        global debugger
        self.concurrent_presses.discard(btn_id)
        if len(self.concurrent_presses) <= 0:
            debugger.log_ghost(self)

    # checks total number of buttons pressed, every time a new button is pressed within the configured timespan
    # and maps the physical device to the virtual device if NOT a ghost input
    def filter_the_button(self, event, vjoy, joy):

        # get the current state (after this much delay)
        still_pressed = joy[event.device_guid].button(event.identifier).is_pressed

        # if we're filtering:
        # if <threshold> or more buttons (including this callback's triggered button) are pressed,
        # and this button is no longer still pressed, this is likely a ghost input
        is_ghost = self.button_filtering and len(self.concurrent_presses) >= self.button_threshold and not still_pressed

        global debugger

        # if this was initially a press
        if event.is_pressed:
            # if this is a ghost input, log it
            if is_ghost:
                debugger.evaluate_ghost(self, event.identifier)
            else:
                # otherwise, update the virtual joystick
                self.trigger_the_button(event, vjoy, still_pressed)

            # log a legitimate press and end monitoring
            if not is_ghost and still_pressed:
                debugger.legitimate(self, event)
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


# helper functions

def defer(time, func, *args, **kwargs):
    timer = threading.Timer(time, func, args, kwargs)
    timer.start()


# write to log (optionally as ~two columns)
def log(str1, str2="", width=50):
    gremlin.util.log(((str1 + " ").ljust(width, ".") + " " + str2) if str2 else str1)


# grab user configuration
name = ui_device_name.value
mode = ui_mode.value
physical_guid = ui_physical_guid.value
virtual_guid = ui_virtual_guid.value

button_remapping = bool(ui_button_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
button_filtering = bool(ui_button_filtering.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
button_timespan = ui_button_timespan.value
button_threshold = ui_button_threshold.value

axis_remapping = bool(ui_axis_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
axis_curve = bool(ui_axis_curve.value)  # joystick gremlin has an issue with BoolVariable persistence(?)

hat_remapping = bool(ui_hat_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)

logging_enabled = bool(ui_logging_enabled.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
logging_is_verbose = bool(ui_logging_is_verbose.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
logging_summary_key = ui_logging_summary_key.value

filtered_device = None

if physical_guid and virtual_guid:
    # Initialize debugging logging
    debugger = Debugger(mode, logging_enabled, logging_is_verbose, logging_summary_key)
    # Initialize filtered device (which creates decorators to listen for and filter input)
    filtered_device = FilteredDevice(
        physical_guid,
        virtual_guid,
        name,
        mode,
        button_remapping,
        button_filtering,
        button_timespan,
        button_threshold,
        axis_remapping,
        axis_curve,
        hat_remapping
    )

else:
    log("Couldn't initialize filtered_device")

# Custom Callbacks
if filtered_device:
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