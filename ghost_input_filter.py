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
            'by_simultaneity': defaultdict(int)
        }

        # log a summary every time summary button is pressed (user configurable)
        @gremlin.input_devices.keyboard(self.summary_key, self.mode)
        def summary_callback(event):
            if event.is_pressed:
                self.summarize()

    def update(self):
        self.counts['total'] = self.counts['total_blocked'] + self.counts['total_allowed']
        self.summary['percentage'] = (self.counts['total_blocked'] / self.counts['total']) * 100 if self.counts[
                                                                                                        'total'] > 0 else 0.0
        self.summary['elapsed_time'] = time.mktime(time.localtime()) - time.mktime(self.summary['start_time'])
        self.summary['per_minute'] = (self.counts['total_blocked'] / self.summary['elapsed_time']) * 60
        self.summary['per_hour'] = self.summary['per_minute'] * 60

    def log(self, msg, **args):

        if not self.enabled:
            return

        if msg is "ready":
            # output general setup info
            log("/////////////////////////////////////////////////////////////////////////////////////////////////////////////////")
            log("Ghost Input Filtering", "on Profile [" + args['device'].mode + "]")
            log("  for Physical Device \"" + args['device'].name + "\"", str(args['device'].physical_guid))
            log("  mapping to Virtual Device " + str(args['device'].vjoy_id), str(args['device'].virtual_guid))
            if args['device'].button_filtering:
                log("   ... Button Filtering enabled")
            if self.is_verbose:
                log("   ... Verbose logging enabled")

        elif msg is "ghost":
            # increment counters
            self.counts['total_blocked'] += 1
            self.counts['by_button'][args['event'].identifier] += 1
            self.counts['by_simultaneity'][args['device'].concurrent_presses] += 1
            # log ghost input
            log("> GHOST INPUT blocked! [" + args['device'].mode + "] " + args['device'].name + " button " + str(
                args['event'].identifier) + " was pressed (" + str(
                args['device'].concurrent_presses) + " buttons at once)")

        elif msg is "legitimate":
            # increment counters
            self.counts['total_allowed'] += 1
            if self.is_verbose:
                log("USER pressed: " + args['device'].name + " button " + str(args['event'].identifier))

        elif msg is "summary":
            # output a summary
            log("//////////////////////////////////////////////////////////////////")
            log("   Summary for \"" + args['device'].name + "\"", "on Profile [" + args['device'].mode + "]")
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
                    log("   |            (" + str(simul) + " at once)", str(cnt))
            self.summary['recent'] = False

        else:
            # output the message
            log(msg)

    def summarize(self):
        if not self.summary['recent'] and self.enabled:
            global filtered_device
            self.summary['recent'] = True
            self.update()
            self.log("summary", device=filtered_device)


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
        self.button_callbacks = defaultdict(list)

        self.axis_remapping = axis_remapping
        self.axis_curve = axis_curve

        self.hat_remapping = hat_remapping

        self.concurrent_presses = 0

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        # for each button on the device
        if self.button_remapping:
            for btn in self.physical_device._buttons:
                if btn:
                    # initialize value
                    self.virtual_device.button(btn._index).is_pressed = self.physical_device.button(
                        btn._index).is_pressed

                    # add a decorator function for when that button is pressed
                    @self.decorator.button(btn._index)
                    # pass that info to the function that will check other button presses
                    def callback(event, vjoy, joy):
                        # increment total buttons counter for this device (if this is a press)
                        if event.is_pressed:
                            self.start_button_monitoring()

                        # wait the first half of the delay timespan (set number of ticks), then check for ghost inputs
                        defer(self.button_timespan[0], self.filter_the_button, [event, vjoy, joy])

        # for each axis on the device
        if self.axis_remapping:
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
                    value = self.physical_device.axis(aid).value
                    self.virtual_device.axis(aid).value = curve(value) if self.axis_curve else value

                    # add a decorator function for when that axis is moved
                    @self.decorator.axis(aid)
                    def callback(event, vjoy):
                        # Map the physical axis input to the virtual one
                        vjoy[self.vjoy_id].axis(event.identifier).value = curve(
                            event.value) if self.axis_curve else event.value

        # for each hat on the device
        if self.hat_remapping:
            for hat in self.physical_device._hats:
                if hat:
                    # initialize value
                    self.virtual_device.hat(hat._index).direction = self.physical_device.hat(hat._index).direction

                    # add a decorator function for when that hat is used
                    @self.decorator.hat(hat._index)
                    def callback(event, vjoy):
                        # Map the physical hat input to the virtual one
                        # (perhaps later: Filtering algorithm? Right now, 1:1)
                        vjoy[self.vjoy_id].hat(event.identifier).direction = event.value

        # Log that device is ready
        debugger.log("ready", device=self)

    def get_count(self, input):
        joy_proxy = gremlin.input_devices.JoystickProxy()
        dev = joy_proxy[gremlin.profile.parse_guid(self.physical_guid)]
        return len(dev._buttons) if input is "button" else len(dev._axis) if input is "axis" else len(
            dev._hats) if input is "hat" else 0

    def start_button_monitoring(self):
        self.concurrent_presses += 1

    def end_button_monitoring(self):
        self.concurrent_presses -= 1

    # checks total number of buttons pressed, every time a new button is pressed within the configured timespan
    # and maps the physical device to the virtual device if NOT a ghost input
    def filter_the_button(self, event, vjoy, joy):

        # if <threshold> or more buttons (including this callback's triggered button) are pressed, this is likely a ghost input
        is_ghost = self.concurrent_presses >= self.button_threshold

        global debugger

        # if this is a ghost input on key press (not release)
        if event.is_pressed and is_ghost and self.button_filtering:
            # log it
            debugger.log("ghost", event=event, device=self)
        else:
            # otherwise, get the current state (after this much delay)
            still_pressed = joy[event.device_guid].button(event.identifier).is_pressed

            # update the virtual joystick (other functions could decorate this and execute here)
            self.trigger_the_button(event, vjoy, still_pressed)

            # log legitimate press
            if still_pressed:
                debugger.log("legitimate", event=event, device=self)

        # after half the delay and evaluation, delay the next half, then decrement the pressed counter (if this was a press and not a release)
        # enough time will have passed that this callback's button should no longer be used to determine a Ghost Input
        if event.is_pressed:
            defer(self.button_timespan[1], self.end_button_monitoring)

    # update the virtual joystick
    def trigger_the_button(self, event, vjoy, new_value):
        try:
            vjoy[self.vjoy_id].button(event.identifier).is_pressed = new_value
        except:
            debugger.log(
                "Error trying to update vjoy[" + str(self.vjoy_id) + "].button(" + str(
                    event.identifier) + ") state  [Device \"" + self.name + "\" on Profile \"" + self.mode + "\"]")
        # if this was a press
        if event.is_pressed:
            # execute any decorated callbacks from custom code (via @filtered_device.on_virtual_button(id) )
            for key, funcs in self.button_callbacks.items():
                # that match this button id
                if key is event.identifier:
                    # allowing for multiple callbacks per button
                    for func in funcs:
                        func()

    # decorator for registering custom callbacks when a virtual button was successfully pressed
    def on_virtual_button(self, btn):
        def wrap(callback):
            # add the decorated function into the callbacks for this button id
            self.button_callbacks[btn].append(callback)
        return wrap


# helper functions

def defer(time, func, args=[]):
    timer = threading.Timer(time, func, args)
    timer.start()


# write to log (optionally as ~two columns)
def log(str1, str2=""):
    gremlin.util.log(((str1 + " ").ljust(50, ".") + " " + str2) if str2 else str1)


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
