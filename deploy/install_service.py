"""Install per-user units for this checkout, without opening any cameras."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--enable", action="store_true", help="Start idle agents on login/boot"
)
args = parser.parse_args()
unit_dir = Path.home() / ".config/systemd/user"
config_dir = Path.home() / ".config/camera-realsense-d435i"
unit_dir.mkdir(parents=True, exist_ok=True)
config_dir.mkdir(parents=True, exist_ok=True)


def quote(value: Path) -> str:
    # systemd quoting (not shell); escape specifiers and literal backslashes.
    return (
        '"'
        + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
        + '"'
    )


for camera, port in (("cam1", 8086), ("cam2", 8087)):
    config = config_dir / f"{camera}.json"
    if not config.exists():
        config.write_text((root / "deploy" / f"{camera}.json").read_text())
    json.loads(config.read_text())
    unit = unit_dir / f"camera-realsense-d435i@{camera}.service"
    if unit.exists():
        unit.with_suffix(".service.previous").write_bytes(unit.read_bytes())
    unit.write_text(f"""[Unit]
Description=RealSense D435i {camera} loopback API
After=network.target

[Service]
Type=simple
WorkingDirectory={str(root).replace("%", "%%")}
Environment="PYTHONPATH={root / "src"}"
Environment=PYTHONUNBUFFERED=1
ExecStart={quote(Path(sys.executable))} -m camera_realsense_d435i serve \\
    --config {quote(config)} --port {port}
Restart=on-failure
RestartSec=3
TimeoutStopSec=15

[Install]
WantedBy=default.target
""")
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
if args.enable:
    for camera in ("cam1", "cam2"):
        subprocess.run(
            [
                "systemctl",
                "--user",
                "enable",
                "--now",
                f"camera-realsense-d435i@{camera}.service",
            ],
            check=True,
        )
print(
    "Installed cam1/cam2 units; camera acquisition starts only on an API start request."
)
