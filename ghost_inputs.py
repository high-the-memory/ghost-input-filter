#python imports
import threading
import math
import time
from collections import defaultdict
#gremlin (user plugin) imports
import gremlin
import gremlin.util
#gremlin (developer) improts
from gremlin.joystick_handling import vjoy_id_from_guid
from gremlin.user_plugin import *
import uuid

#helper functions

#write to log (optionally as two columns)
def log(str1, str2=""):
    gremlin.util.log(((str1 + " ").ljust(50,".") + " " + str2) if str2 else str1)

# (copied from JoystickGremlin-develop/gremlin/util.py since they don't seem to be exposed for user_plugins on production)
def parse_guid(value: str) -> dill.GUID:
    """Reads a string GUID representation into the internal data format.

    This transforms a GUID of the form {B4CA5720-11D0-11E9-8002-444553540000}
    into the underlying raw and exposed objects used within Gremlin.

    Args:
        value: the string representation of the GUID

    Returns:
        dill.GUID object representing the provided value
    """
    try:
        tmp = uuid.UUID(value)
        raw_guid = dill._GUID()
        raw_guid.Data1 = int.from_bytes(tmp.bytes[0:4], "big")
        raw_guid.Data2 = int.from_bytes(tmp.bytes[4:6], "big")
        raw_guid.Data3 = int.from_bytes(tmp.bytes[6:8], "big")
        for i in range(8):
            raw_guid.Data4[i] = tmp.bytes[8 + i]

        return dill.GUID(raw_guid)
    except (ValueError, AttributeError) as _:
        log(f"Failed parsing GUID from value '{value}'")



# Plugin UI Configuration
ui_mode = ModeVariable("Apply Filtering to", "The mode to apply this filtering to")
ui_is_verbose = BoolVariable("Verbose Logging", "Log every legitimate button press (instead of just Ghost Inputs)",
                             False)
ui_device_name = StringVariable("Physical Device Label", "What to call this device in the log?", "Stick")
ui_physical_guid = StringVariable("Physical Device GUID", "Copy and paste from Tools > Device Information", "")
ui_virtual_guid = StringVariable("Virtual Device GUID", "Copy and paste from Tools > Device Information", "")
ui_button_filtering = BoolVariable("Button Filtering Enabled?", "Actively filter ghost input?", True)
ui_button_threshold = IntegerVariable("Button Limit Threshold",
                                      "How many *buttons* pressed at once (within the Monitoring Timespan) constitute a Ghost Input (on a single device)? Default: 2",
                                      2, 0, 100)
ui_button_timespan = IntegerVariable("Button Monitoring Timespan",
                                     "How many ticks (16.66ms) to wait after a button press before checking for ghost input? Default: 5",
                                     5, 1, 20)
ui_summary_key = StringVariable("Generate a Summary with Key", "Which keyboard key to press to get a Ghost Input summary breakdown in the log?","f8")



class Debugger:
    def __init__(self, mode, is_verbose, summary_key):
        self.mode = mode
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
            log("   Summary for \"" + args['device'].name + "\"", "on Profile ["+args['device'].mode + "]")
            log("   |      Total Inputs Allowed", str(self.counts['total_allowed']))
            log("   |      Total Ghost Inputs Blocked", str(self.counts['total_blocked']))
            log("   | ")
            log("   |      Elapsed Time", str(self.summary['elapsed_time']) + " seconds" + "   (" + str(round(self.summary['elapsed_time'] / 60, 1)) + " minutes)    (" + str(round(self.summary['elapsed_time'] / 3600, 1)) + " hours)")
            log("   |      Ghost Input %", str(round(self.summary['percentage'], 3)) + "%")
            log("   |      Ghost Input rate", str(round(self.summary['per_minute'], 3)) + "/min   (" + str(
                round(self.summary['per_hour'])) + "/hr)")
            if self.counts['total_blocked'] > 0:
                log("   | ")
                log("   |      By Button")
                #output how many times each button was ghosted, starting with the most common one
                for btn, cnt in sorted(self.counts['by_button'].items(), key=lambda item: item[1], reverse=True):
                    log("   |            (Joy " + str(btn) + ")", str(cnt))
                log("   |      By Simultaneity")
                #output how many buttons were pressed at the same time, starting with the most common number
                for simul, cnt in sorted(self.counts['by_simultaneity'].items(), key=lambda item: item[1], reverse=True):
                    log("   |            (" + str(simul) + " at once)", str(cnt))
            self.summary['recent'] = False

        else:
            # output the message
            log(msg)

    def summarize(self):
        if not self.summary['recent']:
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
                 button_filtering, button_timespan, button_threshold,
                 # variables
                 tick_len=.01666, max_buttons=36  # , max_axes = 8
                 ):

        self.name = name
        self.mode = mode
        self.physical_guid = physical_guid
        self.virtual_guid = virtual_guid
        self.vjoy_id = vjoy_id_from_guid(parse_guid(str(virtual_guid)))
        self.tick_len = tick_len

        self.button_filtering = button_filtering
        self.button_timespan = [math.ceil(float(button_timespan) / 2) * self.tick_len,
                                math.floor(float(button_timespan) / 2) * self.tick_len] if button_filtering else [0, 0]
        self.button_threshold = button_threshold
        self.max_buttons = max_buttons

        self.concurrent_presses = 0
        self.block_count = 0

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        # for each button on the device
        for i in range(1, self.max_buttons + 1):
            # add a decorator function for when that button is pressed
            @self.decorator.button(i)
            # pass that info to the function that will check other button presses
            def callback(event, vjoy, joy):
                # increment total buttons counter for this device (if this is a press)
                if event.is_pressed:
                    self.start_monitoring()

                # wait the first half of the delay timespan (set number of ticks), then check for ghost inputs
                defer(self.button_timespan[0], self.filter_the_button, [event, vjoy, joy])

        # Log that device is ready
        debugger.log("ready", device=self)

    def start_monitoring(self):
        self.concurrent_presses += 1

    def end_monitoring(self):
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

            # log a summary every n logs
            if debugger.counts['total_blocked'] % debugger.summary['period']['ghost'] is 0:
                defer(5, debugger.summarize, [self])
        else:
            # otherwise, get the current state (after this much delay)
            still_pressed = joy[event.device_guid].button(event.identifier).is_pressed
            # and update the virtual joystick
            try:
                vjoy[self.vjoy_id].button(event.identifier).is_pressed = still_pressed
            except:
                debugger.log(
                    "Error trying to update vjoy[" + str(self.vjoy_id) + "].button(" + str(event.identifier) + ") state  [Device \""+ self.name +"\" on Profile \"" + self.mode + "\"]")
            # log legitimate press
            if still_pressed:
                debugger.log("legitimate", event=event, device=self)

                # log a summary every n logs
                if debugger.counts['total_allowed'] % debugger.summary['period']['legitimate'] is 0:
                    defer(5, debugger.summarize, [self])

        # after half the delay and evaluation, delay the next half, then decrement the pressed counter (if this was a press and not a release)
        # enough time will have passed that this callback's button should no longer be used to determine a Ghost Input
        if event.is_pressed:
            defer(self.button_timespan[1], self.end_monitoring)


# helper functions
def defer(time, func, args=[]):
    timer = threading.Timer(time, func, args)
    timer.start()


# grab user configuration
name = ui_device_name.value
mode = ui_mode.value
physical_guid = ui_physical_guid.value
virtual_guid = ui_virtual_guid.value
is_verbose = bool(ui_is_verbose.value)  # joystick gremlin has an issue with BoolVariable persistance(?)
button_filtering = bool(ui_button_filtering.value)  # joystick gremlin has an issue with BoolVariable persistance(?)
button_timespan = ui_button_timespan.value
button_threshold = ui_button_threshold.value
summary_key = ui_summary_key.value

if physical_guid and virtual_guid:
    # Initialize debugging logging
    debugger = Debugger(mode, is_verbose, summary_key)
    # Initialize filtered device (which creates decorators to listen for and filter input)
    filtered_device = FilteredDevice(
        physical_guid,
        virtual_guid,
        name,
        mode,
        button_filtering,
        button_timespan,
        button_threshold
    )
