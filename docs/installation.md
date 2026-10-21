# 安装与部署

## 本地控制电脑

```bash
uv sync --project camera-realsense-d435i --python 3.11
uv run --project camera-realsense-d435i camera-realsense-d435i --help
```

本地客户端只用标准库和 SSH，不需要 `pyrealsense2`，也不需要在本地连接相机。

## 远端服务主机

远端必须是 Linux x86_64，Python 3.13（现场），并安装服务 extra：

```bash
uv sync --project camera-realsense-d435i --extra server --python 3.13
```

`deploy/install_service.py` 会：

- 把当前源码同步到 `~/project/camera-realsense-d435i/`；
- 创建独立 `.venv`；
- 为 cam1/cam2 写入用户 unit；
- **保留**已有的 `~/.config/camera-realsense-d435i/camN.json`；
- 默认 `disable`，不恢复开机自启。

## 现场 JSON

```json
{"serial": "349522071221", "width": 640, "height": 480, "fps": 15, "jpeg_quality": 80}
```

cam1 使用 USB 序列号 `349522071221`，cam2 使用 `349522072318`；端口分别为
8086/8087。修改后先停对应采集，再重启对应 unit。

## 验证

```bash
camera-realsense-d435i info --profiles
camera-realsense-d435i --camera cam1 status
```

`info` 只枚举设备和 profile，不打开视频流。`status` 在 API 未启动时由本地
`preview`/`connect` 按需启动远端服务。

## 权限

远端用户需要能访问 USB 设备（通常加入 `video` 和 `dialout` 组，或使用 udev
规则）。两台相机挂在同一 USB 2.0 Hub 时，带宽由两者共享。
