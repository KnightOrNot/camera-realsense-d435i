import json
import threading
import time

import numpy as np
import pytest
from PIL import Image

from camera_realsense_d435i.camera import Configuration, Frame
from camera_realsense_d435i.client import Client
from camera_realsense_d435i.manager import CaptureManager
from camera_realsense_d435i.recorder import RawRecorder, RecordError
from camera_realsense_d435i.server import CameraHTTPServer


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for recorder state")
        time.sleep(0.005)


class FakeCamera:
    def __init__(self, config):
        self.config, self.number = config, 0
        self.rows = np.arange(48, dtype=np.uint16)[:, None] * np.ones(
            (1, 64), dtype=np.uint16
        )

    def open(self):
        return {"serial": self.config.serial, "depth_scale_m_per_unit": 0.001}

    def read(self):
        time.sleep(0.01)
        self.number += 1
        stamp = time.monotonic_ns()
        color = np.zeros((48, 64, 3), dtype=np.uint8)
        color[:, :, 0] = self.number % 256
        depth = self.rows + self.number
        return Frame(
            b"color-jpeg",
            b"depth-jpeg",
            b"",
            {
                "received_monotonic_ns": stamp,
                "received_wall_time_ns": time.time_ns(),
                "depth_scale_m_per_unit": 0.001,
                "color": {
                    "frame_number": self.number,
                    "sdk_timestamp_ms": 12,
                    "sdk_timestamp_domain": "system_time",
                },
                "depth": {
                    "frame_number": self.number + 100,
                    "sdk_timestamp_ms": 13,
                    "sdk_timestamp_domain": "system_time",
                },
            },
            color,
            depth,
        )

    def close(self):
        pass


def test_records_lossless_rgb_and_z16(tmp_path):
    manager = CaptureManager(
        Configuration(serial="test"), FakeCamera, record_root=str(tmp_path)
    )
    manager.start({})
    wait_for(lambda: manager.status()["state"] == "streaming")
    directory = tmp_path / "session" / "episode" / "cam1"
    status = manager.start_recording(
        {"directory": str(directory), "session": "s1", "episode": "e0"}
    )
    assert status["state"] == "recording"
    wait_for(lambda: manager.recorder.status()["persisted"] >= 5)
    stopped = manager.stop_recording()
    assert stopped["complete"] is True
    assert stopped["dropped"] == 0
    frames = manager.recorder.frames()
    assert len(frames) == stopped["persisted"]
    assert [f["sequence"] for f in frames] == list(range(len(frames)))
    first = frames[0]
    rgb = np.asarray(Image.open(directory / first["rgb"]))
    depth = np.asarray(Image.open(directory / first["depth"]))
    assert rgb.dtype == np.uint8 and rgb.shape == (48, 64, 3)
    assert depth.dtype == np.uint16 and depth.shape == (48, 64)
    assert first["rgb_frame_number"] != first["depth_frame_number"]
    assert first["received_monotonic_ns"] > 0
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["format"] == "xcore_rgbd_frames_v1"
    assert manifest["metadata"]["depth_scale_m_per_unit"] == 0.001
    complete = json.loads((directory / "COMPLETE.json").read_text())
    assert complete["complete"] is True and complete["persisted"] == len(frames)
    manager.stop()


def test_rejects_directory_outside_root_and_existing(tmp_path):
    recorder = RawRecorder(tmp_path / "root")
    recorder_root = (tmp_path / "root").resolve()
    recorder_root.mkdir()
    with pytest.raises(ValueError, match="under"):
        recorder.start(str(tmp_path / "elsewhere"), session="s", episode="e")
    directory = recorder_root / "valid"
    recorder.start(str(directory), session="s", episode="e")
    recorder.stop(complete=False, reason="test")
    with pytest.raises(FileExistsError):
        recorder.start(str(directory), session="s", episode="e")


def test_unconfigured_recording_is_rejected(tmp_path):
    recorder = RawRecorder("")
    with pytest.raises(RecordError, match="not configured"):
        recorder.start(str(tmp_path / "x"), session="s", episode="e")


def test_writer_failure_marks_episode_failed(tmp_path):
    recorder = RawRecorder(tmp_path, queue_size=4)
    recorder.start(tmp_path / "ep", session="s", episode="e")
    # Missing depth metadata makes the writer fail; no silent partial success.
    broken = Frame(
        b"",
        b"",
        b"",
        {"received_monotonic_ns": 1, "color": {}, "depth": {}},
        np.zeros((4, 4, 3), np.uint8),
        np.zeros((4, 4), np.uint16),
    )
    recorder.submit(broken)
    wait_for(lambda: recorder.status()["state"] == "failed")
    status = recorder.stop(complete=True)
    assert status["complete"] is False
    complete = json.loads((tmp_path / "ep" / "COMPLETE.json").read_text())
    assert complete["complete"] is False and complete["error"]


def test_http_record_endpoints(tmp_path):
    manager = CaptureManager(
        Configuration(serial="test"), FakeCamera, record_root=str(tmp_path)
    )
    server = CameraHTTPServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{server.server_port}")
    try:
        client.start({})
        directory = tmp_path / "s" / "e" / "cam1"
        started = client.record_start(str(directory), session="s", episode="e")
        assert started["state"] == "recording"
        deadline = time.monotonic() + 3
        while not client.record_frames():
            assert time.monotonic() < deadline
            time.sleep(0.02)
        stopped = client.record_stop()
        assert stopped["complete"] is True
        assert client.record_frames(0)
        assert client.record_status()["state"] == "complete"
    finally:
        manager.stop()
        server.shutdown()
        thread.join(2)
        server.server_close()
