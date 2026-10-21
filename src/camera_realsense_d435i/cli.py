"""Remote camera CLI. Client commands never import the camera SDK."""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

from .client import Client, tunnel
from .configuration import Config, load_config


def parser(config: Config | None = None) -> argparse.ArgumentParser:
    config = config or load_config()
    root = argparse.ArgumentParser(description="D435i remote RGB-D capture and preview")
    root.set_defaults(defaults_config=config)
    root.add_argument("--defaults", type=Path, help="TOML defaults file")
    root.add_argument(
        "--camera", choices=("cam1", "cam2"), default=config.client.camera
    )
    commands = root.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--camera", choices=("cam1", "cam2"), default=argparse.SUPPRESS)
    common.add_argument("--url", help="Override forwarded HTTP URL")
    common.add_argument("--local-port", type=int, help="Override local forwarding port")
    common.add_argument(
        "--defaults",
        type=Path,
        default=argparse.SUPPRESS,
        help="TOML defaults file (default: <repository>/config/default.toml)",
    )
    for name in (
        "connect",
        "disconnect",
        "start",
        "stop",
        "status",
        "info",
        "snapshot",
        "preview",
    ):
        entry = commands.add_parser(name, parents=[common])
        if name in ("connect", "disconnect", "preview"):
            entry.add_argument(
                "--ssh-target",
                default=os.environ.get(
                    "XCORE_CAMERA_SSH_TARGET", config.client.ssh_target
                ),
            )
            entry.add_argument("--remote-port", type=int)
        if name in ("start", "preview"):
            entry.add_argument("--width", type=int)
            entry.add_argument("--height", type=int)
            entry.add_argument("--fps", type=int)
            entry.add_argument("--jpeg-quality", type=int)
        if name == "preview":
            entry.add_argument("--no-open", action="store_true")
        if name == "info":
            entry.add_argument("--profiles", action="store_true")
        if name == "snapshot":
            entry.add_argument("--output", type=Path)
    server = commands.add_parser(
        "serve", help="Run on the computer connected to the camera"
    )
    server.add_argument("--host", choices=("127.0.0.1",), default=config.serve.host)
    server.add_argument("--port", type=int, default=config.serve.port)
    server.add_argument(
        "--defaults",
        type=Path,
        default=argparse.SUPPRESS,
        help="TOML defaults file (default: <repository>/config/default.toml)",
    )
    # The per-device camera settings stay a separate file: the deployment keeps
    # site JSON that must not be overwritten by repository defaults.
    server.add_argument("--config", type=Path, required=True)
    return root


def run(args: argparse.Namespace) -> dict:
    config = args.defaults_config
    if args.command == "serve":
        from .camera import Configuration
        from .server import serve

        camera_config = Configuration(**json.loads(args.config.read_text()))
        if not camera_config.serial:
            raise ValueError("A server config must explicitly select a camera serial")
        serve(args.host, args.port, camera_config)
        return {"stopped": True}
    remote_port = getattr(args, "remote_port", None) or config.client.port(args.camera)
    port = args.local_port or config.client.port(args.camera)
    url = args.url or f"http://127.0.0.1:{port}"
    client = Client(url)
    if args.command in ("connect", "disconnect", "preview"):
        if not args.url:
            connection = tunnel(
                args.ssh_target,
                port,
                remote_port,
                camera=args.camera,
                disconnect=args.command == "disconnect",
            )
        elif args.command != "preview":
            raise ValueError(
                "connect/disconnect manage SSH; use --local-port, not --url"
            )
        if args.command != "preview":
            return connection
    if args.command in ("start", "preview"):
        options = {
            k: getattr(args, k)
            for k in ("width", "height", "fps", "jpeg_quality")
            if getattr(args, k) is not None
        }
        status = client.start(options)
        if args.command == "preview":
            opened = False if args.no_open else webbrowser.open(url)
            return {"url": url, "browser_opened": opened, "status": status}
        return status
    if args.command == "stop":
        return client.request("/api/stop", {})
    if args.command == "status":
        return client.request("/api/status")
    if args.command == "info":
        return client.request(
            "/api/devices?profiles=" + ("1" if args.profiles else "0")
        )
    if args.command == "snapshot":
        output = args.output or Path(config.client.snapshot_dir) / args.camera / (
            datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        )
        return client.snapshot(output)
    raise ValueError(f"Unknown command: {args.command}")


def defaults_path(argv: list[str]) -> Path | None:
    selected = None
    for index, value in enumerate(argv):
        if value == "--defaults" and index + 1 < len(argv):
            selected = Path(argv[index + 1])
        if value.startswith("--defaults="):
            selected = Path(value.split("=", 1)[1])
    return selected


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config(defaults_path(arguments))
    except (OSError, ValueError) as exc:
        print(f"camera-realsense-d435i: invalid configuration: {exc}", file=sys.stderr)
        return 1
    args = parser(config).parse_args(arguments)
    try:
        result = run(args)
        print(
            json.dumps(
                {"ok": True, "command": args.command, "result": result},
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "command": args.command,
                    "error": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
