> **历史记录：**本文保留原部署／实验阶段说明，旧 IP、机器路径、compositor 参数或功能范围不代表本次默认实现。当前完整说明以[仓库首页](../README.md)、[配置](../docs/CONFIGURATION.md)和[视频](../docs/VIDEO.md)为准。代码未因本次发布改变。

# 两种整机启动方式

两种版本都包含：

1. PC1 主臂通过 Wi-Fi 和 Unitree 工控机控制从臂。
2. A2 主摄像头、Insta360 机械臂视角、腕部摄像头回传 PC1。
3. 三路画面显示在同一个可缩放窗口中。

两种版本只改变机器狗的控制来源。

## 版本一：原生遥控器直接控制狗

控制链路：

```text
原生配对遥控器 -> A2
PC1 主臂 -> Unitree -> 从臂
三路摄像头 -> Unitree -> PC1
```

启动前：

- 打开原生配对遥控器。
- 不运行 `ble_udp_sender.py`。
- 不运行狗端 `a2_network_bridge --mode receiver`。

PC1 WSL 执行：

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop

ARM_REAL_CONTROL=YES DURATION_SEC=3600 \
  ./start_stack_native_remote.sh
```

## 版本二：另一只遥控器经 PC 转发控制狗

控制链路：

```text
未与 A2 配对的 Unitree 遥控器
-> BLE
-> PC1 Windows
-> UDP/Wi-Fi
-> Unitree 工控机
-> SportClient
-> A2

PC1 主臂 -> Unitree -> 从臂
三路摄像头 -> Unitree -> PC1
```

启动前：

- 关闭与 A2 配对的原生遥控器，避免两个控制源同时控制机器狗。
- 打开 BLE 遥控器 `00:00:00:07:FC:3A`。
- 确认 Unitree 可通过 `unitree-a2-wifi` SSH 连接。
- 确认主臂、从臂和三只摄像头均已连接。

PC1 WSL 执行：

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop

ARM_REAL_CONTROL=YES A2_REAL_CONTROL=YES DURATION_SEC=3600 \
  ./start_stack_ble_pc_remote.sh
```

该入口会自动：

1. 把既有 A2 UDP 接收器部署到 Unitree。
2. 启动狗端 `SportClient` 接收控制。
3. 启动主从机械臂控制。
4. 启动三路视频和 PC1 dashboard。
5. 使用 Windows Python 连接 BLE 遥控器并发送 UDP。

默认 BLE 遥控器无 F1 门控，摇杆输入会直接映射为移动指令。150 ms 没有有效 UDP
控制包时，狗端会停止移动；程序结束时也会执行 `StopMove`。

## 端口

| 功能 | 端口 |
|---|---:|
| BLE 狗控命令 | UDP 39001 |
| BLE 狗控 ACK | UDP 39002 |
| 主从机械臂 | UDP 39101 |
| A2 主摄像头 | UDP 17200 |
| 腕部摄像头 | UDP 17201 |
| Insta360 机械臂视角 | UDP 17202 |

