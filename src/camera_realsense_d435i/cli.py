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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="D435i remote RGB-D capture and preview")
    commands = root.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--camera", choices=("cam1", "cam2"), default="cam1")
    common.add_argument("--url", help="Override forwarded HTTP URL")
    common.add_argument("--local-port", type=int, help="Override local forwarding port")
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
                    "XCORE_CAMERA_SSH_TARGET", "rokae@192.168.2.225"
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
    server.add_argument("--host", choices=("127.0.0.1",), default="127.0.0.1")
    server.add_argument("--port", type=int, default=8086)
    server.add_argument("--config", type=Path, required=True)
    return root


def run(args: argparse.Namespace) -> dict:
    if args.command == "serve":
        from .camera import Configuration
        from .server import serve

        config = Configuration(**json.loads(args.config.read_text()))
        if not config.serial:
            raise ValueError("A server config must explicitly select a camera serial")
        serve(args.host, args.port, config)
        return {"stopped": True}
    port = args.local_port or (8086 if args.camera == "cam1" else 8087)
    url = args.url or f"http://127.0.0.1:{port}"
    client = Client(url)
    if args.command in ("connect", "disconnect", "preview"):
        if not args.url:
            connection = tunnel(
                args.ssh_target,
                port,
                args.remote_port or (8086 if args.camera == "cam1" else 8087),
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
        output = args.output or Path(
            "captures"
        ) / args.camera / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        return client.snapshot(output)
    raise ValueError(f"Unknown command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
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
