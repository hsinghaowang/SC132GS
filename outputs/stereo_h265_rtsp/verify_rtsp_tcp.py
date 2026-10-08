#!/usr/bin/env python3
"""Probe RTSP/RTP over TCP from Windows without decoding or saving images."""

import argparse
import socket
import struct
import time
from urllib.parse import urlparse


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--stall-seconds", type=float, default=0.0,
                        help="pause reads after PLAY to simulate a slow client")
    parser.add_argument("--show-sdp", action="store_true")
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "rtsp" or not parsed.hostname:
        parser.error("expected rtsp://host[:port]/path")

    sock = socket.create_connection((parsed.hostname, parsed.port or 554), 5)
    if args.stall_seconds:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8192)
    sock.settimeout(2)
    stream = sock.makefile("rb")
    cseq = 0

    def request(method: str, url: str, extra: str = ""):
        nonlocal cseq
        cseq += 1
        message = (
            f"{method} {url} RTSP/1.0\r\n"
            f"CSeq: {cseq}\r\n"
            "User-Agent: stereo-rtsp-probe/1.0\r\n"
            f"{extra}\r\n"
        )
        sock.sendall(message.encode("ascii"))
        status = stream.readline().decode("ascii", "replace").strip()
        headers = {}
        while line := stream.readline():
            if line == b"\r\n":
                break
            key, _, value = line.decode("ascii", "replace").partition(":")
            headers[key.lower()] = value.strip()
        body = stream.read(int(headers.get("content-length", "0")))
        if " 200 " not in status:
            raise RuntimeError(f"{method}: {status} {body[:200]!r}")
        return headers, body

    try:
        _, sdp_bytes = request("DESCRIBE", args.url,
                               "Accept: application/sdp\r\n")
        sdp = sdp_bytes.decode("ascii", "replace")
        if args.show_sdp:
            print(sdp)
        media_section = sdp.split("m=video", 1)
        if len(media_section) != 2 or "H265" not in media_section[1]:
            raise RuntimeError("SDP did not advertise H265 video")
        controls = [line.partition(":")[2].strip()
                    for line in media_section[1].splitlines()
                    if line.startswith("a=control:")]
        if not controls:
            raise RuntimeError("SDP has no video track control URL")
        control = controls[0]
        track_url = (control if control.startswith("rtsp://") else
                     args.url.rstrip("/") + "/" + control)
        headers, _ = request(
            "SETUP", track_url,
            "Transport: RTP/AVP/TCP;unicast;interleaved=0-1\r\n",
        )
        session = headers["session"].split(";", 1)[0]
        request("PLAY", args.url, f"Session: {session}\r\n")

        if args.stall_seconds:
            time.sleep(args.stall_seconds)

        deadline = time.monotonic() + args.seconds
        first_marker = None
        markers = 0
        packets = 0
        next_keepalive = time.monotonic() + 20
        while time.monotonic() < deadline:
            if time.monotonic() >= next_keepalive:
                cseq += 1
                sock.sendall((f"GET_PARAMETER {args.url} RTSP/1.0\r\n"
                              f"CSeq: {cseq}\r\nSession: {session}\r\n\r\n").encode('ascii'))
                next_keepalive = time.monotonic() + 20
            try:
                prefix = stream.read(1)
            except TimeoutError:
                continue
            if prefix != b"$":
                if prefix == b"":
                    raise RuntimeError("RTSP connection closed")
                if prefix == b"R":
                    status = (prefix + stream.readline()).decode('ascii', 'replace')
                    headers = {}
                    while line := stream.readline():
                        if line == b'\r\n':
                            break
                        key, _, value = line.decode('ascii', 'replace').partition(':')
                        headers[key.lower()] = value.strip()
                    stream.read(int(headers.get('content-length', '0')))
                    if ' 200 ' not in status:
                        raise RuntimeError(f'keepalive: {status}')
                    continue
                raise RuntimeError(f"unexpected interleaved prefix {prefix!r}")
            channel, length = struct.unpack("!BH", stream.read(3))
            payload = stream.read(length)
            if len(payload) != length:
                raise RuntimeError("truncated RTP packet")
            if channel == 0 and len(payload) >= 12:
                packets += 1
                if payload[1] & 0x80:
                    markers += 1
                    if first_marker is None:
                        first_marker = time.monotonic()
        elapsed = time.monotonic() - first_marker if first_marker else 0.0
        fps = (markers - 1) / elapsed if elapsed > 0 else 0.0
        print(f"codec=H265 rtp_packets={packets} access_units={markers} "
              f"fps={fps:.2f} over_tcp=True")
        return 0 if markers >= max(1, (args.seconds - 2) * 28) else 1
    finally:
        stream.close()
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
