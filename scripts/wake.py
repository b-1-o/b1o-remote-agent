#!/usr/bin/env python3
"""Send a Wake-on-LAN/Wake-on-WLAN magic packet.

Usage:
    python scripts/wake.py 40:1a:58:81:ea:34 192.168.1.255
"""

import socket
import sys


def mac_bytes(mac: str) -> bytes:
    value = mac.replace(":", "").replace("-", "")
    if len(value) != 12:
        raise ValueError("Invalid MAC address")
    return bytes.fromhex(value)


def send_magic_packet(mac: str, broadcast: str) -> None:
    payload = b"\xff" * 6 + mac_bytes(mac) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (broadcast, 9))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: python scripts/wake.py <MAC> <broadcast-ip>"
        )

    send_magic_packet(sys.argv[1], sys.argv[2])
    print("Magic packet sent.")
