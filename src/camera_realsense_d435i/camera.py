"""RealSense adapter. Native depth stays Z16; JPEG depth is visualization only.

Device/profile/calibration organization follows KnightOrNot/camera-realsense
at f50274f00c85ac30ca48b3f3cd076b88fc273db9. SDK and host clocks are retained
separately; preview does not claim cross-host clock synchronization.
"""

from __future__ import annotations

import io
import math
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Configuration:
    width: int = 640
    height: int = 480
    fps: int = 15
    serial: str = ""
    jpeg_quality: int = 80

    def __post_init__(self) -> None:
        for name, upper in (("width", 1920), ("height", 1080), ("fps", 90)):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError(f"{name} must be an integer in 1..{upper}")
        if type(self.jpeg_quality) is not int or not 1 <= self.jpeg_quality <= 95:
            raise ValueError("jpeg_quality must be an integer in 1..95")
        if not isinstance(self.serial, str):
            raise ValueError("serial must be a string")

    def dictionary(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Frame:
    color_jpeg: bytes
    depth_jpeg: bytes
    depth_png: bytes
    metadata: dict[str, Any]


def _device_info(rs: Any, device: Any, profiles: bool) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("name", "serial_number", "firmware_version", "usb_type_descriptor"):
        key = getattr(rs.camera_info, name)
        if device.supports(key):
            result[name] = device.get_info(key)
    result["sensors"] = []
    for sensor in device.query_sensors():
        item: dict[str, Any] = {"name": sensor.get_info(rs.camera_info.name)}
        if profiles:
            item["profiles"] = []
            for profile in sensor.get_stream_profiles():
                entry = {
                    "stream": profile.stream_type().name,
                    "format": profile.format().name,
                    "fps": profile.fps(),
                }
                if profile.is_video_stream_profile():
                    video = profile.as_video_stream_profile()
                    entry.update(width=video.width(), height=video.height())
                item["profiles"].append(entry)
        result["sensors"].append(item)
    return result


def devices(profiles: bool = False) -> list[dict[str, Any]]:
    import pyrealsense2 as rs

    return [_device_info(rs, d, profiles) for d in rs.context().query_devices()]


def _intrinsics(profile: Any) -> dict[str, Any]:
    intr = profile.as_video_stream_profile().get_intrinsics()
    return {
        "width": intr.width,
        "height": intr.height,
        "fx": intr.fx,
        "fy": intr.fy,
        "ppx": intr.ppx,
        "ppy": intr.ppy,
        "model": intr.model.name,
        "coeffs": list(intr.coeffs),
    }


class RealSenseCamera:
    def __init__(self, configuration: Configuration):
        self.configuration = configuration
        self.pipeline: Any = None
        self.colorizer: Any = None
        self.metadata: dict[str, Any] = {}

    def open(self) -> dict[str, Any]:
        import pyrealsense2 as rs

        candidates = list(rs.context().query_devices())
        if self.configuration.serial:
            candidates = [
                d
                for d in candidates
                if d.get_info(rs.camera_info.serial_number) == self.configuration.serial
            ]
        if len(candidates) != 1:
            raise RuntimeError("Connect exactly one camera or select its serial number")
        device = candidates[0]
        information = _device_info(rs, device, False)
        if "D435I" not in information.get("name", "").upper():
            raise RuntimeError(f"Expected D435i, found {information.get('name')}")
        cfg = rs.config()
        cfg.enable_device(information["serial_number"])
        c = self.configuration
        cfg.enable_stream(rs.stream.color, c.width, c.height, rs.format.rgb8, c.fps)
        cfg.enable_stream(rs.stream.depth, c.width, c.height, rs.format.z16, c.fps)
        pipeline = rs.pipeline()
        try:
            profile = pipeline.start(cfg)
            self.pipeline = pipeline
            color = profile.get_stream(rs.stream.color)
            depth = profile.get_stream(rs.stream.depth)
            scale = profile.get_device().first_depth_sensor().get_depth_scale()
            if not math.isfinite(scale) or scale <= 0:
                raise RuntimeError("Invalid camera depth scale")
            extr = depth.get_extrinsics_to(color)
            self.metadata = {
                "device": information,
                "configuration": c.dictionary(),
                "depth_scale_m_per_unit": scale,
                "color_intrinsics": _intrinsics(color),
                "depth_intrinsics": _intrinsics(depth),
                "depth_to_color": {
                    "rotation": list(extr.rotation),
                    "translation_m": list(extr.translation),
                },
                "depth_alignment": "native_depth",
                "depth_format": "z16",
                "timestamp_note": "SDK clocks and server receive clock are separate",
            }
            self.colorizer = rs.colorizer()
            return self.metadata
        except BaseException:
            self.close()
            raise

    def read(self) -> Frame | None:
        import numpy as np
        from PIL import Image

        ok, frames = self.pipeline.try_wait_for_frames(1000)
        if not ok:
            return None
        received = time.monotonic_ns()
        color, depth = frames.get_color_frame(), frames.get_depth_frame()
        if not color or not depth:
            return None
        rgb = np.asanyarray(color.get_data())
        raw_depth = np.asanyarray(depth.get_data())
        depth_preview = np.asanyarray(self.colorizer.colorize(depth).get_data())

        def encode(array: Any, format_name: str) -> bytes:
            stream = io.BytesIO()
            options = (
                {"quality": self.configuration.jpeg_quality}
                if format_name == "JPEG"
                else {}
            )
            Image.fromarray(array).save(stream, format=format_name, **options)
            return stream.getvalue()

        meta = dict(self.metadata)
        meta["received_monotonic_ns"] = received
        meta["received_wall_time_ns"] = time.time_ns()
        for name, frame in (("color", color), ("depth", depth)):
            meta[name] = {
                "frame_number": frame.get_frame_number(),
                "sdk_timestamp_ms": frame.get_timestamp(),
                "sdk_timestamp_domain": frame.get_frame_timestamp_domain().name,
            }
        return Frame(
            encode(rgb, "JPEG"),
            encode(depth_preview, "JPEG"),
            encode(raw_depth, "PNG"),
            meta,
        )

    def close(self) -> None:
        if self.pipeline is not None:
            pipeline, self.pipeline = self.pipeline, None
            pipeline.stop()
