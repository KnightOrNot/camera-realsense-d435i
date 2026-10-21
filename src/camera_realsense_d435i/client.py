"""HTTP client and SSH port forwarding; no RealSense dependency on the laptop."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


class Client:
    def __init__(self, url: str = "http://127.0.0.1:8086", timeout: float = 15):
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        self.url, self.timeout = url.rstrip("/"), timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path: str, data: dict | None = None) -> Any:
        request = urllib.request.Request(self.url + path)
        if data is not None:
            request.data = json.dumps(data).encode()
            request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(exc.read().decode(errors="replace")) from exc

    def start(self, options: dict[str, Any], startup_timeout: float = 30) -> dict:
        self.request("/api/start", options)
        deadline = time.monotonic() + startup_timeout
        while True:
            state = self.request("/api/status")
            if state["state"] == "streaming" and state["sequence"] > 0:
                return state
            if state["state"] == "error":
                raise RuntimeError(state["error"])
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Camera startup timed out: {state}")
            time.sleep(0.15)

    def snapshot(self, destination: Path) -> dict:
        with self.opener.open(
            self.url + "/api/snapshot", timeout=self.timeout
        ) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if len(data) > 32 * 1024 * 1024:
            raise RuntimeError("Snapshot exceeds size limit")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if set(archive.namelist()) != {"color.jpg", "depth.png", "metadata.json"}:
                raise RuntimeError("Unexpected snapshot archive contents")
            if sum(i.file_size for i in archive.infolist()) > 64 * 1024 * 1024:
                raise RuntimeError("Expanded snapshot exceeds size limit")
            destination.mkdir(parents=True, exist_ok=False)
            for name in archive.namelist():
                (destination / name).write_bytes(archive.read(name))
        return {"saved": str(destination.resolve())}


def tunnel(
    target: str,
    local_port: int,
    remote_port: int,
    *,
    camera: str = "cam1",
    disconnect: bool = False,
) -> dict:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*@[A-Za-z0-9][A-Za-z0-9.-]*", target):
        raise ValueError("SSH target must be user@hostname or user@IPv4")
    if not all(1 <= p <= 65535 for p in (local_port, remote_port)):
        raise ValueError("Invalid tunnel port")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", camera):
        raise ValueError("Invalid camera instance name")
    runtime = Path(tempfile.gettempdir()) / f"camera-d435i-{os.getuid()}"
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.is_symlink() or runtime.stat().st_uid != os.getuid():
        raise RuntimeError("Unsafe tunnel socket directory")
    runtime.chmod(0o700)
    digest = hashlib.sha256(
        f"{target}:{local_port}:{remote_port}".encode()
    ).hexdigest()[:16]
    control = str(runtime / (digest + ".sock"))
    common = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=6",
    ]
    check = subprocess.run(
        common + ["-S", control, "-O", "check", target],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if disconnect:
        if check.returncode == 0:
            subprocess.run(
                common + ["-S", control, "-O", "exit", target], check=True, timeout=10
            )
        return {"connected": False, "camera_stopped": False}
    subprocess.run(
        common
        + [target, f"systemctl --user start camera-realsense-d435i@{camera}.service"],
        check=True,
        timeout=20,
    )
    if check.returncode != 0:
        subprocess.run(
            common
            + [
                "-fNT",
                "-M",
                "-S",
                control,
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                "-L",
                f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}",
                target,
            ],
            check=True,
            timeout=15,
        )
    url = f"http://127.0.0.1:{local_port}"
    deadline = time.monotonic() + 8
    while True:
        try:
            state = Client(url, timeout=2).request("/api/health")
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.2)
    if state.get("service") != "camera-realsense-d435i":
        raise RuntimeError("Unexpected service on the forwarded local port")
    return {"connected": True, "url": url, "ssh_target": target, "camera": camera}
