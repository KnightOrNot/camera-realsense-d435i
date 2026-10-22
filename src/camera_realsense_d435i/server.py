"""Loopback HTTP control, MJPEG preview and lossless depth snapshots."""

from __future__ import annotations

import io
import json
import signal
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .camera import Configuration, devices
from .manager import CaptureManager
from .web import PAGE


class CameraHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address: tuple[str, int], manager: CaptureManager):
        self.manager = manager
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: CameraHTTPServer

    def log_message(self, *_args: Any) -> None:
        # Streaming/status polling must not grow a log line per frame.
        pass

    def _response(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, value: Any) -> None:
        self._response(
            code,
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode(),
            "application/json",
        )

    def do_POST(self) -> None:
        try:
            # Browser mutations use JSON and same-origin fetch; no permissive CORS.
            if self.headers.get_content_type() != "application/json":
                raise ValueError("POST requires application/json")
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                self._json(403, {"error": "Cross-origin camera control is not allowed"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("JSON body size must be 1..4096 bytes")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            if self.path == "/api/start":
                self._json(202, self.server.manager.start(body))
            elif self.path == "/api/stop":
                self._json(200, self.server.manager.stop())
            elif self.path == "/api/record/start":
                self._json(202, self.server.manager.start_recording(body))
            elif self.path == "/api/record/stop":
                self._json(
                    200,
                    self.server.manager.stop_recording(
                        complete=body.get("complete", True),
                        reason=body.get("reason"),
                    ),
                )
            else:
                self._json(404, {"error": "Unknown endpoint"})
        except (ValueError, TypeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(409, {"error": str(exc)})

    def do_GET(self) -> None:
        headers_sent = False
        try:
            request = urlsplit(self.path)
            path, manager = request.path, self.server.manager
            if path == "/":
                self._response(200, PAGE.encode(), "text/html; charset=utf-8")
            elif path in ("/api/status", "/api/health"):
                self._json(200, manager.status())
            elif path == "/api/devices":
                profiles = parse_qs(request.query).get("profiles") == ["1"]
                self._json(200, {"devices": devices(profiles)})
            elif path == "/api/record/status":
                self._json(200, manager.recorder.status())
            elif path == "/api/record/frames":
                query = parse_qs(request.query)
                after = int(query.get("after", ["-1"])[0])
                limit = int(query.get("limit", ["1000"])[0])
                self._json(200, {"frames": manager.recorder.frames(after, limit)})
            elif path == "/api/snapshot":
                frame = manager.frame()
                data = io.BytesIO()
                with zipfile.ZipFile(data, "w") as archive:
                    archive.writestr("color.jpg", frame.color_jpeg)
                    archive.writestr("depth.png", frame.depth_png)
                    archive.writestr(
                        "metadata.json", json.dumps(frame.metadata, ensure_ascii=False)
                    )
                self._response(200, data.getvalue(), "application/zip")
            elif path in ("/stream/color.mjpg", "/stream/depth.mjpg"):
                manager.frame()  # Refuse unavailable/stale streams before headers.
                stream = "color" if "color" in path else "depth"
                session = manager.status()["session"]
                self.send_response(200)
                self.send_header(
                    "Content-Type", "multipart/x-mixed-replace; boundary=frame"
                )
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                headers_sent = True
                previous = -1
                while packet := manager.wait_image(stream, previous, session):
                    previous, data = packet
                    self.wfile.write(
                        b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                        + str(len(data)).encode()
                        + b"\r\n\r\n"
                        + data
                        + b"\r\n"
                    )
                    self.wfile.flush()
            else:
                self._json(404, {"error": "Unknown endpoint"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            if not headers_sent:
                self._json(503, {"error": str(exc)})


def serve(
    host: str,
    port: int,
    defaults: Configuration,
    *,
    record_root: str = "",
    record_queue: int = 16,
) -> None:
    manager = CaptureManager(
        defaults, record_root=record_root, record_queue=record_queue
    )
    server = CameraHTTPServer((host, port), manager)

    def stop(*_args: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(f"D435i service ready: http://{host}:{port}; camera idle", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        try:
            manager.stop()
        finally:
            server.server_close()
