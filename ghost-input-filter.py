# python imports
import threading
import math
import time
from datetime import datetime
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

# class for each physical joystick device, for filtering and mapping
class Device:
    def __init__(self, physical_device, name, vjoy_id, mode, settings):

        self.mode = mode
        self.physical_device = physical_device
        self.physical_guid = self.physical_device._info.device_guid
        self.name = name
        self.vjoy_id = vjoy_id
        self.virtual_guid = (gremlin.joystick_handling.vjoy_devices())[self.vjoy_id - 1].device_guid
        self.virtual_device = (gremlin.joystick_handling.VJoyProxy())[self.vjoy_id]

        self.buttons = settings.buttons
        self.axes = settings.axes
        self.hats = settings.hats

        self.debug = settings.device.debug

        # Initialize logging
        self.logger = Logger(settings.device, self)
        self.events = Events(self)

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        self.initialize_inputs(first_time=True)

        self.logger.ready()

    # set all the virtual inputs for this device to the current physical status
    def initialize_inputs(self, start_at_zero=False, first_time=False):
        # for each button on the device
        if self.buttons.enabled:
            self.initialize_buttons(False if start_at_zero else None, first_time)

        # for each axis on the device
        if self.axes.enabled:
            self.initialize_axes(0.0 if start_at_zero else None, first_time)

        # for each hat on the device
        if self.hats.enabled:
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
                            the_button = Button(event, self)
                            if the_button.is_pressed:
                                # add this button to the active_event
                                self.events.start_tracking(the_button)
                            else:
                                # search for a corresponding press in the event log...
                                # if it's far enough from this release, it's a legitimate release, and we should update
                                # the button and execute the release callbacks
                                if self.events.active_event.find_button(the_button):
                                    the_button.connect_to_event(self.events.active_event)

                                    # wait the duration of the delay Wait Time, then check for ghost inputs
                            defer(self.buttons.wait_time, self.filter_the_button, the_button, vjoy, joy)

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
                    self.virtual_device.axis(aid).value = curve(axis_value) if self.axes.curve else axis_value
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
                                event.value) if self.axes.curve else event.value

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
    def filter_the_button(self, the_button, vjoy, joy):

        # get the current state (after this much delay)
        the_button.is_still_pressed = joy[the_button.device_guid].button(the_button.identifier).is_pressed

        # update the button's virtual timestamp and determine if is_ghost input
        the_button.evaluate_button()

        # if this was initially a press
        if the_button.is_pressed:
            # update this event
            self.events.update_tracking(the_button)

            # it could still be part of an ongoing ghosting event, so wait the duration of the Wait Time delay and end monitoring.
            # by then, enough time will have passed that this press should no longer be used to determine a Ghost Input
            defer(self.buttons.wait_time, the_button.event.end_tracking, the_button)

        if not the_button.is_ghost:
            # update the virtual button
            vjoy[self.vjoy_id].button(the_button.identifier).is_pressed = the_button.is_still_pressed

            # execute any decorated callbacks from custom code that match this keypress
            # via @device.on_virtual_press[/release](id)
            for callback in self.buttons.callbacks['press' if the_button.is_still_pressed else 'release'].get(
                    the_button.identifier):
                callback()

    # decorator for registering custom callbacks when a virtual button was successfully pressed or released
    def on_virtual_button(self, btns, events="press"):
        def wrap(callback=None):
            if callback:
                # for this/these button id(s)
                for btn in btns if type(btns) is list else [btns]:
                    # on this/these events(s) ("press"/"release")
                    for event in events if type(events) is list else [events]:
                        # add the decorated function into the callbacks for this button and event
                        self.buttons.callbacks[event][btn].append(callback)

        return wrap

    def on_virtual_press(self, btns):
        return self.on_virtual_button(btns, "press")

    def on_virtual_release(self, btns):
        return self.on_virtual_button(btns, "release")


class Logger:
    def __init__(self, settings, parent):

        self.parent = parent

        self.enabled = settings.enabled
        self.summary_key = settings.summary_key
        self.summary = {
            'percentage': 0.0,
            'start_time': time.localtime(),
            'elapsed_time': 0.0,
            'rate': 0.0
        }

        # log a summary every time summary button is pressed (user configurable)
        @gremlin.input_devices.keyboard(self.summary_key, self.parent.mode)
        def summary_callback(event):
            if event.is_pressed:
                self.summarize()

        self.starting()

    def starting(self):

        if not self.enabled:
            return

        # output general setup info

        log("")
        log("  Remapping [" + self.parent.mode + "] " + self.parent.name, str(self.parent.physical_guid))
        log("     to VJoy #" + str(self.parent.vjoy_id), str(self.parent.virtual_guid))
        if self.parent.buttons.filter:
            log("        ... Button Filtering enabled")
        if self.parent.debug:
            log("        ... Verbose logging enabled")

    def ready(self):

        if not self.enabled:
            return

        log("          [" + self.parent.mode + "] " + self.parent.name + " to VJoy #" + str(
            self.parent.vjoy_id) + " is Ready!")

    def summarize(self):

        if not self.enabled:
            return

        totals = self.parent.events.totals
        complete = self.parent.events.complete

        total = totals['blocked']['total'] + totals['allowed']['total']
        self.summary['percentage'] = (totals['blocked']['total'] / total) * 100 if \
            totals[
                'total'] > 0 else 0.0
        self.summary['elapsed_time'] = time.mktime(time.localtime()) - time.mktime(self.summary['start_time'])
        self.summary['per_minute'] = (totals['blocked']['total'] / self.summary['elapsed_time']) * 60
        self.summary['per_hour'] = self.summary['per_minute'] * 60

        # output a summary
        log("")
        log("//////////////////////////////////////////////////////////////////")
        log("   Summary for \"" + self.parent.name + "\"", "on Profile [" + self.parent.mode + "]")
        log("   |      Total Inputs Allowed", str(totals['allowed']['total']))
        log("   |      Total Ghost Inputs Blocked", str(totals['blocked']['total']))
        log("   | ")
        log("   |      Elapsed Time", str(self.summary['elapsed_time']) + " seconds" + "   (" + str(
            round(self.summary['elapsed_time'] / 60, 1)) + " minutes)    (" + str(
            round(self.summary['elapsed_time'] / 3600, 1)) + " hours)")
        log("   |      Ghost Input %", str(round(self.summary['percentage'], 3)) + "%")
        log("   |      Ghost Input rate", str(round(self.summary['per_minute'], 3)) + "/min   (" + str(
            round(self.summary['per_hour'])) + "/hr)")
        if totals['blocked']['total'] > 0:
            log("   | ")
            log("   |      By Button")
            # output how many times each button was ghosted, starting with the most common one
            for btn, cnt in sorted(totals['blocked']['by_button'].items(), key=lambda item: item[1],
                                   reverse=True):
                log("   |            (Joy " + str(btn) + ")", str(cnt))
            log("   |      By Simultaneity")
            # output how many buttons were pressed at the same time, starting with the most common number
            for simul, cnt in sorted(totals['blocked']['by_simultaneity'].items(), key=lambda item: item[1],
                                     reverse=True):
                log("   |            (" + str(simul) + " at once)", str(int(cnt)))
            log("   |      By Combination")
            # output which combinations of buttons were pressed at the same time, starting with the most common group
            for combo, cnt in sorted(totals['blocked']['by_combination'].items(), key=lambda item: item[1],
                                     reverse=True):
                log("   |            " + str(combo), str(int(cnt)))
        if self.parent.debug:
            log("   | ")
            if complete.has_events():
                log("   |      Allowed Events (since last summary)")
                complete.flush_events()
            else:
                log("   |      No new Allowed Events since last summary")

    def log(self, *args):

        if not self.enabled:
            return

        # output the message
        log(*args)


# the running log of "Event" groups
class Events:
    def __init__(self, parent):
        self.parent = parent
        self.active_event = Event(self)
        self.last_event = None
        self.in_progress = EventList("in_progress", parent=self)
        self.complete = EventList("complete", parent=self)
        self.totals = {
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

    def start_tracking(self, the_button):
        if not self.parent.buttons.enabled:
            return

        self.active_event.add_button(the_button)

    # increment totals and update the in_progress event list with changes from active_event
    def update_tracking(self, the_button):
        if not self.parent.buttons.enabled:
            return

        self.increment_totals(the_button)

        # clone the active event, so we can save it to in_progress (and non-destructively remove its buttons later)
        active_event = self.active_event.clone_event()
        # find the in-progress event
        the_event = self.in_progress.find_similar_event(active_event)
        if the_event:
            # and update it with the current state of active
            the_event.merge_event(active_event)
        else:
            # otherwise, add a clone of the active event to in_progress
            self.in_progress.add_event(active_event)

    def end_tracking(self, the_button):
        if not self.parent.buttons.enabled:
            return

        # remove this button from active_event. It should no longer be used to determine ghost inputs
        self.active_event.remove_button(the_button)

        # if this is the end of the ghosting event
        if len(self.active_event.buttons) <= 0:
            # output appropriate events to the log
            self.in_progress.flush_events()
            # and reinitialize the active Event
            self.active_event = Event(self)

    def increment_totals(self, the_button):

        # generate a sorted set from the buttons in this event
        concurrent_presses = sorted(set(self.active_event.buttons.keys()))
        size = len(concurrent_presses)

        # determine event type for this button press
        event_type = "blocked" if the_button.is_ghost else "allowed"

        # on press, increment the counters
        self.totals[event_type]['total'] += 1
        self.totals[event_type]['by_button'][the_button.identifier] += 1
        self.totals[event_type]['by_simultaneity'][size] += 1.0 / size
        self.totals[event_type]['by_combination'][str(concurrent_presses)] += 1.0 / size


class EventList:
    def __init__(self, id, parent):
        self.parent = parent
        self.grand_parent = parent.parent
        self.id = id
        self.list = {}

    def has_events(self):
        return len(self.list) > 0

    # def create_event(self, the_button):
    #     the_event = Event(self)
    #     the_event.add_button(the_button)
    #     self.list[the_event.id] = the_event
    #     return the_event

    # search this event list for an event that intersects
    def find_similar_event(self, the_event):
        for key, event in list(self.list.items()):
            # if any buttons in this combination are found in an event in this event list
            if set(event.buttons.keys()).intersection(set(the_event.buttons.keys())):
                return event
        return None

    def add_event(self, the_event):
        self.list[the_event.id] = the_event

    def remove_event(self, the_event):
        del self.list[the_event.id]

    def move_event_to(self, the_event, the_event_list):
        # move to a new list
        the_event_list.add_event({the_event.id: the_event.clone_event()})
        # and remove from this list
        self.remove_event(the_event)

    # output all registered ghosting/legitimate events and flush the list
    # def move_events_to(self, the_event_list):
    #     # for each event
    #     for key, event in list(self.list.items()):
    #         self.move_event_to(event, the_event_list)

    def flush_events(self):
        if self.has_events():
            # for each event
            for key, event in list(self.list.items()):
                # if any button in the event was blocked, this is a ghosting event
                event_type = event.get_type()

                # generate an event message
                if event_type is "blocked":
                    msg = "> GHOST INPUTS blocked!"
                elif event_type is "allowed" and self.parent.debug:
                    if self.id is "complete":
                        msg = "   |            At " + str(key.strftime('%H:%M:%S.%f')[:-3]) + " ..... "
                    else:
                        msg = "> USER PRESS allowed:"
                else:
                    msg = False

                # output a message (if we should)
                if msg:
                    # build human-readable button breakdown string
                    buttons_string = []
                    for id, button in event.buttons.items():
                        btn_str = str(button.type) + " press " + ("blocked" if button.type == "ghost" else "allowed")
                        if self.parent.debug:
                            # abbreviate event
                            btn_str = ("".join([word[0].upper() for word in btn_str.split()])) + " @ " + str(
                                button.virtual_time.strftime('%H:%M:%S.%f')[:-3])
                        buttons_string.append("Joy " + str(id) + ": " + btn_str)
                    breakdown = "(" + ("  |  ".join(buttons_string)) + ")"

                    # if debugging, compute difference to previous entry (to flag possible missed ghost inputs)
                    if self.parent.last_event and self.grand_parent.debug:
                        # see if the difference is within the logging threshold (~.5s for now) and flag it
                        breakdown += event.get_flag(self.parent.last_event, .5)
                    self.parent.last_event = event.clone_event()

                    # if we're in debug mode
                    if self.parent.debug and self.id is "in_progress":
                        # save all completed events into [complete]
                        self.move_event_to(event, self.parent.complete)

                    # log the event
                    msg += " [" + self.parent.mode + "] " + self.parent.name + " pressed " + str(
                        len(event.buttons)) + " buttons at once"
                    self.parent.parent.logger.log(msg, breakdown, 90)

                    # delete the event from the list
                    self.remove_event(event)


# a group of simultaneous Button presses
class Event:
    def __init__(self, parent, start_time=None, end_time=None, delta=None, id=None, buttons=None):
        self.parent = parent
        self.grand_parent = parent.parent
        self.start_time = start_time if start_time else datetime.now()
        self.end_time = end_time if end_time else None
        self.delta = delta if delta else None
        self.id = id if id else str(self.start_time)
        self.buttons = buttons if buttons else {}

    def is_ghost_event(self):
        return any(True in button.is_ghost for button in self.buttons.values())

    def is_within_threshold(self, event, threshold):
        self.delta = abs(event.start_time - self.start_time)
        return self.delta.total_seconds() < threshold

    def get_type(self):
        return "blocked" if self.is_ghost_event() else "allowed"

    def get_flag(self, event, threshold):
        if self.is_within_threshold(event, threshold):
            max_pips = 5
            pips = round(max_pips * (1 - (self.delta.total_seconds() / threshold)))
            if pips > 0:
                return ("  +" + str(round(self.delta.total_seconds() * 1000)) + "ms  [" + (
                        "*" * pips) + " Possible Ghost Press Allowed?]")
        return ""

    def find_button(self, the_button):
        self.buttons.get(the_button.identifier)

    def add_button(self, the_button):
        # tell this button which event it's in
        the_button.connect_to_event(self)
        # add this button to the list of concurrent buttons
        self.buttons[the_button.identifier] = the_button

        return the_button

    def remove_button(self, the_button):
        del self.buttons[the_button.identifier]

    def update_event(self, the_button):
        # tell this button which event it's in
        the_button.event = self
        # and add to the concurrent buttons dict
        self.buttons[the_button.identifier] = the_button

    def merge_event(self, the_event):
        self.buttons.update(dict(the_event.buttons))

    def clone_event(self):
        return Event(self.parent, self.start_time, self.end_time, self.delta, str(self.id), dict(self.buttons))


# single button-press event
class Button:
    def __init__(self, e, parent):
        self.parent = parent
        self.event = None
        self.identifier = e.identifier
        self.device_guid = e.device_guid
        self.is_pressed = e.is_pressed
        self.is_still_pressed = None
        self.is_ghost = None
        self.type = None
        self.physical_time = datetime.now()
        self.virtual_time = None
        self.delta = None

    def connect_to_event(self, the_event):
        self.event = the_event

    def evaluate_button(self):
        self.virtual_time = datetime.now()
        self.is_ghost = self.is_ghost_press() if self.is_pressed else self.is_ghost_release()
        self.type = "ghost" if self.is_ghost else "released" if not self.is_pressed else (
            "long" if self.is_still_pressed else "short")

    # ghost conditions for a press
    def is_ghost_press(self):
        # filtering enabled?
        is_filtering = self.parent.buttons.filter
        # multiple simultaneous buttons above threshold?
        is_max_concurrent = len(self.event.buttons) > self.parent.buttons.max_concurrent
        # is this press too close to any of the press events before it?
        is_min_interval = self.event.is_within_threshold(self.parent.events.last_event,
                                                         self.parent.buttons.min_interval)
        # could this be a legitimate long press (if strict mode is off)?
        is_legitimate_long_press = (
                self.is_still_pressed and not is_min_interval) if not self.parent.buttons.is_strict else False

        # a ghost press if
        # 1) filtering is enabled,
        # 2) more than <max_concurrent> buttons are pressed at once,
        # 3) it's not still pressed,
        # or 4) it is still pressed but was very close to previous/next press(es) (and Strict Mode is off)
        return is_filtering and is_max_concurrent and not is_legitimate_long_press

    # ghost conditions for a release
    def is_ghost_release(self):
        # filtering enabled?
        is_filtering = self.parent.buttons.filter

        # get the corresponding press event, if exists
        is_corresponding_ghost_press = self.event.is_ghost_event() if self.event else False

        # a ghost release if
        # 1) filtering is enabled,
        # 2) corresponds to a recent ghost press
        return is_filtering and is_corresponding_ghost_press


class Settings:
    def __init__(self, buttons, axes, hats, device):
        self.buttons = self.Buttons(**buttons)
        self.axes = self.Axes(**axes)
        self.hats = self.Hats(**hats)
        self.device = self.Device(**device)

    class Buttons:
        def __init__(self, enabled, filter, wait_time, max_concurrent, min_interval, is_strict):
            self.enabled = enabled
            self.filter = filter
            self.wait_time = wait_time / 1000 if self.filter else 0
            self.max_concurrent = max_concurrent
            self.min_interval = min_interval / 1000 if self.filter else 0
            self.is_strict = is_strict
            self.callbacks = {'press': defaultdict(list), 'release': defaultdict(list)}

    class Axes:

        def __init__(self, enabled, curve):
            self.enabled = enabled
            self.curve = curve

    class Hats:

        def __init__(self, enabled):
            self.enabled = enabled

    class Device:

        def __init__(self, logging_enabled, debug, summary_key):
            self.logging_enabled = logging_enabled
            self.debug = debug
            self.summary_key = summary_key


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
    for id, device in globals()['filtered_devices'].items():
        # if the new mode matches this device's mode, use the physical device input status
        # otherwise; initialize inputs to 0
        device.initialize_inputs(start_at_zero=active_mode != device.mode)


# switch modes and update all input states (synchronizes button states after a mode switch to prevent latching)
def switch_mode(mode=None):
    if mode is None:
        gremlin.control_action.switch_to_previous_mode()
    else:
        gremlin.control_action.switch_mode(mode)
    initialize_all_inputs()


# Plugin UI Configuration
ui_is_button_remapping = BoolVariable("> Enable Button Remapping?",
                                      "Actively remap button input? Required for filtering ghost inputs", True)
ui_is_button_filtering = BoolVariable("    -  Enable Button Filtering?", "Actively filter ghost input?", True)
ui_button_wait_time = IntegerVariable("          Wait for <ms> to evaluate the press",
                                      "Time (in ms) to wait before deciding if ghost input before sending to vJoy? Lower = Fewer False Positives, Higher = Less Ghosting. Default: 90ms",
                                      90, 1, 1000)
ui_button_max_concurrent = IntegerVariable(
    "            Maybe Ghost: If more than <#> buttons are pressed simultaneously",
    "How many buttons pressed *at once* (within the wait time) are allowed (on a single device)? Lower = Less Ghosting, Higher = Fewer False Positives. Default: 1",
    1, 1, 10)
ui_button_min_interval = IntegerVariable("            Maybe Ghost: If any event is closer than <ms> apart",
                                         "Timespan (in ms) between buttons that should trigger a Ghost filtering (even if it was registered as a single press)? Lower = Fewer False Positives, Higher = Less Ghosting. Default: 10ms",
                                         10, 1, 1000)
ui_button_is_strict = BoolVariable(
    "            Strict Mode: Prevent a button even if it is still pressed after the Wait Time?",
    "Ghost Presses tend to release immediately--otherwise, tries to interpret as a real press. On = Less Ghosting, Off = Fewer False Positives. Default: Off",
    False)
ui_axis_remapping = BoolVariable("> Enable Axis Remapping?",
                                 "Actively remap axes? Disable if remapping them through JG GUI", True)
ui_axis_curve = BoolVariable("    -  Smooth Response Curve?",
                             "If Axis Remapping, adds an S curve to the vJoy output, otherwise linear",
                             True)
ui_hat_remapping = BoolVariable("> Enable Hat Remapping?",
                                "Actively remap hats? Disable if remapping them through JG GUI", True)
ui_logging_enabled = BoolVariable("Enable Logging?", "Output useful debug info to log (Recommended)", True)
ui_is_debug = BoolVariable("  -  Debugging Mode",
                           "Logs all button presses (Recommended only if Ghost Inputs are still getting through... tweak Wait Time / Minimum based on the log results)",
                           False)
ui_summary_key = StringVariable("  -  Generate a Summary with Key",
                                "Which keyboard key to press to get a Ghost Input summary breakdown in the log?",
                                "f8")

# Grab general user config
settings = Settings(
    buttons={
        "enabled": ui_is_button_remapping.value,
        "filter": ui_is_button_filtering.value,
        "wait_time": ui_button_wait_time.value,
        "max_concurrent": ui_button_max_concurrent.value,
        "min_interval": ui_button_min_interval.value,
        "is_strict": ui_button_is_strict.value
    },
    axes={
        "enabled": ui_axis_remapping.value,
        "curve": ui_axis_curve.value
    },
    hats={
        "enabled": ui_hat_remapping.value
    },
    device={
        "logging_enabled": ui_logging_enabled.value,
        "debug": ui_is_debug.value,
        "summary_key": ui_summary_key.value
    }
)

vjoy_devices = sorted(gremlin.joystick_handling.vjoy_devices(), key=lambda x: x.vjoy_id)
filtered_devices = {}
nicknames = defaultdict(list)

log("+++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
log("")
log("Ghost Input Filter", "Script starting")

log("")
log("   Ghost Presses tend to have the following characteristics:")
log("      - Multiple buttons triggered simultaneously")
log("      - Multiple buttons triggered very close together")
log("      - Triggered buttons released immediately")
log("   This plugin attempts to recognize those characteristics and actively filter out any presses that match all of them.")
log("   You can customize the parameters to distinguish between those characteristics and your actual, real button presses (based on you own play style.")

log("")
log("Current Settings:")
log("   Button Filtering Threshold", str(settings.buttons.threshold) + " buttons")
log("   Button Filtering Wait Time", str(settings.buttons.wait_time) + " millisecond evaluation buffer")
log("   Button Filtering Minimum", str(settings.buttons.minimum) + " millisecond button event separation")
log("   Debugging mode", "Enabled" if settings.logging.debug else "Disabled")
if settings.logging.debug:
    log("      -   Event Code Descriptions")
    log("              GPB", "Ghost Press Blocked (always a short press)")
    log("              SPA", "Short Press Allowed")
    log("              LPA", "Long Press Allowed")

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
        device_proxy = (gremlin.input_devices.JoystickProxy())[gremlin.profile.parse_guid(device_guid)]

        # generate a unique but shorter name for this device
        name = device_proxy._info.name
        nickname = "Stick" if "stick" in name.lower() else "Throttle" if "throttle" in name.lower() else name
        nickname = nickname if nickname not in nicknames or device_guid in nicknames[
            nickname] else nickname + " " + str(len(nicknames[nickname]) + 1)
        nicknames[nickname].append(device_guid)

        # create a filtered device for each vjoy device that is getting remapped
        # Initialize filtered device (which creates decorators to listen for and filter input)
        device = Device(
            device_proxy,
            nickname,
            int(vjoy_id),
            mode,
            settings
        )
        filtered_devices[int(vjoy_id)] = device

        # Custom Callbacks
        # Add any custom callback functions here, for events you want to happen IF a virtual input is successfully pressed

        # Example:
        # if name == "Stick":
        #     @device.on_virtual_press(<button id>)
        #     def custom_callback():
        #         # do something here

        #     @device.on_virtual_release(<button id>)
        #     def custom_callback():
        #         # do something here

        pass
