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
record_root = "~/project/xcore-data/raw"
record_queue = 16
```

`host` 只允许 loopback，避免无认证的相机控制端口暴露到局域网。
远端部署时每台相机用 `--port` 覆盖为 8086/8087。

`record_root` 限制无损记录目录，留空则禁用记录 API；`record_queue` 是采集线程与
PNG 写盘线程之间的有界队列，满了会把该段记录标记为失败而不是丢帧续写。
记录目录由 controller 按 `<record_root>/<session>/<episode>/camN` 传入。

## 现场 JSON（不进入 Git）

每台相机的实际设备配置在远端：

```
~/.config/camera-realsense-d435i/cam1.json
~/.config/camera-realsense-d435i/cam2.json
```

```json
{"serial": "349522071221", "width": 640, "height": 480, "fps": 15, "jpeg_quality": 80,
 "align_depth_to_color": true}
```

`align_depth_to_color`（默认 `true`）只影响**深度预览**：把深度重投影到彩色相机
视角，使网页上同一台相机的 RGB 与深度画面视域一致。D435i 的深度传感器视场比彩色
传感器宽，不对齐时深度画面会明显更大。录制的 `depth.png` 仍是**原生 Z16 视角**，
不受该选项影响；旧 JSON 没有这个键时按 `true` 处理。

安装/部署脚本保留已有 JSON，不用仓库默认值覆盖。修改后先停止采集，再重启
对应 unit。

## 覆盖

```bash
camera-realsense-d435i --defaults config/experiment.toml --camera cam2 status
camera-realsense-d435i serve --defaults config/experiment.toml \
  --config ~/.config/camera-realsense-d435i/cam2.json --port 8087
```

未知表或字段、非 loopback 的 serve host、非法端口会在启动前拒绝。
