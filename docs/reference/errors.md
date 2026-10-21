# 故障排查

## 无法连接本地端口

`Connection refused` 表示 SSH 隧道或远端 API 未建立。先运行：

```bash
./scripts/start_camera.sh --camera cam1 preview --no-open
```

preview/connect 会按需启动远端 unit。检查 `systemctl --user status
camera-realsense-d435i@cam1.service`。

## SSH 失败

确认 `XCORE_CAMERA_SSH_TARGET`、密钥和网络。隧道关闭不应停止采集；
停止采集请用 `stop` 或顶层 `stop_camera.sh`。

## 设备未找到

- 远端 `lsusb` 应能看到两台 Intel 435i。
- `info --profiles` 只枚举，不打开流。
- JSON 中的 `serial` 必须与设备一致；多设备时必须显式序列号。

## profile 不支持

先 `info --profiles` 查看设备实际支持的组合。USB 2.0 连接可能无法维持
更高分辨率/帧率。两台相机共用 Hub 时带宽共享。

## 画面冻结或帧号回退

设备断开、SDK 时间域变化或主机时钟跳变都会使当前 session 失效。
重新 `stop` 后 `start`；不要复用旧帧或把接收时间当成曝光时间。

## 截图内容不符预期

`color.jpg` 是当前 JPEG 质量编码，不是无损 RGB；`depth.png` 才是原始 Z16。
深度伪彩预览不能用于测量。没有对齐时 RGB 与深度像素不一一对应。

## 服务重启后配置丢失

安装脚本不会覆盖 `~/.config/camera-realsense-d435i/*.json`。如果 JSON 被
删除，按实际序列号和 profile 重新创建；不要用仓库默认值覆盖现场配置。
