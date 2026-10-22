# CLI 参考

```bash
camera-realsense-d435i [--defaults FILE] --camera cam1 COMMAND [OPTIONS]
camera-realsense-d435i serve --config cam1.json [--host 127.0.0.1] [--port 8086]
```

`--defaults` 选择本项目的 TOML 默认值文件；`serve --config` 是每台相机的
现场 JSON，两者不要混用。

## 客户端命令

| 命令 | 行为 |
| --- | --- |
| `connect` | 建立 SSH 隧道（不启动采集） |
| `preview` | 建立隧道、启动采集并打开页面 |
| `start` | 请求远端启动采集 |
| `stop` | 停止采集，API 保留 idle |
| `status` | 远端状态、帧计数和错误 |
| `info [--profiles]` | 设备信息，可选 profile 列表 |
| `snapshot [--output DIR]` | 下载 RGB JPEG、Z16 PNG 和元数据 |
| `record-start --directory DIR --session S --episode E` | 在同一 pipeline 上开始无损 RGB/Z16 记录 |
| `record-stop [--incomplete] [--reason R]` | 结束记录；默认 complete=true |
| `record-status` | 记录状态、持久化帧数、队列、错误 |
| `record-frames [--after N] [--limit N]` | 读取已落盘的帧索引 |
| `disconnect` | 关闭本地隧道 |

公共参数：`--camera cam1|cam2`、`--url`、`--local-port`、`--defaults`。
connect/disconnect/preview 额外支持 `--ssh-target`、`--remote-port`。
start/preview 支持 `--width`、`--height`、`--fps`、`--jpeg-quality`。

端口默认来自项目 TOML：cam1 = 8086，cam2 = 8087。截图默认保存到
`captures/<camera>/<timestamp>/`。

## 服务端

| 参数 | 默认值 / 用途 |
| --- | --- |
| `--host` | 只能是 `127.0.0.1` |
| `--port` | `serve.port` |
| `--config` | 相机 JSON（必需）：serial、width、height、fps、jpeg_quality |
| `--defaults` | TOML 默认值文件 |

记录路由：`POST /api/record/start`（directory、session、episode）、
`POST /api/record/stop`（complete、reason）、`GET /api/record/status`、
`GET /api/record/frames?after=N&limit=N`。记录目录必须在 `serve.record_root` 下。

## 环境变量

- `XCORE_CAMERA_SSH_TARGET`：覆盖 SSH 目标。
- `XCORE_CAMERA_SNAPSHOT_DIR`：由顶层脚本设置截图根目录。

## 输出与退出码

成功输出 JSON；失败输出 `{"ok": false, "error": ...}` 并返回 1。
参数错误由 argparse 返回 2，Ctrl+C 返回 130。
