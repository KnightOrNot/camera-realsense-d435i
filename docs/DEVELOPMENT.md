# 开发与远端部署

## 结构和运行链

```text
本地 CLI → SSH 管理用户服务＋端口转发 → 远端 loopback HTTP API
本地浏览器 → 同一转发 → MJPEG RGB／深度预览
远端每个实例：一个 SDK pipeline → 最新帧缓存 → 多个查看者／截图
```

`camera.py` 延迟导入 SDK，采集 RGB8 和原生 Z16、编码预览和无损深度；
`manager.py` 管理单采集线程、状态、超时及缓存；`server.py` 提供 HTTP；
`web.py` 是无外部资源的页面；`client.py` 仅用标准库实现 HTTP 和 SSH；`cli.py` 提供命令。
导入、帮助和本地客户端不会打开任何 USB 设备。两台独立服务显式绑定不同序列号。

API 服务只监听 `127.0.0.1`，不公开到局域网；SSH 校验已有主机指纹并采用非交互密钥登录。
先手工 `ssh rokae@192.168.2.225` 核验主机并完成密钥配置。
SSH 临时控制 socket 位于 `/tmp/camera-d435i-UID/`，权限 0700。

## 离线开发

```bash
uv sync --locked
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked camera-realsense-d435i --help
```

本地接相机开发才安装 `uv sync --locked --extra server`。
默认客户端安装没有 SDK、NumPy、Pillow，更不会影响机械臂的 SDK 环境。
`uv.lock` 和 `deploy/requirements-server.txt` 都应更新后提交：

```bash
uv lock
uv export --frozen --no-dev --extra server --no-emit-project \
  --output-file deploy/requirements-server.txt
```

## 首次部署到远端

现场项目放在 `~/project/camera-realsense-d435i/`。远端需有 Python ≥3.11 和 venv；
SDK 轮子可用性由解释器／平台决定，参考官方 [Python 安装说明](https://github.com/realsenseai/librealsense/blob/master/wrappers/python/readme.md)。
目前现场使用 `/home/rokae/miniconda3/bin/python3.13` 建立了独立 venv。
不是将依赖安装到原有 conda 或机械臂环境。

本地打包、复制（远端不要求 Git 或 uv）：

```bash
tar -czf /tmp/camera-d435i.tar.gz \
  src deploy pyproject.toml uv.lock README.md docs
scp /tmp/camera-d435i.tar.gz rokae@192.168.2.225:/tmp/
ssh rokae@192.168.2.225
```

以下在远端执行。**已有服务升级时，先用本地 `stop` 停止两个相机采集，再停止两个相机 unit，
备份旧源码；不要停止夹爪或机械臂服务。**

```bash
mkdir -p "$HOME/project/camera-realsense-d435i"
cd "$HOME/project/camera-realsense-d435i"
tar -xzf /tmp/camera-d435i.tar.gz
python3 -m venv .venv                    # 确认此 python3 >=3.11；已有 .venv 时跳过
.venv/bin/python -m pip install --only-binary=:all: --require-hashes \
  -r deploy/requirements-server.txt
.venv/bin/python deploy/install_service.py --enable
```

安装脚本生成两个明确命名的用户 unit，保留现有相机 JSON 配置，备份已有 unit 到 `.previous`，
并运行 daemon-reload。`--enable` 将空闲 API 服务设置为用户启动时自动运行；
需要无人登录也运行时，在远端执行 `sudo loginctl enable-linger "$USER"`（现场已开启）。
修改源码后，先停采集再 `systemctl --user restart camera-realsense-d435i@cam{1,2}.service`。
重复安装脚本不会重启已经运行的进程，升级后必须显式 restart。

持久配置：

```text
~/.config/camera-realsense-d435i/cam1.json
~/.config/camera-realsense-d435i/cam2.json
```

首次从 `deploy/cam1.json`／`cam2.json` 复制，目前是当前现场序列号。
换设备后在远端读取序列号并修改对应配置，不要让两个实例指向同一设备：

```bash
PYTHONPATH=src .venv/bin/python -c \
  'from camera_realsense_d435i.camera import devices; import json; print(json.dumps(devices(), indent=2))'
systemctl --user status camera-realsense-d435i@cam1.service --no-pager
journalctl --user -u camera-realsense-d435i@cam1.service -n 40 --no-pager
ss -ltn | head
```

若设备权限不足，检查 `/dev/video*`、USB 权限及当前账户访问权限，按
[官方 udev 规则](https://github.com/realsenseai/librealsense/blob/master/config/99-realsense-libusb.rules)
处理，仅重新插拔相机。不要对所有 USB 设备执行 reset／trigger，避免干扰夹爪。
当前现场普通用户已能采集，两台测试未要求安装额外内核驱动或修改权限。

## HTTP 接口

| 路径 | 方法 | 含义 |
| --- | --- | --- |
| `/` | GET | RGB＋深度网页 |
| `/api/health`、`/api/status` | GET | API 状态、采集会话、帧龄及观察帧率 |
| `/api/devices?profiles=1` | GET | SDK 设备／可用流配置枚举 |
| `/api/start` | POST JSON | `{}` 使用默认参数，可覆盖 width/height/fps/jpeg_quality |
| `/api/stop` | POST JSON | `{}` 停采集、释放 pipeline，API 留在 idle |
| `/stream/color.mjpg`、`/stream/depth.mjpg` | GET | 共享缓存的 MJPEG 流 |
| `/api/snapshot` | GET | ZIP：RGB JPEG、原始深度 PNG 和标定／时间元数据 |

启动为异步状态 starting，第一帧发布后进入 streaming；CLI 等待第一帧再返回成功。
同配置重复启动幂等；修改运行中配置必须先停采集。采集失败进入 error、清除缓存，
5 秒无新 frameset 报错；缓存超过 2 秒拒绝作为有效截图／图像发送。
故障不自动重连相机；排查设备后显式 stop/start。
HTTP status 成功只说明服务可访问，必须检查 `state`、`error`、帧龄和帧号推进。

返回元数据中的外参旋转遵循 RealSense SDK 的存储约定；使用 SDK 进行反投影／投影时，
保留畸变模型及系数。单个 frameset 中各流时间戳仍独立，不能当作严格同时曝光。
未来接入记录系统时，要设计时钟映射、逐帧保存和丢帧统计，不能轮询 JPEG 预览代替原始记录。

## 故障定位

- SSH 错误：先手工核验主机和密钥；不要关闭主机指纹校验。
- 8086/8087 已占用：检查已有 tunnel／应用；不要杀未知进程，改用 `--local-port`。
- 缺失设备或 `Couldn't resolve requests`：核实序列号、插线、支持的分辨率和 fps；
  profiles 枚举不保证共享 USB2 带宽下能同时启用任意组合。
- 页面没有有效深度：检查场景距离、遮挡和深度 PNG 的非零比例；能收到 RGB 不代表深度有效。
- 系统重启后预览不自动恢复：API 可自动启动，但采集设计为 idle；重新执行本地 `preview`。
- 关闭页面／断开 SSH 后相机仍运行：显式 `stop`；必要时远端停止对应用户 unit。

Git 提交不包含截图、venv、现场记录；远端源码升级与本地 submodule 更新是两项独立操作。
