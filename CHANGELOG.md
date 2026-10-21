# 更新记录

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
