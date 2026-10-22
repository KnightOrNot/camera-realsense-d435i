# 更新记录

## 2026-10-22

- 新增同一采集 pipeline 的无损 RGB／Z16 连续记录分支：`record-start/stop/status/frames`
  与 `/api/record/*`；有界队列、写盘线程和 `COMPLETE.json` 提交标记。
- `serve` 新增 `record_root`（目录白名单，留空禁用）和 `record_queue`。
- 采集帧增加无损 RGB/Z16 载荷；现有快照与预览行为不变。
- 新增记录单元测试；固定 `dev` 组包含 numpy/pillow 以便离线测试。

## 2026-10-21

- 配置参数支持放在子命令前或后；严格拒绝非法端口类型。

- 新增 `config/default.toml`、`configuration.py` 和 `--defaults`：
  默认相机、SSH 目标、端口、截图目录和 serve 主机/端口来自 TOML。
- serve 的 `--config` 仍然是每台相机的现场 JSON，部署脚本保留现场文件。
- 新增 `docs/`、`CONTRIBUTING.md` 和本文件。

## 2026-10-21（首版）

- 两台 D435i 独立实例、远端 loopback API、本地 SSH 隧道和浏览器 RGB/深度预览。
- 原始 Z16 截图与元数据；设备枚举与 profile 查询。
- 用户 unit 默认 disabled，由本地脚本按需启动。

## 早期

- 首个远程采集与预览实现。
