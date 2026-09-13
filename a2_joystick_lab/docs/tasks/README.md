# A2 遥控通信实验 Task 总览

本系列实验按“输入来源—网络范围—是否执行真机控制”划分为 5 个 Task。这样可以避免把只读采集、dry-run 通信和真实运动混为同一个结论。

| Task | 内容 | 是否控制 A2 |
| --- | --- | --- |
| [Task 01](TASK_01_LOWSTATE_INPUT.md) | 原 A2 遥控器经 `lowstate` 输入 PC，解析按钮、摇杆与相对延迟 | 否 |
| [Task 02](TASK_02_BLE_INPUT.md) | 未配对遥控器通过 BLE 直连 PC，完成输入识别与标定 | 否 |
| [Task 03](TASK_03_SINGLE_PC_CONTROL.md) | 单上位机完成 UDP 打包、解包并通过 Unitree 执行真机控制 | 是 |
| [Task 04](TASK_04_DUAL_PC_RELAY.md) | PC1 经 WiFi 到 PC2，再经网线到 Unitree 的双机 dry-run | 否 |
| [Task 05](TASK_05_DUAL_PC_CONTROL.md) | 双机中继后执行 A2 真机控制，并验证低速/高速挡位 | 是 |

统一链路如下：

```text
未配对遥控器 --BLE--> PC1 --WiFi UDP--> PC2
                              --有线 UDP--> Unitree 下位机
                              --SportClient--> A2
```

详细的早期操作记录仍保留在项目根目录的 `EXPERIMENT_01.md` 至 `EXPERIMENT_04_BLE_FORWARD_CONTROL.md`。本目录用于汇报、评审和阶段总结。
