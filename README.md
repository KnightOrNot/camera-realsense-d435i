# camera-realsense-d435i

在远端 Linux 电脑采集两台 RealSense D435i，通过 SSH 转发，在本地查看 RGB 和深度画面。
支持独立启停、设备／标定信息和 RGB-D 截图；不依赖 ROS，不导入机械臂或夹爪代码。

## 现场快速启动

当前远端 `rokae@192.168.2.225` 的 `~/project/camera-realsense-d435i/` 已部署两个用户服务。
从本地独立仓库执行，Python 3.11＋uv，SSH 密钥登录需已配置：

```bash
uv sync --locked --no-dev
uv run --locked camera-realsense-d435i preview --camera cam1
uv run --locked camera-realsense-d435i preview --camera cam2
```

`preview` 会确保对应远端 API 服务运行、建立 SSH 隧道、启动采集并尝试打开浏览器。
没有桌面时加 `--no-open`，手动打开输出的网址。两个页面分别为：

| 实例 | 序列号 | 本地页面 | 远端服务 |
| --- | --- | --- | --- |
| cam1 | 349522071221 | <http://127.0.0.1:8086> | `camera-realsense-d435i@cam1.service` |
| cam2 | 349522072318 | <http://127.0.0.1:8087> | `camera-realsense-d435i@cam2.service` |

在集成仓库 `xcore-controller` 中，也可使用 `./start_camera.sh` 一次启动两台。
关闭网页不会停止采集；请使用网页“停止采集”按钮或以下 `stop` 命令。
命令返回后相机服务与 SSH 隧道持续运行；API 服务开机启动时保持 idle，不自动打开相机。

## 命令

以下命令前缀均为 `uv run --locked camera-realsense-d435i`，默认 `--camera cam1`：

| 命令 | 用途 | 示例参数 |
| --- | --- | --- |
| `preview` | SSH 连接＋开始采集＋打开页面 | `--camera cam2 --no-open` |
| `connect` | 启动空闲 API、建立隧道，不启动采集 | `--camera cam1` |
| `start` | 在已连接的实例上开始采集 | `--camera cam1 --fps 15` |
| `status` | 采集状态、帧龄、实际观察帧率及标定信息 | `--camera cam2` |
| `info` | 枚举远端相机／固件／USB／传感器 | `--profiles` 显示支持的 profiles；会列出两台 |
| `snapshot` | 在本地保存一次 RGB＋原始深度＋元数据 | `--output ./captures/example`；目标目录必须不存在 |
| `stop` | 停止指定实例采集，释放设备 | `--camera cam2` |
| `disconnect` | 关闭指定 SSH 隧道 | 不会自动停止远端采集，先运行 `stop` |
| `serve` | 远端运行 HTTP 服务 | 通常由 systemd 调用，见部署文档 |

```bash
uv run --locked camera-realsense-d435i status --camera cam1
uv run --locked camera-realsense-d435i snapshot --camera cam1
uv run --locked camera-realsense-d435i stop --camera cam1
uv run --locked camera-realsense-d435i stop --camera cam2
uv run --locked camera-realsense-d435i disconnect --camera cam1
uv run --locked camera-realsense-d435i disconnect --camera cam2
```

服务默认 640×480、15fps、JPEG 质量 80。修改参数先 `stop` 再 `start --fps …`，
不支持的 profile 会直接报错，不静默降级。`start` 不修改远端持久配置；不带参数重启时
使用远端配置文件的默认值。实例绑定序列号，不能通过请求改为另一台相机。

更换主机设置 `XCORE_CAMERA_SSH_TARGET=user@host`，或在 `preview/connect/disconnect`
后传 `--ssh-target user@host`。本地端口被占用时，所有该实例命令一致使用
`--local-port 18086`；远端端口未改时无需传 `--remote-port`。
已有 HTTP 转发可用 `status/start/stop/info/snapshot --url http://127.0.0.1:端口`。

## 数据和边界

网页 RGB 和深度预览均为 MJPEG，深度画面经过伪彩可视化。
截图目录包含 `color.jpg`、**原始 Z16 的无损 16 位 `depth.png`**、`metadata.json`。
深度米数 = PNG 像素值 × `depth_scale_m_per_unit`，0 表示无有效深度。
元数据包含原生深度／RGB 内参、深度到 RGB 外参、各流帧号、SDK 时间戳及 domain，
以及远端接收的 wall／monotonic 时间。设备时间与主机时间是不同的时钟。

深度保持原生视角，**没有对齐 RGB**；不能直接用彩色图同坐标像素取深度。
两个进程互相独立，当前没有双机硬同步，也没有相机与机械臂时间同步。
尚未实现 IMU 数据采集、连续录像、点云和机械臂数据记录集成。
预览采用最新帧，允许跳帧；这是实时查看接口，不能当作无丢帧记录接口。

## 2026-10-21 现场验证

- 远端 Ubuntu 22.04 x86_64；独立 Python 3.13 环境，pyrealsense2 2.59.1.11053、
  NumPy 2.5.4、Pillow 12.3.0。客户端 Python 3.11 不需要上述三个依赖。
- 两台相机固件 5.17.3.10，当前协商为 **USB 2.1**；未修改固件、内核或夹爪／机械臂服务。
- 两台同时 RGB8＋Z16、640×480、15fps：10 秒观测窗口每台缓存各推进 150 次，
  持续观测帧率约 15fps，无采集错误。此结果不代表其他带宽／分辨率组合已验收。
- 实际截图 RGB 为 640×480 RGB，深度 PNG 为 640×480 `uint16`，深度尺度约 0.001 m。
  当时 cam1 深度非零约 77%，cam2 约 1%；cam2 彩色画面看似贴近遮挡物，
  请检查现场镜头朝向／遮挡与被测距离。这是对画面的判断，不是已确认硬件故障。
- 已通过两台四路真实 MJPEG JPEG 帧检查、cam1 停止／重启、非法 profile 报错及恢复，
  期间 cam2 的会话保持连续；测试结束后两个相机采集均已停止，API 保持空闲。
- 离线测试覆盖单采集所有权、启停重启、构造／采集错误、无帧超时、陈旧帧拒绝、
  HTTP MJPEG、原始深度快照保存及错误请求；命令见开发文档。
- 本环境未提供可用的自动化浏览器；已验证网页 HTTP、实际 MJPEG 帧和截图，
  浏览器端页面排版及按钮点击需在用户浏览器中验收。

部署、服务日志和源码结构见 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)。
设备／profile／时间信息组织参考 [KnightOrNot/camera-realsense](https://github.com/KnightOrNot/camera-realsense)
的 `f50274f00c85ac30ca48b3f3cd076b88fc273db9`；SDK 用法参考
[RealSense Python 官方说明](https://github.com/realsenseai/librealsense/blob/master/wrappers/python/readme.md)。
