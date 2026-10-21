# 配置参考

默认文件：[config/default.toml](../../config/default.toml)。优先级：

```text
显式命令行参数 > XCORE_CAMERA_SSH_TARGET 等环境变量 > config/default.toml
```

## client

```toml
[client]
camera = "cam1"
ssh_target = "rokae@192.168.2.225"
cam1_port = 8086
cam2_port = 8087
snapshot_dir = "captures"
```

- `camera` 是默认相机；顶层脚本总是显式传 `--camera`。
- `cam1_port` / `cam2_port` 同时用于远端 API 和本地转发，必须不同。
- `snapshot_dir` 相对于运行命令时的工作目录；顶层脚本会改传绝对路径。

## serve

```toml
[serve]
host = "127.0.0.1"
port = 8086
```

`host` 只允许 loopback，避免无认证的相机控制端口暴露到局域网。
远端部署时每台相机用 `--port` 覆盖为 8086/8087。

## 现场 JSON（不进入 Git）

每台相机的实际设备配置在远端：

```
~/.config/camera-realsense-d435i/cam1.json
~/.config/camera-realsense-d435i/cam2.json
```

```json
{"serial": "349522071221", "width": 640, "height": 480, "fps": 15, "jpeg_quality": 80}
```

安装/部署脚本保留已有 JSON，不用仓库默认值覆盖。修改后先停止采集，再重启
对应 unit。

## 覆盖

```bash
camera-realsense-d435i --defaults config/experiment.toml --camera cam2 status
camera-realsense-d435i serve --defaults config/experiment.toml \
  --config ~/.config/camera-realsense-d435i/cam2.json --port 8087
```

未知表或字段、非 loopback 的 serve host、非法端口会在启动前拒绝。
