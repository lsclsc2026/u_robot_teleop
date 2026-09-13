# Task 03：单上位机 UDP 转发与 A2 真机控制

## ① 实验背景

在完成 BLE 输入后，需要验证单个上位机能否将遥控器输入映射为运动指令、打包为 UDP，并由 Unitree 下位机解包后调用 A2 `SportClient`。这里的“单机”指只有一个外部上位机 PC1；Unitree 下位机仍负责执行 SDK 调用。

## ② 实验流程

```text
未配对遥控器 → BLE → PC1
→ 原始轴/按钮解析 → 68 字节 UDP 指令包
→ Unitree 下位机解包
→ SportClient::Move / 动作接口
→ A2 → 48 字节 ACK 返回 PC1
```

先进行 loopback/dry-run，确认序列化、解包和 ACK；随后显式开启 `--enable-robot-command`，验证移动、回中停止、`Start`、`L2+A` 等映射。UDP 失联 150 ms 时执行 `StopMove`。

## ③ 实验结果

- 连续运动测试 99 个 ACK：UDP RTT p50/p95/p99 为 `2.237/3.430/8.306 ms`。
- 原生映射测试 2949 包连续，无丢包、无重复。
- BLE→首次发送 p50 `0.192 ms`；正常 UDP RTT p50 `1.097 ms`。
- 632 个非零指令包中，532 帧实际调用移动 API。
- `Start` 与 `L2+A` 能触发动作；6 次动作 ACK 中 3 次返回 `3104`。

主要数据：`go2_to_a2_native_motion_v3.csv`、`logs/real_forward_move_test_r1_slow.csv`。

## ④ 分析

单上位机真机控制链路已经打通，连续移动的典型延迟约为 1～3 ms。长尾不是 UDP 网络导致，而是姿态动作的同步 `SportClient` 调用发生 2 秒 DDS 超时，阻塞了接收线程。该问题对持续移动的体感影响较小，但说明后续应将 UDP 接收与耗时动作执行分线程，并只执行最新运动帧。
