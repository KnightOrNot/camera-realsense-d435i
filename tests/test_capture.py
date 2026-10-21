import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from camera_realsense_d435i.camera import Configuration, Frame
from camera_realsense_d435i.client import Client
from camera_realsense_d435i.manager import CaptureManager
from camera_realsense_d435i.server import CameraHTTPServer


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for capture state")
        time.sleep(0.005)


class FakeCamera:
    opened = 0
    closed = 0

    def __init__(self, config):
        self.config = config
        self.number = 0

    def open(self):
        type(self).opened += 1
        return {"serial": self.config.serial}

    def read(self):
        time.sleep(0.01)
        self.number += 1
        return Frame(
            b"color-jpeg",
            b"depth-jpeg",
            b"raw-png",
            {
                "received_monotonic_ns": time.monotonic_ns(),
                "depth_scale_m_per_unit": 0.001,
                "color": {"frame_number": self.number, "sdk_timestamp_ms": 12},
                "depth": {"frame_number": self.number + 100, "sdk_timestamp_ms": 13},
            },
        )

    def close(self):
        type(self).closed += 1


@pytest.fixture
def manager():
    FakeCamera.opened = FakeCamera.closed = 0
    value = CaptureManager(Configuration(serial="test"), FakeCamera)
    yield value
    value.stop()


@pytest.fixture
def service(manager):
    server = CameraHTTPServer(("127.0.0.1", 0), manager)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = Client(f"http://127.0.0.1:{server.server_port}")
    yield client
    manager.stop()
    server.shutdown()
    thread.join(2)
    server.server_close()


def test_shared_capture_idempotence_stop_and_restart(manager):
    assert manager.status()["state"] == "idle"
    manager.start({})
    wait_for(lambda: manager.status()["sequence"] > 0)
    session = manager.status()["session"]
    manager.start({})
    assert FakeCamera.opened == 1
    assert (
        manager.frame().metadata["color"]["frame_number"]
        != manager.frame().metadata["depth"]["frame_number"]
    )
    with pytest.raises(RuntimeError, match="Stop"):
        manager.start({"fps": 6})
    assert manager.stop()["state"] == "idle"
    assert FakeCamera.closed == 1
    with pytest.raises(RuntimeError, match="not streaming"):
        manager.frame()
    assert manager.wait_image("color", 0, session) is None
    manager.start({"fps": 6})
    wait_for(lambda: manager.status()["sequence"] > 0)
    assert manager.status()["session"] != session


def test_serial_cannot_cross_instances(manager):
    with pytest.raises(ValueError, match="bound"):
        manager.start({"serial": "other"})
    assert FakeCamera.opened == 0


@pytest.mark.parametrize("failure", ["constructor", "open", "read"])
def test_errors_reported_and_device_closed(failure):
    class Broken(FakeCamera):
        def __init__(self, config):
            if failure == "constructor":
                raise RuntimeError("constructor failed")
            super().__init__(config)

        def open(self):
            if failure == "open":
                raise RuntimeError("open failed")
            return super().open()

        def read(self):
            raise RuntimeError("read failed")

    value = CaptureManager(Configuration(), Broken)
    value.start({})
    wait_for(lambda: value.status()["state"] == "error")
    value.stop()
    assert failure in value.status()["error"]
    assert value.latest is None


def test_no_frames_timeout():
    class Empty(FakeCamera):
        def read(self):
            time.sleep(0.005)
            return None

    value = CaptureManager(Configuration(), Empty, frame_timeout=0.03)
    value.start({})
    wait_for(lambda: value.status()["state"] == "error")
    value.stop()
    assert "No camera frames" in value.status()["error"]


def test_stale_frame_rejected(manager):
    manager.start({})
    wait_for(lambda: manager.status()["sequence"] > 0)
    with manager.condition:
        manager.latest.metadata["received_monotonic_ns"] -= 3_000_000_000
        with pytest.raises(RuntimeError, match="stale"):
            manager.frame()


def test_http_start_stream_snapshot_stop(service, tmp_path):
    assert service.request("/api/status")["state"] == "idle"
    status = service.start({})
    assert status["metadata"]["serial"] == "test"
    with service.opener.open(service.url + "/stream/color.mjpg", timeout=2) as response:
        assert "multipart" in response.headers["Content-Type"]
        assert response.readline() == b"--frame\r\n"
        assert response.readline() == b"Content-Type: image/jpeg\r\n"
        length = int(response.readline().split(b":")[1])
        assert response.readline() == b"\r\n"
        assert response.read(length) == b"color-jpeg"
    destination = tmp_path / "snapshot"
    service.snapshot(destination)
    assert (destination / "depth.png").read_bytes() == b"raw-png"
    meta = json.loads((destination / "metadata.json").read_text())
    assert meta["depth_scale_m_per_unit"] == 0.001
    assert meta["color"]["sdk_timestamp_ms"] != meta["depth"]["sdk_timestamp_ms"]
    with pytest.raises(FileExistsError):
        service.snapshot(destination)
    assert service.request("/api/stop", {})["state"] == "idle"
    with pytest.raises(RuntimeError, match="not streaming"):
        service.request("/api/snapshot")


def test_invalid_control_requests_do_not_open_device(service):
    for data in ({"fps": True}, {"unknown": 3}, {"serial": "other"}):
        with pytest.raises(RuntimeError):
            service.request("/api/start", data)
    request = urllib.request.Request(
        service.url + "/api/start",
        data=b"{}",
        headers={"Content-Type": "application/json", "Origin": "http://other.example"},
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        service.opener.open(request)
    assert error.value.code == 403
    assert FakeCamera.opened == 0


def test_client_import_and_help_do_not_require_sdk():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from camera_realsense_d435i.cli import main
assert 'pyrealsense2' not in sys.modules
assert 'numpy' not in sys.modules
main(['--help'])
""",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "preview" in result.stdout
