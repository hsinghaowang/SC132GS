#!/usr/bin/env python3
"""Visible serial console that also mirrors output to a log file."""

from __future__ import annotations

import argparse
import msvcrt
import pathlib
import sys
import time

import serial


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM5")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()

    log_path = pathlib.Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Shared console: {args.port} @ {args.baud}; log={log_path}", flush=True)
    print("Keyboard input is forwarded to the board. Ctrl+C exits.", flush=True)

    while True:
        try:
            with serial.Serial(args.port, args.baud, timeout=0.05) as uart, log_path.open("ab", buffering=0) as log:
                banner = f"\r\n--- connected {time.strftime('%Y-%m-%d %H:%M:%S')} ---\r\n".encode()
                sys.stdout.buffer.write(banner)
                sys.stdout.buffer.flush()
                log.write(banner)
                while True:
                    incoming = uart.read(4096)
                    if incoming:
                        sys.stdout.buffer.write(incoming)
                        sys.stdout.buffer.flush()
                        log.write(incoming)
                    while msvcrt.kbhit():
                        key = msvcrt.getwch()
                        if key == "\x03":
                            raise KeyboardInterrupt
                        if key in ("\x00", "\xe0"):
                            msvcrt.getwch()
                            continue
                        uart.write(key.encode("utf-8", errors="ignore"))
        except KeyboardInterrupt:
            print("\nShared console stopped.", flush=True)
            return 0
        except (serial.SerialException, OSError) as exc:
            print(f"\rWaiting for {args.port}: {exc}", flush=True)
            time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
