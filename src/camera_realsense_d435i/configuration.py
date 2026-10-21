"""Validated client/server defaults from ``config/default.toml``."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


def _default_config_path() -> Path | None:
    package = Path(__file__).resolve().parent
    for candidate in (
        package.parents[1] / "config/default.toml",
        package / "default.toml",
    ):
        if candidate.exists():
            return candidate
    return None


DEFAULT_CONFIG = _default_config_path()


@dataclass(frozen=True)
class ClientConfig:
    camera: str = "cam1"
    ssh_target: str = "rokae@192.168.2.225"
    cam1_port: int = 8086
    cam2_port: int = 8087
    snapshot_dir: str = "captures"

    def port(self, camera: str) -> int:
        return self.cam1_port if camera == "cam1" else self.cam2_port


@dataclass(frozen=True)
class ServeConfig:
    host: str = "127.0.0.1"
    port: int = 8086


@dataclass(frozen=True)
class Config:
    path: Path | None
    client: ClientConfig = ClientConfig()
    serve: ServeConfig = ServeConfig()

    def validate(self) -> None:
        sections = {
            name: getattr(self, "return_" if name == "return" else name)
            for name in SECTIONS
        }
        for section, values in sections.items():
            for item in fields(values):
                value = getattr(values, item.name)
                default = item.default
                kind = type(default)
                valid = type(value) is kind
                if kind is float:
                    valid = (
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(value)
                    )
                if not valid:
                    raise ValueError(
                        f"{section}.{item.name} has an invalid type or non-finite value"
                    )
        if self.client.camera not in ("cam1", "cam2"):
            raise ValueError("client.camera must be cam1 or cam2")
        if not isinstance(self.client.ssh_target, str) or not self.client.ssh_target:
            raise ValueError("client.ssh_target must be a non-empty string")
        for name in ("cam1_port", "cam2_port"):
            value = getattr(self.client, name)
            if not isinstance(value, int) or not 1 <= value <= 65535:
                raise ValueError(f"client.{name} must be in 1..65535")
        if self.client.cam1_port == self.client.cam2_port:
            raise ValueError("client.cam1_port and cam2_port must differ")
        if (
            not isinstance(self.client.snapshot_dir, str)
            or not self.client.snapshot_dir
        ):
            raise ValueError("client.snapshot_dir must be a non-empty string")
        if self.serve.host != "127.0.0.1":
            raise ValueError("serve.host must be 127.0.0.1 (loopback only)")
        if not isinstance(self.serve.port, int) or not 1 <= self.serve.port <= 65535:
            raise ValueError("serve.port must be in 1..65535")


SECTIONS = {"client": ClientConfig, "serve": ServeConfig}


def load_config(path: str | Path | None = None) -> Config:
    selected = Path(path).resolve() if path is not None else DEFAULT_CONFIG
    if selected is None:
        data: dict[str, Any] = {}
    else:
        with Path(selected).open("rb") as stream:
            data = tomllib.load(stream)
    unknown = data.keys() - SECTIONS.keys()
    if unknown:
        raise ValueError(f"unknown configuration sections: {sorted(unknown)}")
    sections: dict[str, Any] = {}
    for name, cls in SECTIONS.items():
        values = data.get(name, {})
        if not isinstance(values, dict):
            raise ValueError(f"{name} must be a TOML table")
        unknown = values.keys() - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"unknown {name} options: {sorted(unknown)}")
        try:
            sections[name] = cls(**values)
        except TypeError as exc:
            raise ValueError(f"invalid {name} options: {exc}") from exc
    result = Config(path=Path(selected) if selected is not None else None, **sections)
    result.validate()
    return result
