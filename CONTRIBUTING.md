# 贡献与开发检查

## 规则

- 本地客户端只用标准库，不导入 `pyrealsense2`；导入、`--help` 和状态查询
  不得隐式打开本机相机。
- 默认值写入 `config/default.toml`；现场 JSON 和截图目录不进入 Git。
- 远端 HTTP 只绑定 loopback；不要为了方便改成 `0.0.0.0`。
- 一个远端实例只允许一个 pipeline；多查看者共享缓存。
- 预览伪彩图与原始 Z16 语义不能混用；截图元数据必须保留深度尺度、内参、
  外参、帧号、时间戳和时间域。

## 检查

```bash
uv run --project camera-realsense-d435i --with pytest --with ruff pytest -q
uv run --project camera-realsense-d435i --with ruff ruff check src tests
```

离线测试覆盖启动/停止、异常传播、原始深度格式和双机选择；真实帧率、
USB 模式和页面交互需要现场验收并写入 README。

## 提交

不提交 `captures/`、`.venv`、远端现场 JSON 或密码/密钥。
