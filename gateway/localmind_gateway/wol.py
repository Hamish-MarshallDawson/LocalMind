"""Wake-on-LAN: a UDP broadcast the PC's network card listens for while the PC is off."""
from __future__ import annotations

import re
import socket


def magic_packet(mac: str) -> bytes:
    """Six 0xFF bytes, then the MAC address sixteen times."""
    digits = re.sub(r"[^0-9A-Fa-f]", "", mac)
    if len(digits) != 12:
        raise ValueError(f"{mac!r} isn't a MAC address (expected 12 hex digits, like AA:BB:CC:DD:EE:FF)")
    return b"\xff" * 6 + bytes.fromhex(digits) * 16


def wake(mac: str, broadcast: str = "255.255.255.255", port: int = 9, repeat: int = 3) -> None:
    """Send the packet a few times: it's UDP, and a switch waking up can drop the first one.

    It has to be sent from the PC's own network (the gateway box is on the same LAN), because
    broadcasts don't cross routers or Tailscale.
    """
    packet = magic_packet(mac)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(repeat):
            sock.sendto(packet, (broadcast, port))
