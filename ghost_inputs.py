import gremlin
import threading
import math
from gremlin.user_plugin import *
from gremlin.util import log

#Plugin UI Configuration
ui_mode = ModeVariable("Apply Filtering to","The mode to apply this filtering to")
ui_is_debug = BoolVariable("Verbose Logging","Log every legitimate button press (instead of just Ghost Inputs)", False)
ui_device_name = StringVariable("Physical Device Name","What to call this device in the log?","Stick")
ui_physical_device = StringVariable("Physical Device GUID","Copy and paste from Tools > Device Information")
ui_virtual_device = IntegerVariable("Virtual Device ID","Specify the vJoy device to map the stick to (based on the order of their indexing in Tools > Device Information",1,1,16)
ui_button_filtering = BoolVariable("Button Filtering Enabled?","Actively filter ghost input?", True)
ui_button_threshold = IntegerVariable("Button Limit Threshold","How many *buttons* pressed at once (within the Monitoring Timespan) constitute a Ghost Input (on a single device)? Default: 2",2,0,100)
ui_button_timespan = IntegerVariable("Button Monitoring Timespan","How many ticks (16.66ms) to wait after a button press before checking for ghost input? Default: 5",5,1,20)

#class for each physical joystick device, for filtering and mapping
class FilteredDevice :
    def __init__(self,
                    #device
                    name, mode, device_guid, vjoy_id,
                    #buttons
                    button_filtering, button_timespan, button_threshold,
                    #variables
                    is_debug,
                    tick_len = .01666, max_buttons = 36#, max_axes = 8
                ):
        
        self.name = name
        self.mode = mode
        self.is_debug = is_debug
        self.device_guid = device_guid
        self.vjoy_id = vjoy_id
        self.button_filtering = button_filtering
        self.button_timespan = [math.ceil(float(button_timespan)/2),math.floor(float(button_timespan)/2)] if button_filtering else [0,0]
        self.button_threshold = button_threshold
        self.tick_len = tick_len
        self.max_buttons = max_buttons
        
        self.concurrent_presses = 0
        
        #create the decorator
        self.decorator = gremlin.input_devices.JoystickDecorator(self.name, self.device_guid, self.mode)
        
        #for each button on the device
        for i in range(1,self.max_buttons + 1):
            #add a decorator function for when that button is pressed
            @self.decorator.button(i)
            #pass that info to the function that will check other button presses
            def callback(event, vjoy, joy):        
                #increment total buttons counter for this device (if this is a press)
                if event.is_pressed:    
                    self.increment()
                           
                #wait the first half of the delay timespan (set number of ticks), then check for ghost inputs
                self.defer(self.button_timespan[0], self.filter_the_button, [event,vjoy,joy])
                      
        #Log that device is ready
        log("Ghost Input filtering on Profile [" + self.mode + "]")
        log("  for Physical Device \"" + self.name + "\" [" + self.device_guid + "]")
        log("  mapping to Virtual Device " + str(self.vjoy_id))
        if self.button_filtering:
            log("    ... Button Filtering enabled")
        if self.is_debug:
            log("    ... Verbose logging enabled")
    
    def increment(self):
        self.concurrent_presses += 1
        
    def decrement(self):
        self.concurrent_presses -= 1
        
    def defer(self, ticks, func, params = []):
        timer = threading.Timer(ticks * self.tick_len, func, params)
        timer.start()
    
    #checks total number of buttons pressed, every time a new button is pressed within the configured timespan
    #and maps the physical device to the virtual device if NOT a ghost input
    def filter_the_button(self,event,vjoy,joy):   
                
        #if <threshold> or more buttons (including this callback's triggered button) are pressed, this is likely a ghost input
        is_ghost = self.concurrent_presses >= self.button_threshold
         
        #if this is a ghost input on key press (not release)
        if event.is_pressed and is_ghost and self.button_filtering:
            #log it
            log("> GHOST INPUT blocked! " + self.name + " button " + str(event.identifier) + " was pressed (" + str(self.concurrent_presses) + " buttons at once)")
        else:            
            #otherwise, get the current state (after this much delay)
            still_pressed = joy[event.device_guid].button(event.identifier).is_pressed
            #and update the virtual joystick
            vjoy[self.vjoy_id].button(event.identifier).is_pressed = still_pressed
            
            #log legitimate press, if debugging
            if self.is_debug and still_pressed:
                log("USER pressed: " + self.name + " button " + str(event.identifier))
                
        #after half the delay and evaluation, delay the next half, then decrement the pressed counter (if this was a press and not a release)
        #enough time will have passed that this callback's button should no longer be used to determine a Ghost Input
        if event.is_pressed:
            self.defer(self.button_timespan[1], self.decrement)
            
#grab user configuration
name = ui_device_name.value
mode = ui_mode.value
guid = ui_physical_device.value
vjoy_id = ui_virtual_device.value
is_debug = bool(ui_is_debug.value) #joystick gremlin has an issue with BoolVariable persistance(?)
button_filtering = bool(ui_button_filtering.value) #joystick gremlin has an issue with BoolVariable persistance(?)
button_timespan = ui_button_timespan.value
button_threshold = ui_button_threshold.value

#Initialize filtered device (which creates decorators to listen for and filter input)
if guid:
    filtered_device = FilteredDevice(
        name, 
        mode, 
        guid, 
        vjoy_id, 
        button_filtering, 
        button_timespan, 
        button_threshold, 
        is_debug
    )