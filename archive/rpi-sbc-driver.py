#!/usr/bin/python3
from os import system, name
from time import sleep
import usb.core
import usb.util
import threading
import re
import array as arr


class SelfRefDict(dict):
  def __getitem__(self, key):
    print(f"SelfRefDict(self: {self}, key: {key}, dict: {dict} ) called.")
    val = dict.__getitem__(self, key)
    return callable(val) and val(self) or val


    
class SBC_Core:
  def __init__(self):
    print(f"***__init__(self) called.")  
    # data-packet legends
    self.PacketModel = ["Const_00", "SBC_Id", "Buttons0", "Buttons1", "Buttons2", "Buttons3", "Buttons4", "Const_01", "Aiming_X1", "Aiming_X2", "Aiming_Y1", "Aiming_Y2", "Rotation1", "Rotation2", "Sight_X1", "Sight_X2", "Sight_Y1", "Sight_Y2", "S_Bias", "Sidestep", "B_Bias", "Brake", "T_Bias", "Throttle", "Tuner_Dial", "Gear"]
    #Properties - settings
    # 0a7b:d000
    self.VID = 0x0a7b
    self.PID = 0xd000
    self.INTERFACE_SBC = 0
    self.SETTING_SBC = 0
    self.ENDPOINT_READER = 0
    self.ENDPOINT_WRITER = 1
    self.INTERFACE = 0
    # Properties
    self.Configuration = None
    self.Dev = None
    self.Endpoint_Reader = None
    self.Endpoint_Writer = None
    # current read, previous read
    self.Buffer = [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    self.IoMap = [
       {"Name" : "RightJoythumb_trigger",     "Value" : lambda : self.Bit("Buttons0", 5), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "RightJoyfinger_trigger",    "Value" : lambda : self.Bit("Buttons0", 6), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "Eject",                     "Value" : lambda : self.Bit("Buttons0", 4), "Led" : lambda : 3, "Action" : None }
      ,{"Name" : "CockpitHatch",              "Value" : lambda : self.Bit("Buttons0", 3), "Led" : lambda : 4, "Action" : None }
      ,{"Name" : "Ignition",                  "Value" : lambda : self.Bit("Buttons0", 2), "Led" : lambda : 5, "Action" : None }
      ,{"Name" : "Start",                     "Value" : lambda : self.Bit("Buttons0", 1), "Led" : lambda : 6, "Action" : None }
      ,{"Name" : "MmcOpenClose",              "Value" : lambda : self.Bit("Buttons0", 0), "Led" : lambda : 7, "Action" : None }
      ,{"Name" : "MmcMapZoomInOut",           "Value" : lambda : self.Bit("Buttons1", 3), "Led" : lambda : 8, "Action" : None }
      ,{"Name" : "MmcModeSelect",             "Value" : lambda : self.Bit("Buttons1", 4), "Led" : lambda : 9, "Action" : None }
      ,{"Name" : "MmcSubMonitor",             "Value" : lambda : self.Bit("Buttons1", 5), "Led" : lambda : 10, "Action" : None }
      ,{"Name" : "MmcZoomIn",                 "Value" : lambda : self.Bit("Buttons1", 6), "Led" : lambda : 11, "Action" : None }
      ,{"Name" : "MmcZoomOut",                "Value" : lambda : self.Bit("Buttons1", 7), "Led" : lambda : 12, "Action" : None }
      ,{"Name" : "FxForcastShootingSystem",   "Value" : lambda : self.Bit("Buttons1", 2), "Led" : lambda : 13, "Action" : None }
      ,{"Name" : "FxManipulator",             "Value" : lambda : self.Bit("Buttons1", 1), "Led" : lambda : 15, "Action" : None }
      ,{"Name" : "FxLineColourChange",        "Value" : lambda : self.Bit("Buttons1", 0), "Led" : lambda : 16, "Action" : None }
      ,{"Name" : "FxTankDetach",              "Value" : lambda : self.Bit("Buttons2", 4), "Led" : lambda : 20, "Action" : None }
      ,{"Name" : "FxOverride",                "Value" : lambda : self.Bit("Buttons2", 3), "Led" : lambda : 21, "Action" : None }
      ,{"Name" : "FxNightScope",              "Value" : lambda : self.Bit("Buttons2", 2), "Led" : lambda : 22, "Action" : None }
      ,{"Name" : "FxFunctionF1",              "Value" : lambda : self.Bit("Buttons2", 1), "Led" : lambda : 23, "Action" : None }
      ,{"Name" : "FxFunctionF2",              "Value" : lambda : self.Bit("Buttons2", 0), "Led" : lambda : 24, "Action" : None }
      ,{"Name" : "FxFunctionF3",              "Value" : lambda : self.Bit("Buttons3", 7), "Led" : lambda : 25, "Action" : None }
      ,{"Name" : "ToggleOxygenSupply",        "Value" : lambda : self.Bit("Buttons4", 5), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "ToggleFilter",              "Value" : lambda : self.Bit("Buttons4", 4), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "ToggleFuelFlowRate",        "Value" : lambda : self.Bit("Buttons4", 3), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "ToggleBufferMaterial",      "Value" : lambda : self.Bit("Buttons4", 2), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "ToggleVTLocation",          "Value" : lambda : self.Bit("Buttons4", 1), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "Comm1",                     "Value" : lambda : self.Bit("Buttons3", 3), "Led" : lambda : 29, "Action" : None }
      ,{"Name" : "Comm2",                     "Value" : lambda : self.Bit("Buttons3", 2), "Led" : lambda : 30, "Action" : None }
      ,{"Name" : "Comm3",                     "Value" : lambda : self.Bit("Buttons3", 1), "Led" : lambda : 31, "Action" : None }
      ,{"Name" : "Comm4",                     "Value" : lambda : self.Bit("Buttons3", 0), "Led" : lambda : 32, "Action" : None }
      ,{"Name" : "Comm5",                     "Value" : lambda : self.Bit("Buttons4", 7), "Led" : lambda : 33, "Action" : None }
      ,{"Name" : "WcWashing",                 "Value" : lambda : self.Bit("Buttons2", 5), "Led" : lambda : 17, "Action" : None }
      ,{"Name" : "WcExstinguisher",           "Value" : lambda : self.Bit("Buttons2", 6), "Led" : lambda : 18, "Action" : None }
      ,{"Name" : "WcChaff",                   "Value" : lambda : self.Bit("Buttons2", 7), "Led" : lambda : 19, "Action" : None }
      ,{"Name" : "WcMain",                    "Value" : lambda : self.Bit("Buttons3", 4), "Led" : lambda : 26, "Action" : None }
      ,{"Name" : "WcSub",                     "Value" : lambda : self.Bit("Buttons3", 5), "Led" : lambda : 27, "Action" : None }
      ,{"Name" : "WcMagazineChange",          "Value" : lambda : self.Bit("Buttons3", 6), "Led" : lambda : 28, "Action" : None }
      ,{"Name" : "LeftJoyRotation",           "Value" : lambda : int(format(self.Byte("Rotation1") + self.Byte("Rotation2"),'d')), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "LeftJoySightX",             "Value" : lambda : int(format(self.Byte("Sight_X1") + self.Byte("Sight_X2"),'d')), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "LeftJoySightY",             "Value" : lambda : int(format(self.Byte("Sight_Y1") + self.Byte("Sight_Y2"),'d')), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "RightJoyAimingX",           "Value" : lambda : int(format(self.Byte("Aiming_X1") + self.Byte("Aiming_X2"),'d')), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "RightJoyAimingY",           "Value" : lambda : int(format(self.Byte("Aiming_Y1") + self.Byte("Aiming_Y2"),'d')), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "Tuner",                     "Value" : lambda : self.Byte("Tuner_Dial"), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "Gear",                      "Value" : lambda : self.ComputeGearPosition(self.Byte("Gear")), "Led" : lambda : 36 + self.ComputeGearPosition(self.Byte("Gear")), "Action" : None, "Gears" : {"R" : 35, "N" : 36, "1" : 37, "2" : 38, "3" : 39, "4" : 40, "5" : 41} }
      ,{"Name" : "SidestepPedalDriftOffset",  "Value" : lambda : self.ComputeDriftOffset("Sidestep", "SidestepPedalDriftOffset"), "Led" : lambda : None, "Action" : None, "buffer" : None }
      ,{"Name" : "SidestepPedal",             "Value" : lambda : self.ComputePedalValue("Sidestep", "SidestepPedalDriftOffset", "S"), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "BrakePedalDriftOffset",     "Value" : lambda : self.ComputeDriftOffset("Brake", "BrakePedalDriftOffset"), "Led" : lambda : None, "Action" : None, "buffer" : None }
      ,{"Name" : "BrakePedal",                "Value" : lambda : self.ComputePedalValue("Brake", "BrakePedalDriftOffset", "B"), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "ThrottlePedalDriftOffset",  "Value" : lambda : self.ComputeDriftOffset("Throttle", "ThrottlePedalDriftOffset"), "Led" : lambda : None, "Action" : None, "buffer" : None }
      ,{"Name" : "ThrottlePedal",             "Value" : lambda : self.ComputePedalValue("Throttle", "ThrottlePedalDriftOffset", "T"), "Led" : lambda : None, "Action" : None }
      ,{"Name" : "SBC_Active",                "Value" : lambda : self.Bit("Buttons4", 0), "Led" : lambda : None, "Action" : None }
      ] #/IoMap
    #
    self.LedMap = [v["Led"]() for k,v in enumerate(self.IoMap) if v["Led"]() is not None] + [v for k,v in [v["Gears"] for k,v in enumerate(self.IoMap) if "Gears" in v][0].items()]
#    self.LedBuffer = {k:0 for k,v in enumerate(self.IoMap) if v["Led"]() is not None} + {k:0 for k,v in [v["Gears"] for k,v in enumerate(self.IoMap) if "Gears" in v][0].items()}

    self.LedBuffer = {k:0 for k,v in enumerate(self.IoMap) if v["Led"]() is not None}
    self.LedBuffer.update({k:0 for k,v in [v["Gears"] for k,v in enumerate(self.IoMap) if "Gears" in v][0].items()})


    print(f"* self.LedMap: {self.LedMap}")
    print(f"* self.LedBuffer: {self.LedBuffer}")
    print(f"Ready.")
    
  # range: 0-255 maybe -127-128 if signed
  def Byte(self, packet_byte):
    print(f"***Byte(self, packet_byte: {packet_byte}) called.")  
    return int(self.Buffer[self.PacketModel.index(packet_byte)])

  def ByteAsStr(self, packet_byte):
    print(f"***ByteAsStr(self, packet_byte: {packet_byte}) called.")  
    return format(self.Byte(packet_byte),'08b') 

  # range: 0 or 1
  def Bit(self, packet_byte, packet_bit):
    print(f"***FindIoIndex(self, packet_byte: {packet_byte}, packet_bit: {packet_bit}) called.")  
    return int(format(self.Buffer[self.PacketModel.index(packet_byte)],'08b')[packet_bit])

  def BitAsStr(self, packet_byte, packet_bit):
    print(f"***BitAsStr(self, packet_byte: {packet_byte}, packet_bit: {packet_bit}) called.")  
    return self.Byte(packet_byte)[packet_bit]

  def FindIoIndex(self, control):
    print(f"***FindIoIndex(self, control: {control}) called.")  
    for (key, value) in enumerate(self.IoMap):
      if value['Name'] == control:
        return key
    return None
      
  def FindLedIoIndex(self, led_id):
    print(f"* FindLedIoIndex(led_id:{led_id}) called.")
    for (key, value) in enumerate(self.IoMap):
      if value['Led']() == led_id:
        return key
    return None
      
  def FindLedIoIndexByName(self, led_name):
    print(f"* FindLedIoIndexByName(led_id:{led_id}) called.")
    for (key, value) in enumerate(self.IoMap):
      if value['Name'] == led_name:
        if 'Led' in value:
          if value['Led']() is not None:
            return key
    return None
      
  # Endpoints
  def SetEndpointReader(self):
    print(f"***SetEndpointReader(self) called.")  
    self.Endpoint_Reader = self.Dev[0][(self.INTERFACE_SBC, self.SETTING_SBC)][self.ENDPOINT_READER]

  def SetEndpointWriter(self):
    print(f"***SetEndpointWriter(self) called.")  
    self.Endpoint_Writer = self.Dev[0][(self.INTERFACE_SBC, self.SETTING_SBC)][self.ENDPOINT_WRITER]
    
  def SetDevConfiguration(self):
    print(f"***SetDevConfiguration(self) called.")
    self.Configuration = self.Dev.get_active_configuration()

  def SetLedState(self, led_id, intensity, send_state = True):
    print(f"***SetLedState(led_id: {led_id}, intensity: {intensity}, send_state: {send_state}) called.")
    
    #if led is None: return

    hex_pos = int(led_id) % 2
    print(f"* hex_pos: {hex_pos}")
    byte_pos = int(led_id) - hex_pos / 2
    print(f"* byte_pos: {byte_pos}")

    intensity = 0x0f if intensity >= 0x0f else intensity
    intensity = 0x00 if intensity <= 0x00 else intensity

    led = self.LedBuffer[led_id]
    
    if led_id == 34:
      print(f"Skilling element {led_id}.")
      return

    print(f"* self.LedBuffer: {self.LedBuffer}")
    print(f"* led: {led}")

    self.LedBuffer[led_id] &= int(0x0f if hex_pos == 1 else 0xf0)
    print(f"SetLedState:hex_pos: {hex_pos}, byte_pos: {byte_pos}, intensity: {intensity}, self.LedBuffer[led_id]: {self.LedBuffer[led_id]}")
    self.LedBuffer[led_id] += int(intensity * (0x10 if hex_pos == 1 else 0x01))
    print(f"SetLedState:hex_pos: {hex_pos}, byte_pos: {byte_pos}, intensity: {intensity}, self.LedBuffer[led_id]: {self.LedBuffer[led_id]}")
    

    if send_state:
      self.DevWriteLedState()

  def ComputeDriftOffset(self, pedal, driftOffset):
    print(f"***ComputeDriftOffset(self, pedal: {pedal}, driftOffset: {driftOffset}) called.")  
    driftOffsetIndex = self.FindIoIndex(driftOffset)
    self.IoMap[driftOffsetIndex]["buffer"] = self.Byte(pedal) if (self.IoMap[driftOffsetIndex]["buffer"] == -1 or self.IoMap[driftOffsetIndex]["buffer"] is None) else self.IoMap[driftOffsetIndex]["buffer"]

  def ComputePedalValue(self, pedal, driftOffset, bias):
    print(f"***ComputeDriftOffset(self, pedal: {pedal}, driftOffset: {driftOffset}, bias: {bias}) called.")  
    driftOffsetIndex = self.FindIoIndex(driftOffset)
    return (lambda x, y: x - self.IoMap[driftOffsetIndex]["buffer"] if x + (-1 * self.IoMap[driftOffsetIndex]["buffer"]) > -1 and (y == 64 or y ==128 or y == 0 and y != 192) else x)(self.Byte(pedal), self.Byte(f"{bias}_Bias"))

  def ComputeGearPosition(self, gear):
    print(f"* ComputeGearPosition(self, gear: {gear}) called.")
    return int(re.sub("255","-1", re.sub("254","-0", format(gear,'d'))))

#class SBC_Device_IO(SBC_base):
  # -------
  # Methods
  # -------
  def DevOpen(self):
    print(f"* DevOpen(self) called.")
    self.Dev = usb.core.find(idVendor=self.VID, idProduct=self.PID)
    # if the OS kernel already claimed the device, which is most likely true
    # thanks to http://stackoverflow.com/questions/8218683/pyusb-cannot-set-configuration
    if self.Dev.is_kernel_driver_active(self.INTERFACE) is True:
      # tell the kernel to detach
      print(f"*** Disengaging kernel mode driver for user mode driver")
      self.Dev.detach_kernel_driver(self.INTERFACE)
      # claim the device
      print(f"*** Engaging user mode driver")
      usb.util.claim_interface(self.Dev, self.INTERFACE)

  def DevReset(self):
    print(f"* DevReset(self) called.")
    self.Dev.reset()

  def DevClose(self):
    print(f"* DevClose(self) called.")
    self.terminate = True

  def DevRead(self):
    print(f"* DevRead(self) called.")
    try:
      self.Buffer = self.Dev.read(self.Endpoint_Reader.bEndpointAddress,self.Endpoint_Reader.wMaxPacketSize)

    except usb.core.USBError as e:
      self.Buffer = "0000000000000000000000000000000010000000"
      if e.args == ('Operation timed out',):
        print(f"*****Read error: {e.args}.")
    print(f"* self.Buffer: {self.Buffer}")
    try:
      self.Buffer = self.Dev.read(self.Endpoint_Reader.bEndpointAddress, self.Endpoint_Reader.wMaxPacketSize)
      
    except usb.core.USBError as e:
      if e.args == ('Operation timed out',):
        print(f"*****( Read error: {e.args}.")
            
    return self.Buffer

  def DevWrite(self, cmd):
    print(f"***DevWrite(self, cmd: {cmd}) called.")  
    self.Endpoint_Writer(cmd)

  def DevWriteLedState(self):
    print(f"***DevWriteLedState(self) called.")  
    ledBufferData = arr.array("B",[])

    for ledIndex in self.LedMap:
      print(f"--ledIndex:{ledIndex}")
      print(f"--self.LedBuffer[{ledIndex}]: {self.LedBuffer[ledIndex]}")
      ledBufferData.append(self.LedBuffer[ledIndex])

    self.DevWrite(ledBufferData)

  def GetLedState(self, led_id):
    print(f"* GetLedStavte(led_id:{led_id}) called.")
    led = self.LedBuffer[led_id]
    
    if not led: return -1
    intensity = led["intensity" ]
    
    print(f"** intensity: {intensity}")
    return intensity & (0x0F if hex_pos == 1 else 0xF0) /  (0x01 if hex_pos == 1 else 0x10)

  def DevLedHandlerThread(self):
    print(f"* DevLedHandlerThread(self) called.")
    self.DevWriteLedState()

  def DevRun(self):
    print(f"* DevRun(self) called.")
    #quit flag
    self.terminate = False
    # init
    self.DevOpen()
    self.DevReset()
    self.SetDevConfiguration()
    self.SetEndpointReader()
    self.SetEndpointWriter()
    # Run handlers
    self.DevTask()
    # End of line.S
    print(f"stop.")
    exit(0)

  def DevTask(self):
    print(f"* DevTask(self) called.")

    while self.terminate is False:
      self.DevControlHandlerThread()
      sleep(5)
      self.DevLedHandlerThread()

      """  def DevTask(self):
    inLock = threading.Lock()
    outLock = threading.Lock()
    
    self.threadIn = threading.Thread(target=self.DevControlHandlerThread, name="controlHandler", args=(inLock,))
    #self.threadIn.daemon = True
    #self.threadIn.setDaemon()
    
    self.threadOut = threading.Thread(target=self.DevLedHandlerThread, name="ledHandler", args=(outLock,))
    #self.threadOut.daemon = True
    #self.threadOut.setDaemon()
    
    self.threadIn.start()
    self.threadOut.start()

    while self.terminate is False:
      # runs I/O input polling thread
      self.threadIn.run()
      self.threadIn.join()
      # runs I/O LED output send thread      
      self.threadOut.run()
      self.threadOut.join()
    """

  def DevControlHandlerThread(self):
    print(f"* DevControlHandlerThread(self) called.")
    self.DevRead()
    #for control in self.IoMap:
      #print(f"{control['Name']} => {control['Value']()}")
    #  control['Value']()
    self.HandleGearIndicators()
      
  def HandleGearIndicators(self):
    print(f"* HandleGearIndicators(self) called.")
    LEDOFF = 0x0
    LEDFULLON = 0xf
    gear = self.IoMap[self.FindIoIndex("Gear")]
    gearIndicators = gear["Gears"]

    for gearIndicator in gearIndicators.items():
      #gearIndicatorName = gearIndicator[0]
      gearIndicatorLedId = gearIndicator[1]   
      self.SetLedState(gearIndicatorLedId, LEDOFF, True)
    
    self.SetLedState(gear["Led"](), LEDFULLON, True)

  def LedPulser(self):
    print(f"* LedPulser(self) called.")
    LEDOFF = 0x0
    LEDFULLON = 0xf
    FADE_DELAY = 0.7

    for x in range(2):
      for ledId in self.LedMap:
        self.SetLedState(led_id, 0x00, True)
        #fade-in
        for intensity in range(0x0f):
          self.SetLdState(ledId, intensity, True)
          sleep(FADE_DELAY)
    #on
    self.set_led_state(ledId, 0x0f, True)
    sleep(fade_delay)

    #fade-out
    for intensity in range(0x0f, -1, -1):
     self.SetLdState(ledId, intensity, True)
     sleep(FADE_DELAY)
    #off
    self.SetLedState(ledId, 0x00, True)

  def LedStartupSequence(self):
    self.LedPulser


#class Steel_Battalions_Controller(SBC_Device_IO):
class Steel_Battalions_Controller(SBC_Core):
  pass
#-------------------------------------------------------------------------------

def main():
  print(f"main called.")
  sbc = Steel_Battalions_Controller()
  sbc.DevRun()
  exit(0)

main()
