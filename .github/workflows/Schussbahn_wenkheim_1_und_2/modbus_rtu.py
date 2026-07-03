#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import socket
import pycrc
import time

s = socket.socket()         # creat socket
host = '192.168.8.203'        # set ip
port = 4196                 # Set port

cmd = [0, 0, 0, 0, 0, 0, 0, 0]

s.connect((host, port))     # connect serve
while True:
    for i in range(8):
        cmd[0] = 0x01   # Device address
        cmd[1] = 0x05   # command
        cmd[2] = 0      # freies bit 
        cmd[3] = i      # Relais nummer 0x00-7
        cmd[4] = 0xFF   # Relais an
        cmd[5] = 0      # freies bit 
        crc = pycrc.ModbusCRC(cmd[0:6])
        cmd[6] = crc & 0xFF
        cmd[7] = crc >> 8
        # print(cmd)
        s.send(bytearray(cmd))
        time.sleep(0.2)
        data = s.recv(1024)
        print('[{}]'.format(','.join(hex(x) for x in data)))

    for i in range(8):
        cmd[0] = 0x01   # Device address
        cmd[1] = 0x05   # command
        cmd[2] = 0      # freies bit 
        cmd[3] = i      # Relais nummer 0x00-7
        cmd[4] = 0      # Relais aus
        cmd[5] = 0      # freies bit 
        crc = pycrc.ModbusCRC(cmd[0:6])
        cmd[6] = crc & 0xFF
        cmd[7] = crc >> 8
        # print(cmd)
        s.send(bytearray(cmd))
        time.sleep(0.2)
        data = s.recv(1024)
        print('[{}]'.format(','.join(hex(x) for x in data)))

s.close()                   # Close the
