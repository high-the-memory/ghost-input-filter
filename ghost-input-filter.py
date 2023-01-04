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
import gremlin.event_handler
from gremlin.spline import CubicSpline


# Classes

class Logger:
    def __init__(self, device, enabled, is_debug, summary_key):

        self.device = device

        self.enabled = enabled
        self.is_debug = is_debug
        self.summary_key = summary_key
        self.summary = {
            'percentage': 0.0,
            'start_time': time.localtime(),
            'elapsed_time': 0.0,
            'rate': 0.0
        }
        self.counts = {
            'total': 0,
            'allowed': {
                'total': 0,
                'by_button': defaultdict(int),
                'by_simultaneity': defaultdict(int),
                'by_combination': defaultdict(int)
            },
            'blocked': {
                'total': 0,
                'by_button': defaultdict(int),
                'by_simultaneity': defaultdict(int),
                'by_combination': defaultdict(int)
            }
        }
        self.events = {
            'in_progress': {},
            'complete': {},
            'archive': {}
        }
        self.delta = {'previous': False, 'string': "", 'difference': 0, 'threshold': .5, 'pips': 0, 'max_pips': 5}

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
        log("  Remapping [" + self.device.mode + "] " + self.device.name, str(self.device.physical_guid))
        log("     to VJoy #" + str(self.device.vjoy_id), str(self.device.virtual_guid))
        if self.device.button_filtering:
            log("        ... Button Filtering enabled")
        if self.is_debug:
            log("        ... Verbose logging enabled")

    def ready(self):

        if not self.enabled:
            return

        log("          [" + self.device.mode + "] " + self.device.name + " to VJoy #" + str(
            self.device.vjoy_id) + " is Ready!")

    def start_tracking(self, btn_id):
        self.device.concurrent_presses.add(btn_id)

    def update_tracking(self, is_ghost, button, still_pressed):

        if not self.enabled:
            return

        concurrent_presses = set(self.device.concurrent_presses)

        # determine event type
        event_type = "blocked" if is_ghost else "allowed"

        # on press, increment the counters
        self.counts[event_type]['total'] += 1
        self.counts[event_type]['by_button'][button] += 1
        self.counts[event_type]['by_simultaneity'][len(concurrent_presses)] += 1.0 / len(concurrent_presses)
        self.counts[event_type]['by_combination'][str(sorted(concurrent_presses))] += 1.0 / len(concurrent_presses)

        # bail if not is_debug (don't need to track legitimate presses)
        if not is_ghost and not self.is_debug:
            return

        # build the event
        current_time = time.time()
        the_event = {
            button: [
                round(current_time, 3), "long" if still_pressed else "short", "ghost" if is_ghost else "legitimate"
            ]
        }
        the_key = current_time

        # search through currently ongoing events that have been logged
        for key, event in list(self.events['in_progress'].items()):
            # if this combination is found in the current ghosting/legitimate events
            if concurrent_presses.intersection(set(event.keys())):
                # merge the current event with this saved event (keeping the key of the earliest matching event)
                the_key = key
                the_event.update(event)
                break

        # update the extant event with the larger set or create a new event entry
        self.events['in_progress'].update({the_key: the_event})

    def end_tracking(self, btn_id):
        self.device.concurrent_presses.discard(btn_id)

        # if this is the end of the ghosting event, flush the tracking log
        if len(self.device.concurrent_presses) <= 0:
            self.finalize_tracking()

    # when no more concurrent presses are detected, move all current events to Complete
    def finalize_tracking(self):
        # for each in-progress event
        for key, event in list(self.events['in_progress'].items()):
            # mark as complete
            self.events['complete'].update({key: event})
            # and remove from in_progress
            del self.events['in_progress'][key]

        # output appropriate events to the log
        self.flush_tracked_events("allowed", "blocked")

    # output all registered ghosting/legitimate events and flush the list
    def flush_tracked_events(self, *args, state="complete"):
        for event_type_to_flush in args:
            if self.events[state]:
                # for each [state] event (complete, archive, etc)
                for key, event in list(self.events[state].items()):
                    # if any button in the event was blocked, this is a ghosting event
                    event_type = "blocked" if any("ghost" in status for status in event.values()) else "allowed"

                    # for each event, generate a message based on the event_type
                    if event_type_to_flush is "blocked":
                        msg = "> GHOST INPUTS blocked!"
                    elif event_type_to_flush is "allowed" and self.is_debug:
                        if state is "archive":
                            msg = "   |            At " + str(
                                time.strftime('%H:%M:%S', time.localtime(key))) + " ..... "
                        else:
                            msg = "> USER PRESS allowed:"
                    else:
                        msg = False
                    if msg and event_type == event_type_to_flush:
                        # build human-readable button breakdown string
                        buttons = []
                        for button, info in event.items():
                            buttons.append(
                                "Joy " + str(button) + ": " + str(info[1]) + " " + str(info[2]) + " press " + (
                                    "blocked" if info[2] == "ghost" else "allowed") + (
                                    " @ " + str(info[0]) if self.is_debug else ""))
                        breakdown = "(" + (", ".join(buttons)) + ")"

                        # if we're in debug mode
                        if self.is_debug:
                            # compute difference to previous entry (to flag possible missed ghost inputs)
                            self.compute_delta(key)
                            if state == "complete":
                                # save all completed events into [archive]
                                self.events['archive'].update({key: event})

                        # log the event
                        description = " [" + self.device.mode + "] " + self.device.name + " pressed " + str(
                            len(event)) + " buttons at once"
                        self.log(msg + description, breakdown + self.delta['string'], 90)

                        # delete the entry
                        del self.events[state][key]

    # compute the difference in log times, to determine if two logs were close enough to be a missed ghost input
    def compute_delta(self, current_time=None):
        if self.delta['previous']:
            self.delta['string'] = ""
            self.delta['difference'] = max(current_time - self.delta['previous'], 0)
            # if the difference is within the threshold (~1.666 seconds for now... configurable?)
            if self.delta['difference'] < self.delta['threshold']:
                self.delta['pips'] = round(
                    self.delta['max_pips'] * (1 - (self.delta['difference'] / self.delta['threshold'])))
                if self.delta['pips'] > 0:
                    self.delta['string'] = "  +" + str(
                        round(self.delta['difference'] * 1000)) + "ms  [" + ("*" * self.delta['pips']) + "]"
        self.delta['previous'] = current_time

    def summarize(self):
        if not self.enabled:
            return

        # update totals
        self.counts['total'] = self.counts['blocked']['total'] + self.counts['allowed']['total']
        self.summary['percentage'] = (self.counts['blocked']['total'] / self.counts['total']) * 100 if \
            self.counts[
                'total'] > 0 else 0.0
        self.summary['elapsed_time'] = time.mktime(time.localtime()) - time.mktime(self.summary['start_time'])
        self.summary['per_minute'] = (self.counts['blocked']['total'] / self.summary['elapsed_time']) * 60
        self.summary['per_hour'] = self.summary['per_minute'] * 60

        # output a summary
        log("")
        log("//////////////////////////////////////////////////////////////////")
        log("   Summary for \"" + self.device.name + "\"", "on Profile [" + self.device.mode + "]")
        log("   |      Total Inputs Allowed", str(self.counts['allowed']['total']))
        log("   |      Total Ghost Inputs Blocked", str(self.counts['blocked']['total']))
        log("   | ")
        log("   |      Elapsed Time", str(self.summary['elapsed_time']) + " seconds" + "   (" + str(
            round(self.summary['elapsed_time'] / 60, 1)) + " minutes)    (" + str(
            round(self.summary['elapsed_time'] / 3600, 1)) + " hours)")
        log("   |      Ghost Input %", str(round(self.summary['percentage'], 3)) + "%")
        log("   |      Ghost Input rate", str(round(self.summary['per_minute'], 3)) + "/min   (" + str(
            round(self.summary['per_hour'])) + "/hr)")
        if self.counts['blocked']['total'] > 0:
            log("   | ")
            log("   |      By Button")
            # output how many times each button was ghosted, starting with the most common one
            for btn, cnt in sorted(self.counts['blocked']['by_button'].items(), key=lambda item: item[1],
                                   reverse=True):
                log("   |            (Joy " + str(btn) + ")", str(cnt))
            log("   |      By Simultaneity")
            # output how many buttons were pressed at the same time, starting with the most common number
            for simul, cnt in sorted(self.counts['blocked']['by_simultaneity'].items(), key=lambda item: item[1],
                                     reverse=True):
                log("   |            (" + str(simul) + " at once)", str(int(cnt)))
            log("   |      By Combination")
            # output which combinations of buttons were pressed at the same time, starting with the most common group
            for combo, cnt in sorted(self.counts['blocked']['by_combination'].items(), key=lambda item: item[1],
                                     reverse=True):
                log("   |            " + str(combo), str(int(cnt)))
        if self.is_debug:
            log("   | ")
            if self.events['archive']:
                log("   |      Allowed Events (since last summary)")
                self.flush_tracked_events("allowed", state="archive")
            else:
                log("   |      No new Allowed Events since last summary")

    def log(self, *args):

        if not self.enabled:
            return

        # output the message
        log(*args)


# class for each physical joystick device, for filtering and mapping
class FilteredDevice:
    def __init__(self,
                 # device
                 physical_device, name, vjoy_id, mode,
                 # buttons
                 button_remapping_enabled, button_filtering, button_filtering_sensitivity, button_filtering_threshold,
                 # axes
                 axis_remapping_enabled, axis_curve,
                 # hats
                 hat_remapping_enabled,
                 # debugging
                 logging_enabled, logging_is_debug, logging_summary_key
                 ):

        self.mode = mode
        self.physical_device = physical_device
        self.physical_guid = self.physical_device._info.device_guid
        self.name = name
        self.vjoy_id = vjoy_id
        self.virtual_guid = (gremlin.joystick_handling.vjoy_devices())[self.vjoy_id - 1].device_guid
        self.virtual_device = (gremlin.joystick_handling.VJoyProxy())[self.vjoy_id]

        self.button_remapping = button_remapping_enabled
        self.button_filtering = button_filtering
        self.button_filtering_sensitivity = button_filtering_sensitivity / 1000 if button_filtering else 0
        self.button_filtering_threshold = button_filtering_threshold
        self.button_callbacks = {'press': defaultdict(list), 'release': defaultdict(list)}

        self.axis_remapping = axis_remapping_enabled
        self.axis_curve = axis_curve

        self.hat_remapping = hat_remapping_enabled

        self.concurrent_presses = set()

        # Initialize debugging logging
        self.logger = Logger(self, logging_enabled, logging_is_debug, logging_summary_key)

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        self.initialize_inputs(first_time=True)

        self.logger.ready()

    # set all the virtual inputs for this device to the current physical status
    def initialize_inputs(self, start_at_zero=False, first_time=False):
        # for each button on the device
        if self.button_remapping:
            self.initialize_buttons(False if start_at_zero else None, first_time)

        # for each axis on the device
        if self.axis_remapping:
            self.initialize_axes(0.0 if start_at_zero else None, first_time)

        # for each hat on the device
        if self.hat_remapping:
            self.initialize_hats((0, 0) if start_at_zero else None, first_time)

    def initialize_buttons(self, value=None, first_time=False):
        if first_time:
            self.logger.log("        ... Initializing buttons on " + self.name)
        for btn in self.physical_device._buttons:
            if btn:
                # initialize value (to off if explicitly set; otherwise, current value)
                try:
                    self.virtual_device.button(
                        btn._index).is_pressed = value if value is not None else self.get_button(btn._index)
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
                                self.logger.start_tracking(event.identifier)

                            # wait the duration of the delay Sensitivity, then check for ghost inputs
                            defer(self.button_filtering_sensitivity, self.filter_the_button, event, vjoy, joy)

    def initialize_axes(self, value=None, first_time=False):
        if first_time:
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
                    axis_value = value if value is not None else self.get_axis(aid)
                    self.virtual_device.axis(aid).value = curve(axis_value) if self.axis_curve else axis_value
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

    def initialize_hats(self, value=None, first_time=False):
        if first_time:
            self.logger.log("        ... Initializing hats on " + self.name)
        for hat in self.physical_device._hats:
            if hat:
                # initialize value
                try:
                    self.virtual_device.hat(
                        hat._index).direction = value if value is not None else self.get_hat(hat._index)
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

    def get_button(self, id):
        return self.physical_device.button(id).is_pressed

    def get_axis(self, id):
        return self.physical_device.axis(id).value

    def get_hat(self, id):
        return self.physical_device.hat(id).direction

    # checks total number of buttons pressed, every time a new button is pressed within the configured timespan
    # and maps the physical device to the virtual device if NOT a ghost input
    def filter_the_button(self, event, vjoy, joy):

        # get the current state (after this much delay)
        still_pressed = joy[event.device_guid].button(event.identifier).is_pressed

        # if we're filtering, and if <threshold> or more buttons (including this button) are pressed,
        # and this button is no longer still pressed, this is likely a ghost input
        is_ghost = self.button_filtering and len(
            self.concurrent_presses) >= self.button_filtering_threshold and not still_pressed

        # if this was initially a press
        if event.is_pressed:
            # track this event
            self.logger.update_tracking(is_ghost, event.identifier, still_pressed)
            # if this is not a ghost input
            if not is_ghost:
                # update the virtual joystick
                self.trigger_the_button(event, vjoy, still_pressed)

            # it could still be part of an ongoing ghosting event, so wait the duration of the Sensitivity delay and end monitoring.
            # by then, enough time will have passed that this press should no longer be used to determine a Ghost Input
            defer(self.button_filtering_sensitivity, self.logger.end_tracking, event.identifier)
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
    def on_virtual_press(self, btns):
        def wrap(callback=None):
            # add the decorated function into the callbacks for this/these button id(s)
            if callback:
                for btn in btns if type(btns) is list else [btns]:
                    self.button_callbacks['press'][btn].append(callback)

        return wrap

    # decorator for registering custom callbacks when a virtual button was successfully released
    def on_virtual_release(self, btns):
        def wrap(callback=None):
            # add the decorated function into the callbacks for this/these button id(s)
            if callback:
                for btn in btns if type(btns) is list else [btns]:
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
def initialize_all_inputs():
    active_mode = gremlin.event_handler.EventHandler().active_mode
    for id, filtered_device in globals()['filtered_devices'].items():
        # if the new mode matches this device's mode, use the physical device input status
        # otherwise; initialize inputs to 0
        filtered_device.initialize_inputs(start_at_zero=active_mode != filtered_device.mode)


# switch modes and update all input states (synchronizes button states after a mode switch to prevent latching)
def switch_mode(mode=None):
    if mode is None:
        gremlin.control_action.switch_to_previous_mode()
    else:
        gremlin.control_action.switch_mode(mode)
    initialize_all_inputs()


# Plugin UI Configuration
ui_button_remapping = BoolVariable("Enable Button Remapping?",
                                   "Actively remap button input? Required for filtering ghost inputs", True)
ui_button_filtering = BoolVariable("  -  Enable Button Filtering?", "Actively filter ghost input?", True)
ui_button_filtering_threshold = IntegerVariable("          Button Filtering Threshold",
                                                "How many *buttons* pressed at once (within a timespan) constitute a Ghost Input (on a single device)? Default: 2",
                                                2, 0, 100)
ui_button_filtering_sensitivity = IntegerVariable("          Button Filtering Sensitivity (ms)",
                                                  "Timespan (in ms) to evaluate ghost input before possibly sending to vJoy? Default: 90ms",
                                                  90, 1, 1000)
ui_axis_remapping = BoolVariable("Enable Axis Remapping?",
                                 "Actively remap axes? Disable if remapping them through JG GUI", True)
ui_axis_curve = BoolVariable("  -  Smooth Response Curve?",
                             "If Axis Remapping, adds an S curve to the vJoy output, otherwise linear",
                             True)
ui_hat_remapping = BoolVariable("Enable Hat Remapping?",
                                "Actively remap hats? Disable if remapping them through JG GUI", True)
ui_logging_enabled = BoolVariable("Enable Logging?", "Output useful debug info to log (Recommended)", True)
ui_logging_is_debug = BoolVariable("  -  Debugging Mode",
                                   "Logs all button presses (Recommended only if Ghost Inputs are still getting through... tweak Sensitivity based on the log results)",
                                   False)
ui_logging_summary_key = StringVariable("  -  Generate a Summary with Key",
                                        "Which keyboard key to press to get a Ghost Input summary breakdown in the log?",
                                        "f8")

# Grab general user config
button_remapping_enabled = bool(
    ui_button_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
button_filtering = bool(ui_button_filtering.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
button_filtering_threshold = ui_button_filtering_threshold.value
button_filtering_sensitivity = ui_button_filtering_sensitivity.value

axis_remapping_enabled = bool(ui_axis_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
axis_curve = bool(ui_axis_curve.value)  # joystick gremlin has an issue with BoolVariable persistence(?)

hat_remapping_enabled = bool(ui_hat_remapping.value)  # joystick gremlin has an issue with BoolVariable persistence(?)

logging_enabled = bool(ui_logging_enabled.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
logging_is_debug = bool(ui_logging_is_debug.value)  # joystick gremlin has an issue with BoolVariable persistence(?)
logging_summary_key = ui_logging_summary_key.value

vjoy_devices = sorted(gremlin.joystick_handling.vjoy_devices(), key=lambda x: x.vjoy_id)
filtered_devices = {}
nicknames = defaultdict(list)

log("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
log("")
log("Ghost Input Filter", "Script starting")

log("")
log("Settings:")
log("   Button Filtering Threshold", str(button_filtering_threshold) + " buttons")
log("   Button Filtering Sensitivity", str(button_filtering_sensitivity) + " millisecond evaluation window")
log("   Debugging mode", "Enabled" if logging_is_debug else "Disabled")

# Output VJoy configuration to log, to show Windows (GUIDs) <-> Joystick Gremlin (Vjoy IDs) assignment
log("")
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
            button_filtering_sensitivity,
            button_filtering_threshold,
            axis_remapping_enabled,
            axis_curve,
            hat_remapping_enabled,
            logging_enabled,
            logging_is_debug,
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
