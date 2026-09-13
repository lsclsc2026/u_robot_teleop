# Task 02：未配对遥控器 BLE 直连 PC

## ① 实验背景

为消除“原遥控器直接控制 A2”对转发实验的污染，改用一只未与 A2 配对的 Unitree 遥控器。目标是在 A2 不开机的情况下，由 PC 通过 BLE 直接读取遥控器数据，并确认原始轴、按钮和电量字段可用。

## ② 实验流程

```text
Unitree-34B827 遥控器
→ BLE FFE1 notify（20 字节）
→ Windows PC
→ 解析 lx/ly/rx/ry、button mask、电量
→ CSV 标定
```

先使用 BLE 扫描确认设备，再枚举 `FFE0` 服务；订阅 `FFE1` 通知，依次操作四个摇杆和全部按钮，保存为 `go2_remote_pc_only_test.csv`。

## ③ 实验结果

- BLE 连接成功，30 秒记录 911 行，平均约 30.3 Hz。
- 摇杆范围覆盖：`LX[-1.000,0.941]`、`LY[-0.797,0.870]`、`RX[-0.823,0.953]`、`RY[0,0.999]`。
- 成功识别 `A/B/X/Y`、`Start/Select`、`F1/F2`、`L1/L2/R1/R2` 和方向键。
- 电量字段稳定读取为 21%。
- BLE 通知触发 UDP 后，BLE 新样本到首次发送的典型 p50 约 `0.18～0.20 ms`。

主要数据：`D:\unitree_ble_test\go2_remote_pc_only_test.csv` 及摇杆标定 CSV。

## ④ 分析

未配对遥控器可以作为独立 PC 输入设备使用，不需要 A2 开机，也不会经过原 A2 遥控接收链路。它不是 Windows HID 手柄，而是厂商自定义 BLE GATT 数据。该阶段解决了“遥控器只向 PC 提供输入”的关键前提，并为后续 UDP 转发提供了无污染输入源。
