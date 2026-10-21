"""One acquisition worker with a latest-frame cache, shared by all viewers."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from .camera import Configuration, Frame, RealSenseCamera


class CaptureManager:
    def __init__(
        self,
        defaults: Configuration,
        factory: Callable[..., Any] = RealSenseCamera,
        frame_timeout: float = 5.0,
    ):
        self.defaults, self.factory = defaults, factory
        self.frame_timeout = frame_timeout
        self.condition = threading.Condition()
        self.thread: threading.Thread | None = None
        self.stopping = threading.Event()
        self.phase = "idle"
        self.error: str | None = None
        self.session = ""
        self.configuration = defaults
        self.latest: Frame | None = None
        self.sequence = 0
        self.metadata: dict[str, Any] = {}
        self.counters: dict[str, list[Any]] = {}

    def start(self, options: dict[str, Any]) -> dict[str, Any]:
        config = Configuration(**(self.defaults.dictionary() | options))
        if self.defaults.serial and config.serial != self.defaults.serial:
            raise ValueError("This instance is bound to its configured camera serial")
        with self.condition:
            if self.thread is not None and self.thread.is_alive():
                if (
                    self.phase in ("starting", "streaming")
                    and config == self.configuration
                ):
                    return self.status()
                raise RuntimeError(
                    "Stop the existing camera session before reconfiguring"
                )
            self.configuration = config
            self.phase, self.error = "starting", None
            self.session = uuid.uuid4().hex
            self.latest, self.sequence = None, 0
            self.metadata, self.counters = {}, {}
            self.stopping.clear()
            self.thread = threading.Thread(
                target=self._capture, daemon=True, name="d435i-capture"
            )
            self.thread.start()
            return self.status()

    def _capture(self) -> None:
        camera = None
        try:
            camera = self.factory(self.configuration)
            metadata = camera.open()
            with self.condition:
                self.metadata = metadata
            last_frame = time.monotonic()
            while not self.stopping.is_set():
                frame = camera.read()
                now = time.monotonic()
                if frame is None:
                    if now - last_frame > self.frame_timeout:
                        raise TimeoutError("No camera frames received within timeout")
                    continue
                last_frame = now
                with self.condition:
                    for name in ("color", "depth"):
                        number = frame.metadata[name]["frame_number"]
                        stat = self.counters.setdefault(name, [number, 0, now, now])
                        if number != stat[0] or stat[1] == 0:
                            stat[0], stat[1], stat[3] = number, stat[1] + 1, now
                    self.latest = frame
                    self.sequence += 1
                    self.phase = "streaming"
                    self.condition.notify_all()
        except Exception as exc:
            with self.condition:
                self.error = f"{type(exc).__name__}: {exc}"
                self.phase = "error"
                self.latest = None
                self.condition.notify_all()
        finally:
            try:
                if camera is not None:
                    camera.close()
            except Exception as exc:
                with self.condition:
                    self.error = f"Camera close failed: {exc}"
                    self.phase = "error"
            with self.condition:
                self.latest = None
                if self.phase != "error":
                    self.phase = "idle"
                self.condition.notify_all()

    def stop(self) -> dict[str, Any]:
        with self.condition:
            self.stopping.set()
            thread = self.thread
            if thread is not None and thread.is_alive():
                self.phase = "stopping"
            self.condition.notify_all()
        if thread is not None:
            thread.join(timeout=10)
            if thread.is_alive():
                raise RuntimeError("Camera is still stopping; no new session permitted")
        return self.status()

    def status(self) -> dict[str, Any]:
        with self.condition:
            age = None
            if self.latest is not None:
                age = (
                    time.monotonic_ns() - self.latest.metadata["received_monotonic_ns"]
                ) / 1e9
            fps = {
                name: round((s[1] - 1) / (s[3] - s[2]), 2) if s[3] > s[2] else 0
                for name, s in self.counters.items()
            }
            return {
                "service": "camera-realsense-d435i",
                "state": self.phase,
                "session": self.session,
                "sequence": self.sequence,
                "frame_age_s": age,
                "observed_fps": fps,
                "error": self.error,
                "configuration": self.configuration.dictionary(),
                "metadata": self.metadata,
            }

    def frame(self) -> Frame:
        with self.condition:
            if self.latest is None or self.phase != "streaming":
                raise RuntimeError(
                    self.error or "Camera is not streaming; start it first"
                )
            if (
                time.monotonic_ns() - self.latest.metadata["received_monotonic_ns"]
                > 2_000_000_000
            ):
                raise RuntimeError("Camera frames are stale")
            return self.latest

    def wait_image(
        self, stream: str, previous: int, session: str
    ) -> tuple[int, bytes] | None:
        with self.condition:
            self.condition.wait_for(
                lambda: (
                    self.sequence > previous
                    or self.phase != "streaming"
                    or self.session != session
                ),
                timeout=2,
            )
            if self.phase != "streaming" or self.session != session:
                return None
            frame = self.frame()
            return self.sequence, getattr(frame, f"{stream}_jpeg")
