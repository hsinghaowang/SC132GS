#!/usr/bin/env python3
"""Read the connected board UART without changing the modem control lines."""
import serial
import time
from pathlib import Path
uart=serial.Serial(port=None,baudrate=115200,timeout=0.1)
uart.dtr=False
uart.rts=False
uart.port='COM5'
uart.open()
try:
    end=time.monotonic()+8
    captured=bytearray()
    while time.monotonic()<end:
        captured.extend(uart.read(4096))
    Path(__file__).with_name('reboot-uart.txt').write_bytes(captured)
    print(captured.decode('utf-8',errors='replace')[-8000:])
finally:
    uart.close()
