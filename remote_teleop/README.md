> **历史记录：**本文保留原部署／实验阶段说明，旧 IP、机器路径、compositor 参数或功能范围不代表本次默认实现。当前完整说明以[仓库首页](../README.md)、[配置](../docs/CONFIGURATION.md)和[视频](../docs/VIDEO.md)为准。代码未因本次发布改变。

# SO-101：PC1 主臂经 Unitree 工控机控制从臂

两种完整启动方式（原生遥控器版、BLE 遥控器经 PC 转发版）见：

- [START_TWO_CONTROL_VERSIONS.md](START_TWO_CONTROL_VERSIONS.md)

## 数据链路

```text
SO-101 Leader（PC1 USB）
  -> PC1 读取并使用主臂校准文件转换为六关节标准位置
  -> UDP/CRC/序号（WiFi，最新指令优先）
  -> Unitree 工控机解包
  -> 使用从臂自己的校准文件转换并写入 CH343 串口
  -> SO-101 Follower
```

网络层不重新设计关节映射：六个字段直接沿用 LeRobot 的
`shoulder_pan/shoulder_lift/elbow_flex/wrist_flex/wrist_roll/gripper`。

## 安全机制

- 接收端默认是 dry-run，只有同时使用 `--enable-motors` 和环境变量
  `ARM_REAL_CONTROL=YES` 才会打开从臂串口。
- CRC、协议版本、来源 IP 和递增序号均通过后才接受指令。
- WiFi 堵塞时丢弃旧帧，只执行最新目标，不重传过期动作。
- 启动时若主从姿态在硬安全范围内，从臂以限定速度平滑同步到主臂姿态，再自动进入实时跟随；超过硬上限才拒绝启动。
- 250 ms 没有新包时停止写入新目标，从臂伺服保持最后目标。
- 默认退出时关闭从臂扭矩；退出前必须用手托住从臂。

## 端口

- PC1 主臂：`5B3D047743`
- Unitree 从臂：`5B3D047726`
- Unitree WiFi：`172.18.20.152`
- UDP：`39101`

具体部署及实验命令见主文档后续记录。

## 一键联合启动

PC1 脚本同时编排以下三条链路：

1. A2 主摄像头 RTP/H.264：Unitree `eth0` 接收后经 WiFi 转发至 PC1。
2. PC1 主臂目标：UDP 发往 Unitree，dry-run 或写入从臂。
3. Unitree 腕部 UVC 摄像头：低延迟档默认 1280×720@20 FPS，经 zerolatency H.264/RTP/UDP
   转发至 PC1；三路模式默认码率 1400 kbps，接收端抖动缓冲 5 ms，并主动丢弃过期帧。
4. Intel RealSense D435i RGB 机械臂全景：默认 960×540@20 FPS、900 kbps，
   经独立 H.264/RTP/UDP 端口 17202 转发至 PC1；当前只读取 RGB，不开启深度流。

PC1 不再创建三个独立裸窗口，而是用 GStreamer compositor 合成后交给 OpenCV/Qt
显示为一个可缩放窗口。左侧为 1280×720 主摄像头，右上为 640×360 臂部摄像头，
右下为 640×360 腕部摄像头。各支路仅保留最新一帧，避免播放积压画面。

第一次先做 30 秒 dry-run：

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop
./launch_pc1_operation.sh --duration 30
```

该模式显示两路真实视频，也读取和发送真实主臂数据，但不打开从臂串口。

确认主从初始姿态接近、从臂区域清空并准备好断开 12 V 电源后，才运行真实控制：

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop
ARM_REAL_CONTROL=YES ./launch_pc1_operation.sh --enable-arm --duration 3600 --fps 100
```

腕部视频参数可以按网络情况调整：

```bash
ARM_REAL_CONTROL=YES ./launch_pc1_operation.sh \
  --enable-arm --duration 3600 --fps 100 \
  --max-relative-target 8.0 --startup-max-delta 80 \
  --startup-sync-tolerance 2 \
  --wrist-fps 20 --wrist-bitrate-kbps 1400 --wrist-jitter-ms 3
  --arm-view-fps 20 --arm-view-bitrate-kbps 900 --arm-view-jitter-ms 3
```

若开始出现花屏或跳帧，可将 `--wrist-jitter-ms` 恢复到 `20`。

任一服务提前退出或用户按一次 `Ctrl+C`，PC1 会结束本地发送端和两个视频窗口，
SSH 远端脚本也会结束视频转发与从臂接收端。默认从臂接收端退出时关闭扭矩，
因此退出前必须用手托住从臂。
