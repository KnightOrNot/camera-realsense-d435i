# 采集、预览与截图

## 流

每台相机一个 pipeline，提供：

- RGB（JPEG/MJPEG 预览）。
- 深度伪彩 JPEG（仅预览）。
- 原始 Z16 深度（截图）。
- 设备信息、profile、内参、外参和深度尺度。

多个浏览器共享同一份最新帧缓存；订阅者断开不影响采集。

## API

HTTP 只绑定 `127.0.0.1`。主要路由：

| 路由 | 用途 |
| --- | --- |
| `/api/start` | 打开采集；可覆盖 width/height/fps/jpeg_quality |
| `/api/stop` | 停止采集，释放设备 |
| `/api/status` | 当前状态、帧计数和错误 |
| `/api/devices` | 设备信息；`profiles=1` 时枚举 profile |
| `/api/snapshot` | 返回 zip：RGB JPEG、原始 Z16 PNG 和元数据 |
| `/api/record/start` | 在唯一 pipeline 上开始无损 RGB/Z16 连续记录 |
| `/api/record/stop` | 结束记录，写 `COMPLETE.json` |
| `/api/record/status` | 记录状态、持久化帧数、队列和错误 |
| `/api/record/frames` | 已落盘帧索引（`after`、`limit`） |
| `/api/health` | 与 status 相同的健康检查 |
| `/stream/color.mjpg` | RGB MJPEG |
| `/stream/depth.mjpg` | 深度伪彩 MJPEG |

## 截图

本地 `snapshot` 下载并解压到：

```text
captures/<camera>/<timestamp>/
├── color.jpg        # 当前 JPEG 质量（默认 80），不是无损原图
├── depth.png        # uint16 Z16，原生视角，无损
└── metadata.json    # 内参、外参、深度尺度、帧号、时间戳
```

`depth.png` 的零值表示无效深度；真实距离为 `raw * depth_scale`。
RGB 截图复用预览编码；训练数据使用 `record-start` 的无损 RGB PNG，
它在 JPEG 编码前保存原始数组，并与 Z16 深度、帧号和时间戳一起写入帧索引。

## 时间

每一帧保留 SDK 时间戳、timestamp domain 和主机接收时间。设备时间与主机
monotonic 时间不得混用；当前实现不做双机硬同步。

## 边界

- 关闭网页不会停止采集。
- `stop` 只停止采集，API 保留 idle；`stop_camera.sh` 停止 API。
- 断流、设备拔出和写盘失败会作为错误返回，不静默复用旧帧。
