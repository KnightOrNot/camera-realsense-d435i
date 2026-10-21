from __future__ import annotations

from pathlib import Path

import pytest

from camera_realsense_d435i.cli import parser
from camera_realsense_d435i.configuration import load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "default.toml"
    path.write_text(text)
    return path


def test_defaults() -> None:
    config = load_config()
    assert config.client.camera == "cam1"
    assert config.client.cam1_port == 8086
    assert config.client.cam2_port == 8087
    assert config.serve.host == "127.0.0.1"
    args = parser(config).parse_args(["status"])
    assert args.camera == "cam1"
    assert args.defaults_config is config


@pytest.mark.parametrize(
    "arguments",
    [
        ["--defaults", "custom.toml", "--camera", "cam2", "status"],
        ["status", "--defaults", "custom.toml", "--camera", "cam2"],
    ],
)
def test_options_before_or_after_command(arguments):
    args = parser().parse_args(arguments)
    assert args.camera == "cam2"
    assert args.defaults == Path("custom.toml")


def test_camera_and_port_override(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
[client]
camera = "cam2"
cam1_port = 18086
cam2_port = 18087
snapshot_dir = "images"

[serve]
port = 18087
""",
    )
    config = load_config(path)
    args = parser(config).parse_args(["status"])
    assert args.camera == "cam2"
    assert config.client.port("cam2") == 18087
    assert config.client.snapshot_dir == "images"
    assert config.serve.port == 18087


def test_invalid_values(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must differ"):
        load_config(
            write(
                tmp_path,
                "[client]\ncam1_port = 8086\ncam2_port = 8086\n",
            )
        )
    with pytest.raises(ValueError, match="loopback"):
        load_config(write(tmp_path, '[serve]\nhost = "0.0.0.0"\n'))
    with pytest.raises(ValueError, match="unknown client options"):
        load_config(write(tmp_path, "[client]\nnope = 1\n"))


@pytest.mark.parametrize(
    "text",
    [
        "[client]\ncam1_port = true\n",
        "[client]\ncam2_port = 1.5\n",
        "[client]\nsnapshot_dir = []\n",
    ],
)
def test_invalid_types_and_nonfinite_values(tmp_path, text):
    with pytest.raises(ValueError):
        load_config(write(tmp_path, text))
