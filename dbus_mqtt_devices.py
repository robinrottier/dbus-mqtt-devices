#!/usr/bin/env python

"""
This Venus GX Driver works in concert with the Victron dbus-mqtt gateway. It 
enables devices (such as Arduino microcontrollers or Raspberry Pi) to self 
register to the dbus over MQTT, without needing additional dedicated custom 
drivers to be developed and deployed.

It uses a pair of MQTT topics under the "devices/*" namespace to establish the 
registration, using the following protocol:

1)  When a device initialises, it does 2 things:
	a) subscribes to a topic "device/<client id>/DeviceInstance"
	b) publishes a status message on the MQTT topic 
		"device/<client id>/Status". 
		The payload is a json object containing :
    	{ "clientid": <client id>, "connected": <either 1 or 0>, "services": [<a dictionary or services that this device wants to use>] }
   	for example:
		{ "clientid": "fe001", "connected": 1, "services": {"t1": "temperature", "t2": "temperature"}}
2)	The driver will the use this infomation to 
		- obtain a numeric device instance (for VRM), 
		- set up local settings for persistent storage of some attributes
		- register the device on the dbus, 
		- set up the appropriate dbus paths for the service type 
		  (i.e. temperature sensor can provide Temperature, Pressure and Humidity)
3)	The driver publishes a DeviceInstance message under the same MQTT Topic
	namespace. This is the topic the device subscribed to in 1a). The 
	DeviceInstance message contains the numeric device instances (one for each 
	service) that the device should use when publishing messages for dbus-mqtt
	to process (see 5). For example: 
		Topic: "device/<client id>DeviceInstance"
		Payload: {"t1": 5, "t2":12} 
4)	The device uses the device instance to periodically publish messages to the 
	appropriate dbus-mqtt topics for the service they are providing. 
	For example:
		Topic: "W/<portal id>/temperature/<device instance>/Temperature"
		Payload: { "value": 24.91 }
5) 	When a device disconnects it should notify the driver by publishing a 
	status message with a connected value of 0. With MQTT the preferred
	methos of achieving this is through am MQTT "last will". For example:
		{ "clientid": "fe001", "connected": 0, "services": {"t1": "temperature", "t2": "temperature"}}
	plead note: the contents of the "services" are actually irrelevant as all 
	the device services are cleared by the message

Things to consider:
	- 	The device can have multiple sensors of the same time (e.g. two 
		temperature sensors), each publishing to different dbus-mqtt topics as 
		different device services.
	- 	Each device service will appear separately on the Venus GX device, and 
		each can have a customised name that will show on the display and in 
		VRM.
	- 	Currently this driver only supports temperature services but the 
		protocol and the driver have been designed to be easily extended for 
		other services supported by dbus-mqtt.
	-   A working Arduino Sketch that publishes temperature readings from an 
        Adafruit AHT20 temperature and humidty module using this driver and 
        mqtt-dbus is available at github. etc etc
	
"""

import logging
import argparse
#import dbus
import os
import sys
import signal
import traceback
from functools import partial
from gi.repository import GLib
from dbus.mainloop.glib import DBusGMainLoop

AppDir = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(1, os.path.join(AppDir, 'ext', 'velib_python'))

from logger import setup_logging
from ve_utils import get_vrm_portal_id, exit_on_error, wrap_dbus_value, unwrap_dbus_value

from device_manager import MQTTDeviceManager

VERSION = '0.10'

def dumpstacks(signal, frame):
	import threading
	id2name = dict((t.ident, t.name) for t in threading.enumerate())
	for tid, stack in sys._current_frames().items():
		logging.info ("=== {} ===".format(id2name[tid]))
		traceback.print_stack(f=stack)

def main():
	parser = argparse.ArgumentParser(description='Publishes values from the D-Bus to an MQTT broker')
	parser.add_argument('-d', '--debug', help='set logging level to debug', action='store_true')
	parser.add_argument('-q', '--mqtt-server', nargs='?', default=None, help='name of the mqtt server')
	parser.add_argument('-u', '--mqtt-user', default=None, help='mqtt user name')
	parser.add_argument('-P', '--mqtt-password', default=None, help='mqtt password')
	parser.add_argument('-c', '--mqtt-certificate', default=None, help='path to CA certificate used for SSL communication')
	parser.add_argument('-b', '--dbus', default=None, help='dbus address')
	parser.add_argument('-i', '--init-broker', action='store_true', help='Tries to setup communication with VRM MQTT broker')
	args = parser.parse_args()

	print("-------- dbus_mqtt_devices, v{} is starting up --------".format(VERSION))
	logger = setup_logging(args.debug)

	mainloop = GLib.MainLoop()
	# Have a mainloop, so we can send/receive asynchronous calls to and from dbus
	DBusGMainLoop(set_as_default=True)
	handler = MQTTDeviceManager(
		mqtt_server=args.mqtt_server, ca_cert=args.mqtt_certificate, user=args.mqtt_user,
		passwd=args.mqtt_password, dbus_address=args.dbus,
		init_broker=args.init_broker, debug=args.debug)

	# Quit the mainloop on ctrl+C
	signal.signal(signal.SIGINT, partial(exit, mainloop))

	# Handle SIGUSR1 and dump a stack trace
	signal.signal(signal.SIGUSR1, dumpstacks)

	# Start and run the mainloop
	try:
		mainloop.run()
	except KeyboardInterrupt:
		pass

if __name__ == '__main__':
	main()