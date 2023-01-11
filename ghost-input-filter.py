# python imports
import threading
import time
import math
from datetime import datetime, timedelta
from collections import defaultdict
from pprint import pformat
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

        self.settings = settings

        # Initialize logging
        self.logger = Logger(self)
        self.events = Events(self)

        # create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, str(self.physical_guid), self.mode)

        self.initialize_inputs(first_time=True)

        self.logger.ready(self)

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    # set all the virtual inputs for this device to the current physical status
    def initialize_inputs(self, start_at_zero=False, first_time=False):
        # for each button on the device
        if self.settings.buttons.enabled:
            self.initialize_buttons(False if start_at_zero else None, first_time)

        # for each axis on the device
        if self.settings.axes.enabled:
            self.initialize_axes(0.0 if start_at_zero else None, first_time)

        # for each hat on the device
        if self.settings.hats.enabled:
            self.initialize_hats((0, 0) if start_at_zero else None, first_time)

    def initialize_buttons(self, value=None, first_time=False):
        if first_time:
            self.logger.log("        ... Initializing buttons on " + self.name)
        for btn in self.physical_device._buttons:
            if btn:
                # initialize value (to off if explicitly set; otherwise, current value)
                try:
                    if value is None:
                        value = self.get_button(btn._index)
                    self.virtual_device.button(btn._index).is_pressed = value
                except:
                    self.logger.log("> Error initializing button " + str(btn._index) + " value")
                else:
                    # if this is the first time, set up the decorators
                    if first_time:
                        # add a decorator function for when that button is pressed
                        @self.decorator.button(btn._index)
                        # pass that info to the function that will check other button presses
                        def callback(event, vjoy, joy):
                            the_button = Button(event)
                            if the_button.was_a_press:
                                # add this button to the active_event
                                self.events.start_tracking(the_button)
                            else:
                                # search for a matching press in the event log...
                                # if it's far enough from this release, it's a legitimate release, and we should update
                                # the button and execute the release callbacks
                                if self.events.active_event.find_button(the_button):
                                    the_button.connect_to_event(self.events.active_event)

                                    # wait the duration of the delay Wait Time, then check for ghost inputs
                            defer(self.settings.buttons.latency, self.filter_the_button, the_button, vjoy, joy)

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
                    if value is None:
                        value = self.get_axis(aid)
                    self.virtual_device.axis(aid).value = curve(value) if self.settings.axes.curve else value
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
                                event.value) if self.settings.axes.curve else event.value

    def initialize_hats(self, value=None, first_time=False):
        if first_time:
            self.logger.log("        ... Initializing hats on " + self.name)
        for hat in self.physical_device._hats:
            if hat:
                # initialize value
                try:
                    if value is None:
                        value = self.get_hat(hat._index)
                    self.virtual_device.hat(hat._index).direction = value
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
        the_button.evaluate_button(self)

        # if this was initially a press
        if the_button.was_a_press:
            # it could still be part of an ongoing ghosting event, so wait the duration of the Wait Time delay and end monitoring.
            # by then, enough time will have passed that this press should no longer be used to determine a Ghost Input
            defer(self.settings.buttons.latency, self.events.end_tracking, the_button, self)

        if not the_button.is_ghost:
            # update the virtual button
            vjoy[self.vjoy_id].button(the_button.identifier).is_pressed = the_button.is_still_pressed

            # execute any decorated callbacks from custom code that match this keypress
            # via @device.on_virtual_press[/release](id)
            callbacks = self.settings.buttons.callbacks['press' if the_button.is_still_pressed else 'release'].get(
                the_button.identifier)
            if callbacks:
                for callback in callbacks:
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
                        self.settings.buttons.callbacks[event][btn].append(callback)

        return wrap

    def on_virtual_press(self, btns):
        return self.on_virtual_button(btns, "press")

    def on_virtual_release(self, btns):
        return self.on_virtual_button(btns, "release")


class Logger:
    def __init__(self, the_device):

        self.enabled = the_device.settings.logging
        self.summary_key = the_device.settings.summary_key
        self.summary = {
            'percentage': 0.0,
            'start_time': time.localtime(),
            'elapsed_time': 0.0,
            'rate': 0.0
        }

        # log a summary every time summary button is pressed (user configurable)
        @gremlin.input_devices.keyboard(self.summary_key, the_device.mode)
        def summary_callback(event):
            if event.is_pressed:
                self.summarize(the_device)

        self.starting(the_device)

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    def starting(self, the_device):

        if not self.enabled:
            return

        # output general setup info

        log("")
        log("  Remapping [" + the_device.mode + "] " + the_device.name, str(the_device.physical_guid))
        log("     to VJoy #" + str(the_device.vjoy_id), str(the_device.virtual_guid))
        if the_device.settings.buttons.filter:
            log("        ... Button Filtering enabled")
        if the_device.settings.debug:
            log("        ... Verbose logging enabled")

    def ready(self, the_device):

        if not self.enabled:
            return

        log("          [" + the_device.mode + "] " + the_device.name + " to VJoy #" + str(
            the_device.vjoy_id) + " is Ready!")

    def summarize(self, the_device):

        if not self.enabled:
            return

        totals = the_device.events.totals
        complete = the_device.events.complete

        total = totals['buttons']['blocked']['total'] + totals['buttons']['allowed']['total']
        self.summary['percentage'] = (totals['buttons']['blocked'][
                                          'total'] / total) * 100 if total > 0 else 0.0  # !div/0
        self.summary['elapsed_time'] = time.mktime(time.localtime()) - time.mktime(self.summary['start_time'])
        self.summary['per_minute'] = (totals['buttons']['blocked']['total'] / self.summary['elapsed_time']) * 60
        self.summary['per_hour'] = self.summary['per_minute'] * 60

        # output a summary
        log("")
        log("//////////////////////////////////////////////////////////////////")
        log("   Summary for \"" + the_device.name + "\"", "on Profile [" + the_device.mode + "]")
        log("   |      Total Inputs Allowed", str(totals['buttons']['allowed']['total']))
        log("   |      Total Ghost Inputs Blocked", str(totals['buttons']['blocked']['total']))
        log("   | ")
        log("   |      Total Allowed Events", str(totals['events']['allowed']['total']))
        log("   |      Total Blocked Events", str(totals['events']['blocked']['total']))
        log("   |      Total Mixed Events", str(totals['events']['mixed']['total']))
        log("   | ")
        log("   |      Elapsed Time", str(self.summary['elapsed_time']) + " seconds" + "   (" + str(
            round(self.summary['elapsed_time'] / 60, 1)) + " minutes)    (" + str(
            round(self.summary['elapsed_time'] / 3600, 1)) + " hours)")
        log("   |      Ghosting %", str(round(self.summary['percentage'], 3)) + "%")
        log("   |      Ghost Block rate", str(round(self.summary['per_minute'], 3)) + "/min   (" + str(
            round(self.summary['per_hour'])) + "/hr)")

        for event_type in ["blocked", "allowed"]:
            if totals['buttons'][event_type]['total'] > 0:
                log("   | ")
                log("   |      " + event_type.capitalize() + " Events")

                def output_the_data(totals, event_type, metric):
                    for key, cnt in sorted(totals[event_type][metric].items(), key=lambda item: item[1], reverse=True):
                        log("   |                  " + str(key), str(int(math.ceil(cnt))))

                log("   |            By Button")
                # output how many times each button was ghosted, starting with the most common one
                output_the_data(totals['buttons'], event_type, 'by_button')
                log("   |            By Simultaneity")
                # output how many buttons were triggered at the same time, starting with the most common number
                output_the_data(totals['events'], event_type, 'by_simultaneity')
                log("   |            By Combination")
                # output which combinations of buttons were pressed at the same time, starting with the most common
                output_the_data(totals['events'], event_type, 'by_combination')

                # if event_type == "allowed" and the_device.settings.debug:
                #     log("   | ")
                #     if complete.has_events():
                #         log("   |      Allowed Events (since last summary)")
                #         complete.flush_events(the_device)
                #     else:
                #         log("   |      No new Allowed Events since last summary")

    def log(self, *args, **kwargs):

        if not self.enabled:
            return

        # output the message
        log(*args, **kwargs)


# the running log of "Event" groups
class Events:
    def __init__(self, the_device):
        self.enabled = the_device.settings.buttons.enabled
        self.active_event = Event()
        self.last_event = None
        self.complete = EventList("complete")
        self.totals = {
            'events': {
                'allowed': {
                    'total': 0,
                    'by_simultaneity': defaultdict(int),
                    'by_combination': defaultdict(int)
                },
                'blocked': {
                    'total': 0,
                    'by_simultaneity': defaultdict(int),
                    'by_combination': defaultdict(int)
                },
                'mixed': {
                    'total': 0
                }

            },
            'buttons': {
                'allowed': {
                    'total': 0,
                    'by_button': defaultdict(int)
                },
                'blocked': {
                    'total': 0,
                    'by_button': defaultdict(int)
                }
            }
        }

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    def start_tracking(self, the_button):

        if not self.enabled:
            return

        self.active_event.add_button(the_button)

    def end_tracking(self, the_button, the_device):
        if not self.enabled:
            return

        # flag this button as expired. It should no longer be used to determine ghost inputs
        the_button.expire()

        # if this is the end of the ghosting event
        if len(self.active_event.get_active_presses()) <= 0:
            # update this event's totals
            self.update_totals()

            # output event to the log
            self.active_event.flush_event(the_device)

            # and reinitialize the active Event
            self.active_event = Event()

    # increment totals and update the in_progress event list with changes from active_event
    def update_totals(self):
        if not self.enabled:
            return

        is_ghost = self.active_event.has_any()
        is_heterogeneous = self.active_event.has_any(not is_ghost)

        by_event = {
            'allowed': {},
            'blocked': {}
        }

        # increment the event type
        self.totals['events']["mixed" if is_heterogeneous else "blocked" if is_ghost else "allowed"]['total'] += 1

        # increment per button
        for key, button in self.active_event.buttons.items():
            button_type = "blocked" if button.is_ghost else "allowed"
            self.totals['buttons'][button_type]['total'] += 1
            self.totals['buttons'][button_type]['by_button']["(Joy " + str(key) + ")"] += 1
            by_event[button_type][key] = button

        # increment per allowed/blocked combination
        for event_type, buttons in by_event.items():
            combination = set(buttons.keys())
            size = len(combination)

            if size > 0:
                self.totals['events'][event_type]['by_simultaneity']["(" + str(size) + " at once)"] += 1.0 / size
                self.totals['events'][event_type]['by_combination'][str(combination)] += 1.0 / size


class EventList:
    def __init__(self, id):
        self.id = id
        self.list = {}

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    def has_events(self):
        return len(self.list) > 0

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

    def flush_events(self, the_device):
        if self.has_events():
            # for each event, generate an event message
            for key, event in list(self.list.items()):
                event.flush_event(the_device, event_list=self.id)
                # delete the event from the list
                self.remove_event(event)


# a group of simultaneous Button presses
class Event:
    def __init__(self, start_time=None, end_time=None, delta=None, id=None, buttons=None):
        self.start_time = start_time if start_time else datetime.now()
        self.end_time = end_time if end_time else None
        self.delta = delta if delta else None
        self.id = id if id else self.start_time
        self.buttons = buttons if buttons else {}
        self.threshold = globals()['settings'].buttons.latency * 4  # for flagging any events close together

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    def has_any(self, is_ghost=True):
        return any(button.is_ghost == is_ghost for button in self.buttons.values())

    def has_matching(self, the_button, is_ghost=True):
        matching_button = self.buttons.get(the_button.identifier)
        return self.buttons[the_button.identifier].is_ghost == is_ghost if matching_button else False

    def is_all(self, is_ghost=True):
        return all(button.is_ghost == is_ghost for button in self.buttons.values())

    def is_not_all(self, is_ghost=True):
        return all(button.is_ghost != is_ghost for button in self.buttons.values())

    def is_event_within_threshold(self, last_event):
        self.delta = self.start_time - last_event.start_time
        return self.delta.total_seconds() < self.threshold if self.delta.total_seconds() > 0 else False

    def get_active_presses(self):
        # get a list of active buttons that haven't expired
        return [key for key, button in set(sorted(self.buttons.items())) if not button.end_time]

    def get_presses(self):
        # get a list of all buttons pressed in this event
        return [key for key, button in set(sorted(self.buttons.items()))]

    def get_flag(self, last_event):
        pips = 0
        flag = ""
        # was this event very close to the previous event?
        if self.is_event_within_threshold(last_event):
            # map the seconds from 0 to <threshold> to 0 pips to <max_pips (5)> (inverted)
            pips = int(map_value(self.delta.total_seconds(), (0.0, self.threshold), (5, 0)))
            if pips:
                flag += ("  ...Previous Event +" + str(round(max(self.delta.total_seconds() * 1000, 0))) + "ms")
        # were any of these buttons allowed during a ghosting event?
        if self.has_any():
            allowed = len([button.identifier for button in self.buttons.values() if not button.is_ghost])
            total = len(self.buttons)
            # map the allowed/total ratio to 0 pips to <max_pips (5)>
            pips = int(map_value(allowed, (0.0, total), (0, 5)))
            if pips:
                flag += ("  ..." + str(allowed) + " out of " + str(total) + " buttons triggered")
        if pips > 0:
            flag += "  [" + ("*" * pips) + "]"
        if flag:
            flag += "  Possible Ghost Press Allowed?"
        return flag

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
        return Event(self.start_time, self.end_time, self.delta, self.id, dict(self.buttons))

    def flush_event(self, the_device, event_list=None):
        self.end_time = datetime.now()

        is_ghost_event = self.has_any(is_ghost=True)
        # if ghosting event
        if is_ghost_event:
            msg = "> GHOST INPUTS blocked!"
        # if allowed event, and we're debugging verbosely
        elif the_device.settings.debug:
            if event_list is "complete":
                msg = "   |            At " + str(self.start_time.strftime('%H:%M:%S.%f')[:-3]) + " ..... "
            else:
                msg = "> USER PRESS allowed:"
        else:
            msg = False

        # output a message (if we have one)
        if msg:
            # build human-readable button breakdown string
            buttons_string = []
            for id, button in self.buttons.items():
                btn_str = ("long" if button.is_still_pressed else "short") + \
                          (" ghost" if button.is_ghost else "") + \
                          (" press" if button.was_a_press else " release ") + \
                          (" blocked" if button.is_ghost else " allowed")
                if the_device.settings.debug:
                    # abbreviate event
                    btn_str = ("".join([word[0].upper() for word in btn_str.split()])) + " @ " + str(
                        button.trigger_time.strftime('%H:%M:%S.%f')[:-3])
                buttons_string.append("Joy " + str(id) + ": " + btn_str)
            breakdown = "(" + ("  |  ".join(buttons_string)) + ")"

            # if debugging, compute difference to previous entry (to flag possible missed ghost inputs)
            if the_device.events.last_event and the_device.settings.debug:
                # see if the difference is within the logging threshold and flag it
                breakdown += self.get_flag(the_device.events.last_event)
            the_device.events.last_event = self.clone_event()

            # if we're in debug mode
            if the_device.settings.debug and event_list is not "complete" and not is_ghost_event:
                # save all allowed events into [complete]
                the_device.events.complete.add_event(self.clone_event())

            # log the event
            msg += " [" + the_device.mode + "] " + the_device.name + " pressed " + str(
                len(self.buttons)) + " buttons at once"
            the_device.logger.log(msg, breakdown, gutter=90)


# single button-press event
class Button:
    def __init__(self, e):
        self.event_id = None
        self.identifier = e.identifier
        self.device_guid = e.device_guid
        self.was_a_press = e.is_pressed
        self.is_still_pressed = None
        self.is_ghost = None
        self.type = None
        self.start_time = datetime.now()
        self.trigger_time = None
        self.end_time = None
        self.delta = None

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    def connect_to_event(self, the_event):
        self.event_id = the_event.id

    def evaluate_button(self, the_device):
        self.trigger_time = datetime.now()
        self.is_ghost = self.is_ghost_press(the_device) if self.was_a_press else self.is_ghost_release(the_device)

    def expire(self):
        self.end_time = datetime.now()

    # loop through all buttons in this event and see if any are too close together
    def is_button_within_threshold(self, the_device):
        for id, button in the_device.events.active_event.buttons.items():
            if button.identifier == self.identifier:
                continue
            delta = self.start_time - button.start_time
            if abs(delta.total_seconds()) < the_device.settings.buttons.min_separation:
                return True
        return False

    # ghost conditions for a press
    def is_ghost_press(self, the_device):
        # filtering enabled?
        is_filtering = the_device.settings.buttons.filter
        # multiple simultaneous buttons above threshold?
        is_max_concurrent = len(the_device.events.active_event.buttons) > the_device.settings.buttons.max_concurrent
        # is this press too close to any other presses in this event?
        is_within_min_separation = self.is_button_within_threshold(the_device)
        # could this be a legitimate long press (if strict mode is off)?
        is_legitimate_long_press = self.is_still_pressed and not the_device.settings.buttons.is_strict
        # a ghost press if
        # 1) filtering is enabled,
        # 2) more than <max_concurrent> buttons are pressed at once,
        # 3) it's very close to another button press in this event
        # and 4) it's not still pressed as of now (if Strict Mode is off)
        return is_filtering and is_max_concurrent and is_within_min_separation and not is_legitimate_long_press

    # ghost conditions for a release
    def is_ghost_release(self, the_device):
        # filtering enabled?
        is_filtering = the_device.settings.buttons.filter

        # get the matching press event, if exists
        has_matching_ghost_press = the_device.events.active_event.has_matching(
            the_button=self) if self.event_id else False

        # a ghost release if
        # 1) filtering is enabled,
        # 2) corresponds to a recent ghost press
        return is_filtering and has_matching_ghost_press


class Settings:
    def __init__(self, buttons, axes, hats, logging, debug, summary_key):
        self.buttons = self.Buttons(**buttons)
        self.axes = self.Axes(**axes)
        self.hats = self.Hats(**hats)
        self.logging = logging
        self.debug = debug
        self.summary_key = summary_key

    def __repr__(self):
        return "\n" + pformat(vars(self), indent=6, width=1)

    class Buttons:
        def __init__(self, enabled, filter, latency, max_concurrent, min_separation, is_strict):
            self.enabled = enabled
            self.filter = filter
            self.latency = latency / 1000 if self.filter else 0
            self.max_concurrent = max_concurrent
            self.min_separation = min_separation / 1000 if self.filter else 0
            self.is_strict = is_strict
            self.callbacks = {'press': defaultdict(list), 'release': defaultdict(list)}

        def __repr__(self):
            return "\n" + pformat(vars(self), indent=6, width=1)

    class Axes:
        def __init__(self, enabled, curve):
            self.enabled = enabled
            self.curve = curve

        def __repr__(self):
            return "\n" + pformat(vars(self), indent=6, width=1)

    class Hats:

        def __init__(self, enabled):
            self.enabled = enabled

        def __repr__(self):
            return "\n" + pformat(vars(self), indent=6, width=1)


# Functions

# execute function after delay (via threading)
def defer(time, func, *args, **kwargs):
    timer = threading.Timer(time, func, args, kwargs)
    timer.start()


# write to log (optionally as ~two columns)
def log(*args, gutter=80, **kwargs):
    the_string = ""
    for i, arg in enumerate(args):
        if isinstance(arg, str):
            the_string += (arg + " ").ljust(gutter, ".") if i == 0 and len(args) > 1 else arg
        else:
            the_string += pformat(arg, **kwargs)

    gremlin.util.log(the_string)


# Scale the given value from the scale of src to the scale of dst.
def map_value(val, src, dst):
    return ((clamp_value(val, *src) - src[0]) / (src[1] - src[0])) * (dst[1] - dst[0]) + dst[0]


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
ui_button_latency = IntegerVariable("            Latency: Wait for <ms> to evaluate the press",
                                    "Time (in ms) to wait before deciding if ghost input before sending to vJoy? Lower = More Ghosting, Higher = Less Ghosting. Default: 35ms",
                                    35, 1, 500)
ui_button_max_concurrent = IntegerVariable(
    "            Maybe Ghost: If more than <#> buttons are pressed simultaneously",
    "How many buttons pressed *at once* (within the wait time) are allowed (on a single device)? Lower = Less Ghosting, Higher = More Ghosting. Default: 1",
    1, 1, 10)
ui_button_min_separation = IntegerVariable(
    "            Maybe Ghost: If any single button press is closer than <ms> apart",
    "Timespan (in ms) between buttons that should trigger a Ghost filtering (even if it was registered as a single press)? Lower = More Ghosting, Higher = Less Ghosting. Default: 10ms",
    10, 1, 1000)
ui_button_is_strict = BoolVariable(
    "            Strict Mode: Prevent a button even if it is still held down after the Wait Time?",
    "Ghost Presses tend to release immediately--otherwise, tries to interpret as a real press. On = Less Ghosting, Off = More Ghosting. Default: On",
    True)
ui_axis_remapping = BoolVariable("> Enable Axis Remapping?",
                                 "Actively remap axes? Disable if remapping them through JG GUI", True)
ui_axis_curve = BoolVariable("    -  Smooth Response Curve?",
                             "If Axis Remapping, adds an S curve to the vJoy output, otherwise linear",
                             True)
ui_hat_remapping = BoolVariable("> Enable Hat Remapping?",
                                "Actively remap hats? Disable if remapping them through JG GUI", True)
ui_logging_enabled = BoolVariable("Enable Logging?", "Output useful debug info to log (Recommended)", True)
ui_is_debug = BoolVariable("  -  Debugging Mode",
                           "Logs all button presses (Recommended only if Ghost Inputs are still getting through... tweak Wait Time / Minimum based on the log results). Default: Off",
                           False)
ui_summary_key = StringVariable("  -  Generate a Summary with Key",
                                "Which keyboard key to press to get a Ghost Input summary breakdown in the log?",
                                "f8")

# Grab general user config
settings = Settings(
    buttons={
        "enabled": ui_is_button_remapping.value,
        "filter": ui_is_button_filtering.value,
        "latency": ui_button_latency.value,
        "max_concurrent": ui_button_max_concurrent.value,
        "min_separation": ui_button_min_separation.value,
        "is_strict": ui_button_is_strict.value
    },
    axes={
        "enabled": ui_axis_remapping.value,
        "curve": ui_axis_curve.value
    },
    hats={
        "enabled": ui_hat_remapping.value
    },
    logging=ui_logging_enabled.value,
    debug=ui_is_debug.value,
    summary_key=ui_summary_key.value
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
log("   This plugin attempts to recognize those characteristics and actively block any presses that seem to match them.")
log("   You can customize the parameters to distinguish between those symptoms and your actual, real button presses (based on you own play style).")

log("")
log("Current Settings:")
log("   Button Filtering Threshold", str(settings.buttons.max_concurrent) + " buttons")
log("   Button Filtering Wait Time", str(int(settings.buttons.latency * 1000)) + " millisecond evaluation buffer")
log("   Button Filtering Minimum",
    str(int(settings.buttons.min_separation * 1000)) + " millisecond button event separation")
log("   Debugging mode", "Enabled" if settings.debug else "Disabled")
if settings.debug:
    log("      -   Event Code Descriptions")
    log("              LGPB", "Long Ghost Press Blocked")
    log("              SGPB", "Short Ghost Press Blocked")
    log("              LGRB", "Long Ghost Release Blocked")
    log("              SGRB", "Short Ghost Release Blocked")
    log("              LPA", "Long Press Allowed")
    log("              SPA", "Short Press Allowed")
    log("              LRA", "Long Release Allowed")
    log("              SRA", "Short Release Allowed")

# Output VJoy configuration to log, to show Windows (GUIDs) <-> Joystick Gremlin (Vjoy IDs) assignment
log("")
log("The following VJoy devices were detected:")
for vjoy in vjoy_devices:
    log("   VJoy #" + str(vjoy.vjoy_id), str(vjoy.device_guid))

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
