# 设备专用标定备份

[返回首页](../README.md) · [配置说明](../docs/CONFIGURATION.md)

本目录 `aloha_leader.json` 是原 PC1 的 **SO-101 主臂**标定，来源设备串口序列号为 **`5B3D047743`**，历史 by-id 为 `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047743-if00`。不是通用参数，也不是从臂标定。

原 PC1 使用路径：`~/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json`。只有确认仍是同一设备、关节、电机 ID、零点和 EEPROM 标定状态时，才可把备份用于恢复；换电机、改零点或重新标定后需采用该设备新的记录。

另一个保留文件是 [历史从臂标定](../remote_teleop/calibration_export/aloha_follower.json)，它在 PC1 上为串口序列号 **`5B3D047726`** 的 SO-101 从臂生成。历史导出说明见 [README.txt](../remote_teleop/calibration_export/README.txt)。该文件不能自动视为当前 Unitree 宿主机的有效标定，不能用来覆盖主臂，也不能跨设备使用。

历史从臂目标路径：`~/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json`。当前适配器会核对 EEPROM 与 JSON，发现不一致时拒绝自动改写。仓库中的 JSON 备份不包含对当前硬件状态的保证；标定工具会操作电机配置，不属于纯文件检查。
