# 实验 04：未绑定遥控器经 PC1 与 Unitree 转发控制 A2

## 目标

建立以下唯一控制链路：

```text
未与 A2 配对的 Unitree 遥控器
-> BLE
-> PC1（解析原始轴/按键、原 A2 比例映射、UDP 打包）
-> 以太网 UDP
-> Unitree（校验、解包、失联保护）
-> A2 SportClient::Move/StopMove
-> A2 ai_sport
```

原 A2 遥控器在真实测试前应关机，避免与 PC 转发链路同时控制。
不要调用 `ReleaseMode` 或静默模式，A2 保持正常 `ai_sport` 服务。

## 已实现部分

- 新遥控器 BLE 地址：`00:00:00:07:FC:3A`。
- PC1：`D:\unitree_ble_test\ble_udp_sender.py`。
- Unitree 地址：`192.168.123.162`，A2 工控机地址：`192.168.123.161`。
- UDP 指令端口 `39001`，ACK 端口 `39002`。
- Unitree 执行器：`~/a2_joystick_lab/bin/a2_network_bridge`。
- 新遥控器采用无按键门控，沿用原 A2 SDK 映射：`vx=LY*0.5`、`vy=-LX*0.3`、`yaw=-RX*0.8`。
- BLE 新通知立即触发 UDP 发送；`--send-hz 50` 是无新数据时的心跳频率，不再额外等待固定周期。
- Unitree 接收端按文档复现 A2 按键组合，并通过官方 `SportClient` 执行。
- 启动及失联恢复后必须先检测到摇杆回中，才允许发送非零运动。
- Unitree 仅接受来自 `192.168.123.200` 的指令。
- UDP 150 ms 失联时调用 `StopMove`，恢复后必须先让摇杆回中才能重新使能。
- 摇杆值变化时立即调用运动接口，不等待周期节流；正常回中发送一次零速度，只有通信失联或程序退出才调用 `StopMove`。
- 重复或倒序序号被拒绝，非有限浮点值被拒绝。

## 安全 dry-run

在 Unitree 执行：

```bash
DURATION_SEC=45 ~/a2_joystick_lab/bin/run_unitree_receiver_dry.sh
```

此模式不初始化 SportClient，不会控制机器人。

## 原生比例真实测试

现场条件：A2 正常站立、原 A2 遥控器关机、四周清空、急停可触达。先启动接收端：

```bash
A2_REAL_CONTROL=YES DURATION_SEC=15 \
  ~/a2_joystick_lab/bin/run_unitree_receiver_control.sh
```

随后在 PC1 Windows PowerShell 启动 10 秒低速发送：

```powershell
cd D:\unitree_ble_test
python .\ble_udp_sender.py `
  --address "00:00:00:07:FC:3A" `
  --target "192.168.123.162" `
  --duration 10 `
  --send-hz 50 `
  --no-deadman `
  --csv .\go2_to_a2_native_motion.csv
```

操作顺序：启动时保持所有摇杆回中；按一次 `Start` 恢复默认步态；之后只轻推左摇杆一个方向约 0.5 秒并立即回中。首次验证不要测试特殊动作。

预期：

- Unitree 中 `ret=0` 表示 A2 接受高层运动调用。
- `robot_sent=1` 只在当前帧实际调用非零 `Move` 时出现。
- 摇杆回中、UDP 中断或程序结束都会调用 `StopMove`。

## PC1 结果分析

```bash
python3 /home/shuochen/a2_joystick_lab/scripts/analyze_ble_udp_csv.py \
  /mnt/d/unitree_ble_test/go2_to_a2_native_motion.csv
```

重点检查：`missing_inside_range=0`、`nonzero_without_required_enable=0`，以及真实控制期间 `robot_ack_flags` 大于 0。

## A2 文档映射与边界

- `L2+B` 阻尼；`L2+A` 首次锁定站立、再次卧倒；`Start` 解除锁定并恢复默认步态。
- `L2+Start` 跑步；双击 `X/Y` 左/右侧步；`L2+X` 恢复站立；`R1+X` 攀爬。
- `L1+Up/Down` 调整机身高度；`Up/Down` 调整速度挡位；`Y+B` 切换自动翻身。
- 双击 `R1/R2`、`L1+X/Y` 已识别为倒立、直立、前/后空翻，但默认阻止执行。只有接收端额外设置 `A2_NATIVE_SPECIAL_ACTIONS=YES` 才放行。
- 三击 `F1` 蜂鸣器没有公开的 A2 `SportClient` 接口，只记录为不支持，不会伪造调用。
- 这是基于官方公开接口的行为兼容层；厂商固件内部未公开的互锁、动作时序无法做到二进制级透明转发。
