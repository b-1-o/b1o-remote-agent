import hmac
import json
import os
import re
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAC = os.getenv("B1O_WAKE_MAC", "40:1a:58:81:ea:34")
BROADCAST = os.getenv("B1O_WAKE_BROADCAST", "192.168.1.255")
PORT = int(os.getenv("B1O_WOL_RELAY_PORT", "8787"))
WAKE_PORT = int(os.getenv("B1O_WAKE_PORT", "9"))
TOKEN = os.getenv("B1O_WOL_RELAY_TOKEN", "")

MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}$")


def mac_bytes(value: str) -> bytes:
    if not MAC_RE.fullmatch(value):
        raise ValueError("Invalid MAC address")
    return bytes.fromhex(value.replace(":", "").replace("-", ""))


def send_magic_packet() -> None:
    payload = b"\xff" * 6 + mac_bytes(MAC) * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(payload, (BROADCAST, WAKE_PORT))


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"ok": True, "service": "b1o-wol-relay"})
            return
        self._json(404, {"ok": False})

    def do_POST(self):
        if self.path != "/wake":
            self._json(404, {"ok": False})
            return

        provided = self.headers.get("X-Relay-Token", "")
        if not TOKEN or not hmac.compare_digest(provided, TOKEN):
            self._json(401, {"ok": False, "error": "Unauthorized"})
            return

        try:
            send_magic_packet()
        except Exception as exc:
            self._json(500, {"ok": False, "error": type(exc).__name__})
            return

        self._json(
            200,
            {
                "ok": True,
                "action": "wake",
                "broadcast": BROADCAST,
                "port": WAKE_PORT,
            },
        )

    def log_message(self, fmt, *args):
        return


def main() -> None:
    if not TOKEN:
        raise RuntimeError("B1O_WOL_RELAY_TOKEN is not configured")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"b1o WOL relay listening on 0.0.0.0:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
