# Windows BLE 工具

本目录应整体放到 Windows 可访问目录，例如 `D:\unitree_ble_test`，由 Windows Python + Bleak 执行。`ble_udp_sender.py` 会导入相邻的 `ble_command_mapper.py`，不能只复制一个文件。

| 文件 | 用途 |
|---|---|
| `ble_udp_sender.py` | 手柄通知解析、A2 UDP 发送、ACK 接收、CSV |
| `ble_command_mapper.py` | 发送端控制命令映射 |
| `scan_ble.py` | 扫描周边 BLE 设备 |
| `inspect_unitree.py`、`listen_unitree.py` | 服务检查、通知监听 |
| `unitree_live_monitor.py` | 手柄实时监视 |

发送端默认端口 39001、ACK 39002、发送 50 Hz，具体启动见[使用文档](../docs/USAGE.md)。BLE 扫描／监视与实际发送会接触设备，避免多个程序同时占用同一连接。历史地址和 Windows 目录只是样例。
