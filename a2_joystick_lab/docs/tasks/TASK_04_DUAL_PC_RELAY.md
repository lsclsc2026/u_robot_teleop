# Task 04：PC1—PC2 双机 UDP 中继通信

## ① 实验背景

实际部署需要 PC1 连接遥控器，PC2 同时连接 WiFi 和 A2 有线网络。因此先在不控制机器狗的情况下，验证 PC1→PC2→Unitree 的双网卡中继、打包解包和 ACK 返回链路。

## ② 实验流程

```text
遥控器 → BLE → PC1 172.18.21.232
→ WiFi UDP → PC2 172.18.20.130
→ pc2_udp_relay.py
→ PC2 有线 192.168.123.200
→ Unitree 192.168.123.162 dry-run receiver
→ ACK 原路返回 PC1
```

PC2 只校验 68 字节命令包、记录时间并原样转发；Unitree 使用 dry-run 接收端，不初始化 `SportClient`。

## ③ 实验结果

- PC1 收到 1944 个连续 ACK，无内部缺失和重复。
- 端到端 UDP RTT p50/p95/p99：`17.770/61.193/220.754 ms`。
- PC2 中继处理 p50/p95/p99：`70.050/118.600/170.500 μs`。
- PC2→Unitree 有线 ACK p50/p95/p99：`0.799/1.274/1.390 ms`。
- dry-run 中 `robot_move_ack_flags=0`，机器狗未收到运动调用。

对应数据：PC1 `pc1_wifi_pc2_unitree_dry_v1.csv`，PC2 `pc1_to_unitree_dry_v1.csv`。

## ④ 分析

双机中继功能正确，PC2 转发耗时仅几十微秒，有线段约 1 ms，不是主要瓶颈。端到端长尾主要位于 PC1—PC2 WiFi 往返及 Windows 调度。该 Task 只证明通信链路可用；`robot_move_ack_flags=0` 是安全 dry-run 的预期结果，不能据此判断真机是否能移动。
