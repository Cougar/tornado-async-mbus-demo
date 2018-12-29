#!/usr/bin/env python3
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4

import sys
import time

import itertools

from concurrent.futures import ThreadPoolExecutor

import tornado
import tornado.ioloop

sys.path.append("droidcontroller")
from droidcontroller.msgbus import MsgBus

sys.path.append("python-mbus")
from mbus.MBus import MBus
from mbus.MBusLowLevel import MBUS_ADDRESS_NETWORK_LAYER

sys.path.append("pylansen")
import serial
from pylansen.lansendecoder import LansenDecoder
from pylansen.lansen2mbus import Lansen2MBus
from pylansen.enapimbusdata import ENAPIMbusData

class LansenSerial(object):
    def __init__(self, msgbus, port, speed=115200):
        self._fd = serial.Serial(port=port, baudrate=speed, timeout=0)
        self._msgbus = msgbus
        self._port = port
        self._ioloop = tornado.ioloop.IOLoop.current()
        self._ioloop.add_handler(self._fd, self._serial_data_received, self._ioloop.READ)
        self._decoder = LansenDecoder(self._fd, self._wmbus_msg_received)
        self._lmbus = Lansen2MBus()

    def _serial_data_received(self, fd, events):
        while fd.in_waiting:
            self._decoder._add_byte(fd.read(1))

    def _wmbus_msg_received(self, timestamp, enapi):
        if isinstance(enapi, ENAPIMbusData):
            xml = self._lmbus.getxml(enapi.MbusData)
            self._ioloop.add_callback(self._msgbus.publish, 'lansen_data_received', {'port': self._port, 'timestamp': timestamp, 'rssi': enapi.RSSI, 'xml': xml})

class MBusSerial(object):
    def __init__(self, msgbus, port, interval=1, ids=[]):
        self._msgbus = msgbus
        self._port = port
        self._interval = interval
        self._get_next_id = itertools.cycle(ids).__next__
        self._ioloop = tornado.ioloop.IOLoop.current()
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._ioloop.add_callback(self._read_mbus)

    def _read_mbus(self):
        self._executor.submit(self._runner).add_done_callback(self._done)

    def _runner(self):
        id = self._get_next_id()
        self._mbus = MBus(device=self._port, libpath='./libmbus.so')
        self._mbus.connect()
        self._mbus.select_secondary_address(id)
        self._mbus.send_request_frame(MBUS_ADDRESS_NETWORK_LAYER)
        reply = self._mbus.recv_frame()
        reply_data = self._mbus.frame_data_parse(reply)
        xml = self._mbus.frame_data_xml(reply_data)
        self._ioloop.add_callback(self._msgbus.publish, 'mbus_data_received', {'port': self._port, 'id': id, 'xml': xml})

    def _done(self, _):
        time.sleep(self._interval)
        self._ioloop.add_callback(self._read_mbus)

class DemoController(object):
    import tornado.web  # only for demo page
    def __init__(self, msgbus):
        msgbus.subscribe('demo_token', 'lansen_data_received', 'controller', self._lansen_data_received)
        msgbus.subscribe('demo_token', 'mbus_data_received', 'controller', self._mbus_data_received)
        self._last_msg = None

        tornado.web.Application([(r"/", self.MainHandler, dict(controller=self))]).listen(8888)
        print("web page running at http://127.0.0.1:8888/")

    def _lansen_data_received(self, token, subject, message):
        print("w-MBus ENAPI received: {}".format(str(message)))
        self._last_msg = message

    def _mbus_data_received(self, token, subject, message):
        print("M-Bus data received: {}".format(str(message)))
        self._last_msg = message

    # demo page
    class MainHandler(tornado.web.RequestHandler):
        def initialize(self, controller):
            self._controller = controller
        def get(self):
            self.set_header("Content-Type", "text/plain")
            self.write("Last message:\n{}".format(str(self._controller._last_msg)))

if __name__ == '__main__':
    msgbus = MsgBus()
    controller = DemoController(msgbus)
    LansenSerial(msgbus, "/dev/ttyUSB1", speed=9600)
    MBusSerial(msgbus, "/dev/ttyUSB2", interval=2,  ids=['54880337D6254007', '0123456789ABCDF'])

    tornado.ioloop.IOLoop.current().start()
