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

import logging
log = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

class LansenSerial(object):
    def __init__(self, msgbus, port, speed=115200, reconnect_time=2):
        self._port = port
        self._speed = speed
        self._reconnect_time = reconnect_time
        self._fd = None
        self._msgbus = msgbus
        self._port = port
        self._ioloop = tornado.ioloop.IOLoop.current()
        self._decoder = LansenDecoder(self._fd, self._wmbus_msg_received)
        self._lmbus = Lansen2MBus()
        self._reconnect()

    def _reconnect(self):
        if self._fd:
            self._ioloop.remove_handler(self._fd)
            try:
                self._fd.close()
                self._fd = None
            except Exception as ex:
                log.error("wMBus serial close exception %s", ex)
        if not self._fd:
            try:
                self._fd = serial.Serial(port=self._port, baudrate=self._speed, timeout=0)
            except Exception as ex:
                log.error("wMBus serial open exception %s", ex)
        if self._fd:
            self._ioloop.add_handler(self._fd, self._serial_data_received, self._ioloop.READ)
        else:
            self._ioloop.add_timeout(self._ioloop.time() + self._reconnect_time, self._reconnect)

    def _serial_data_received(self, fd, events):
        try:
            while fd.in_waiting:
                self._decoder._add_byte(fd.read(1))
        except Exception as ex:
            log.error("wMBus serial read exception %s", ex)
            self._reconnect()

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
        self._mbus = None
        self._ioloop.add_callback(self._read_mbus)

    def _read_mbus(self):
        self._executor.submit(self._runner).add_done_callback(self._done)

    def _reconnect(self):
        if self._mbus:
            try:
                self._mbus.disconnect()
                self._mbus = None
            except Exception as ex:
                log.error("MBus close exception %s", ex)
        if not self._mbus:
            try:
                self._mbus = MBus(device=self._port, libpath='./libmbus.so')
            except Exception as ex:
                log.error("MBus create exception %s", ex)
                return
            try:
                self._mbus.connect()
            except Exception as ex:
                log.error("MBus open exception %s", ex)
                self._mbus = None

    def _runner(self):
        id = self._get_next_id()
        if not self._mbus:
            self._reconnect()
        if not self._mbus:
            log.error("MBus reconnect failed")
            return
        try:
            self._mbus.select_secondary_address(id)
        except Exception as ex:
            log.error("MBus select exception %s", ex)
            self._reconnect()
            return
        try:
            self._mbus.send_request_frame(MBUS_ADDRESS_NETWORK_LAYER)
        except Exception as ex:
            log.error("MBus send exception %s", ex)
            self._reconnect()
            return
        try:
            reply = self._mbus.recv_frame()
        except Exception as ex:
            log.error("MBus receive exception %s", ex)
        try:
            reply_data = self._mbus.frame_data_parse(reply)
            xml = self._mbus.frame_data_xml(reply_data)
            self._ioloop.add_callback(self._msgbus.publish, 'mbus_data_received', {'port': self._port, 'id': id, 'xml': xml})
        except Exception as ex:
            log.error("MBus parse exception %s", ex)

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
