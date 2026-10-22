"""Lossless RGB/Z16 recording tapped from the one shared capture pipeline.

The capture thread never waits for disk I/O: frames enter a bounded queue and a
single writer thread encodes PNG and appends the frame index. A full queue or a
write error latches the episode as failed instead of silently dropping frames.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

FORMAT = "xcore_rgbd_frames_v1"


class RecordError(RuntimeError):
    """Raised when the active recording can no longer be trusted."""


def _check_label(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be a non-empty string of at most 128 chars")
    return value


class RawRecorder:
    """Write one camera stream of one episode into a caller-provided directory."""

    def __init__(self, root: str | Path, *, queue_size: int = 16) -> None:
        if type(queue_size) is not int or not 1 <= queue_size <= 1000:
            raise ValueError("record queue size must be an integer in 1..1000")
        self.root = Path(root).expanduser().resolve() if str(root) else None
        self.queue_size = queue_size
        self._lock = threading.RLock()
        self._queue: queue.Queue[dict[str, Any] | None] | None = None
        self._thread: threading.Thread | None = None
        self._directory: Path | None = None
        self._manifest: dict[str, Any] | None = None
        self._stream = None
        self._frames: list[dict[str, Any]] = []
        self._next_sequence = 0
        self._dropped = 0
        self._error: str | None = None
        self._complete = False
        self._state = "idle"

    @property
    def configured(self) -> bool:
        return self.root is not None

    @property
    def recording(self) -> bool:
        with self._lock:
            return self._state == "recording"

    def start(
        self,
        directory: str | Path,
        *,
        session: str,
        episode: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.root is None:
            raise RecordError(
                "recording is not configured (serve.record_root is empty)"
            )
        path = Path(directory)
        if not path.is_absolute():
            path = self.root / path
        path = path.resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("recording directory must stay under serve.record_root")
        session, episode = (
            _check_label("session", session),
            _check_label("episode", episode),
        )
        with self._lock:
            if self._state in ("recording", "stopping"):
                raise RecordError("a recording is already active")
            if path.exists() or path.is_symlink():
                raise FileExistsError("recording directory must be new")
            path.mkdir(parents=True)
            (path / "rgb").mkdir()
            (path / "depth").mkdir()
            manifest = {
                "format": FORMAT,
                "camera": (metadata or {}).get("configuration", {}).get("serial", ""),
                "session": session,
                "episode": episode,
                "created_wall_time_ns": time.time_ns(),
                "clock_note": "received_monotonic_ns is the host receive time; "
                "sdk timestamps stay in their own domain",
                "metadata": metadata or {},
            }
            self._directory = path
            self._manifest = manifest
            self._write_json(path / "manifest.json", manifest)
            self._stream = (path / "frames.jsonl").open("x", encoding="utf-8")
            self._frames, self._next_sequence = [], 0
            self._dropped, self._error, self._complete = 0, None, False
            self._queue = queue.Queue(maxsize=self.queue_size)
            self._state = "recording"
            self._thread = threading.Thread(
                target=self._run,
                args=(path, self._queue),
                name="d435i-raw",
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def submit(self, frame: Any) -> None:
        """Non-blocking enqueue from the capture thread; never raises."""
        with self._lock:
            if self._state != "recording" or self._queue is None:
                return
            color, depth = frame.color_rgb, frame.depth_z16
            if color is None or depth is None:
                self._fail("frame has no lossless RGB/depth payload")
                return
            sequence = self._next_sequence
            self._next_sequence += 1
            try:
                self._queue.put_nowait(
                    {
                        "sequence": sequence,
                        "frame": frame,
                        "monotonic_ns": time.monotonic_ns(),
                    }
                )
            except queue.Full:
                self._dropped += 1
                self._fail("recording queue is full; frames were not persisted")

    def _fail(self, reason: str) -> None:
        if self._error is None:
            self._error = reason
            self._state = "failed"

    def stop(
        self, *, complete: bool = True, reason: str | None = None
    ) -> dict[str, Any]:
        with self._lock:
            if self._queue is None:
                return self.status()
            queue_ref, thread, path = self._queue, self._thread, self._directory
            if self._state == "recording":
                self._state = "stopping"
        deadline = time.monotonic() + 10
        while thread is not None and thread.is_alive():
            try:
                queue_ref.put(None, timeout=0.1)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    self._fail("recording writer did not drain before timeout")
                    break
        if thread is not None:
            thread.join(timeout=10)
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.flush()
                    os.fsync(self._stream.fileno())
                finally:
                    self._stream.close()
                    self._stream = None
            failed = self._error is not None or self._dropped > 0
            self._complete = bool(complete) and not failed
            if path is not None:
                self._write_json(
                    path / "COMPLETE.json",
                    {
                        "complete": self._complete,
                        "frames": self._next_sequence,
                        "persisted": len(self._frames),
                        "dropped": self._dropped,
                        "error": self._error or reason,
                        "stopped_wall_time_ns": time.time_ns(),
                    },
                )
            self._state = "complete" if self._complete else "failed"
            self._queue, self._thread = None, None
            return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            queue_size = 0 if self._queue is None else self._queue.qsize()
            return {
                "configured": self.configured,
                "state": self._state,
                "directory": str(self._directory) if self._directory else None,
                "session": (self._manifest or {}).get("session"),
                "episode": (self._manifest or {}).get("episode"),
                "frames": self._next_sequence,
                "persisted": len(self._frames),
                "queued": queue_size,
                "dropped": self._dropped,
                "error": self._error,
                "complete": self._complete,
            }

    def frames(self, after: int = -1, limit: int = 1000) -> list[dict[str, Any]]:
        if type(after) is not int or type(limit) is not int or not 1 <= limit <= 5000:
            raise ValueError("invalid frame query bounds")
        with self._lock:
            return [dict(item) for item in self._frames if item["sequence"] > after][
                :limit
            ]

    def _run(self, path: Path, work: queue.Queue[dict[str, Any] | None]) -> None:
        import numpy as np
        from PIL import Image

        frames_since_flush = 0
        try:
            while True:
                item = work.get()
                if item is None:
                    break
                sequence = item["sequence"]
                frame = item["frame"]
                color = np.asarray(frame.color_rgb)
                depth = np.asarray(frame.depth_z16)
                if (
                    color.ndim != 3
                    or color.shape[2] != 3
                    or color.dtype != np.uint8
                    or depth.ndim != 2
                    or depth.dtype != np.uint16
                ):
                    raise ValueError("expected uint8 RGB and uint16 Z16 frames")
                name = f"{sequence:06d}.png"
                # Level 1 keeps lossless PNG encodable faster than real time;
                # level 6 costs ~105 ms for one 640x480 RGB frame (measured).
                Image.fromarray(color).save(
                    path / "rgb" / name, format="PNG", compress_level=1
                )
                if frame.depth_png:
                    # Reuse the already encoded lossless Z16 snapshot.
                    (path / "depth" / name).write_bytes(frame.depth_png)
                else:
                    Image.fromarray(depth).save(
                        path / "depth" / name,
                        format="PNG",
                        compress_level=1,
                    )
                meta = frame.metadata
                entry = {
                    "sequence": sequence,
                    "rgb": f"rgb/{name}",
                    "depth": f"depth/{name}",
                    "rgb_frame_number": meta["color"]["frame_number"],
                    "depth_frame_number": meta["depth"]["frame_number"],
                    "rgb_sdk_timestamp_ms": meta["color"]["sdk_timestamp_ms"],
                    "rgb_sdk_timestamp_domain": meta["color"]["sdk_timestamp_domain"],
                    "depth_sdk_timestamp_ms": meta["depth"]["sdk_timestamp_ms"],
                    "depth_sdk_timestamp_domain": meta["depth"]["sdk_timestamp_domain"],
                    "received_monotonic_ns": meta["received_monotonic_ns"],
                    "received_wall_time_ns": meta["received_wall_time_ns"],
                    "writer_monotonic_ns": item["monotonic_ns"],
                }
                with self._lock:
                    if self._stream is not None:
                        line = json.dumps(entry, ensure_ascii=False, allow_nan=False)
                        self._stream.write(line + "\n")
                        self._frames.append(entry)
                frames_since_flush += 1
                if frames_since_flush >= 15:
                    with self._lock:
                        if self._stream is not None:
                            self._stream.flush()
                    frames_since_flush = 0
        except Exception as exc:  # noqa: BLE001 - surface any write/serialization failure
            with self._lock:
                self._fail(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _write_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".partial")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
