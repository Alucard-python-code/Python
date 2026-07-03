#!/usr/bin/env python3
# -*- coding:utf-8 -*-
import socket
import time

s = socket.socket()         # creat socket
host = '192.168.8.203'        # set ip
port = 4196                 # Set port

cmd = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

cmd[5] = 0x06  # Byte length
cmd[6] = 0x01  # Device address
cmd[7] = 0x05  # command

s.connect((host, port))     # connect serve
while True:
    for i in range(30):
        cmd[5] = 0x06  # Byte length
        cmd[6] = 0x01  # Device address
        cmd[7] = 0x05  # command
        cmd[8] = 0
        cmd[9] = i
        cmd[10] = 0xFF
        cmd[11] = 0
        # print(cmd)
        s.send(bytearray(cmd))
        time.sleep(0.2)
        data = s.recv(1024)
        print('[{}]'.format(','.join(hex(x) for x in data)))

    for i in range(30):
        cmd[5] = 0x06  # Byte length
        cmd[6] = 0x01  # Device address
        cmd[7] = 0x05  # command
        cmd[8] = 0
        cmd[9] = i
        cmd[10] = 0
        cmd[11] = 0
        # print(cmd)
        s.send(bytearray(cmd))
        time.sleep(0.2)
        data = s.recv(1024)
        print('[{}]'.format(','.join(hex(x) for x in data)))

#s.close()                   # Close the connectio
