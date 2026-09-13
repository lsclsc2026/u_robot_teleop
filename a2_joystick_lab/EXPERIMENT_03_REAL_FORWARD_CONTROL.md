# 实验 03：遥控器经 PC 转发后真实控制 A2 运动

## 1. 实验目标

本实验在阶段二的网络桥接基础上，增加真实运动控制：

```text
实体遥控器
-> A2 lowstate
-> PC 解析 wireless_remote[40]
-> PC 打包 UDP 指令
-> receiver 解包
-> receiver 调用 A2 SportClient::Move/StopMove
-> A2 真实运动
-> receiver 返回 ACK
-> PC 记录延迟
```

这里的关键变化是：

```text
阶段二：receiver 只 dry-run 打印 dry_cmd
阶段三：receiver 可以在显式授权后调用 A2 SportClient 控制真实运动
```

## 2. 安全设计

真实控制默认关闭。

必须显式加入：

```text
--enable-robot-command
```

才会调用 A2 高层运动接口。

同时，程序强制使用 deadman 按键，当前默认是 `F1`：

```text
按住 F1：允许把摇杆映射成 Move(vx, vy, vyaw)
松开 F1：发送 StopMove()
```

也可以通过参数指定其他已知按键：

```text
--deadman-button F1
```

当前 SDK 原始键位中明确包含 `F1`、`F2`，没有明确的 `F3` 位。不要再使用 R1 做 deadman，因为 R1 可能触发 A2 原生危险动作。

速度也做了二次限幅：

```text
vx       限制到 ±0.25 m/s
vy       限制到 ±0.15 m/s
yaw_rate 限制到 ±0.40 rad/s
```

所以第一次测试时，请务必：

- 让 A2 在空旷地面；
- 人站在安全位置；
- 急停可触达；
- 先短时间、低幅度拨动摇杆；
- 全程按住 deadman 键才移动，松开立即停。

## 3. 重要实验污染点

A2 内置高层运动服务本身可能也响应实体遥控器。

因此在阶段三里，如果你直接拨动实体遥控器，A2 可能同时受到两条链路影响：

```text
链路 A：实体遥控器 -> A2 内置遥控控制
链路 B：实体遥控器 -> PC -> UDP 转发 -> SportClient::Move
```

这会污染“PC 转发控制延迟”的测量。

如果要严格验证“只经过 PC 转发”的控制效果，需要找到并关闭 A2 对实体遥控器的直接运动响应，或者让遥控器输入只作为 PC 侧采样源。当前代码侧已经完成 PC 转发链路，但直接遥控链路是否关闭，需要结合 A2 运动服务配置进一步确认。

## 4. 编译

```bash
cd /home/shuochen/a2_joystick_lab
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
```

## 5. 推荐第一步：只验证 StopMove

先不让 A2 移动，只确认真实控制接口能调用成功。

运行：

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_network_bridge \
  --mode loopback \
  --interface eth1 \
  --duration 5 \
  --csv logs/real_forward_stop_test.csv \
  --enable-robot-command
```

这个测试中不要按 deadman 键，不要拨摇杆。

预期：

- receiver 输出 `ROBOT COMMAND ENABLED`。
- `robot_sent=0`。
- ACK CSV 中 `robot_command_sent=0`。
- `ack_result` 应该大多为 0，表示 `StopMove()` 调用成功。

分析：

```bash
python3 scripts/analyze_bridge_csv.py logs/real_forward_stop_test.csv
```

## 6. 第二步：短时间真实移动测试

确保安全后再运行：

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_network_bridge \
  --mode loopback \
  --interface eth1 \
  --duration 10 \
  --send-hz 50 \
  --command-hz 10 \
  --deadman-button F1 \
  --csv logs/real_forward_move_test.csv \
  --enable-robot-command
```

操作方式：

- 按住 F1。
- 轻轻拨动左摇杆或右摇杆。
- 松开 F1，A2 应停止。

分析：

```bash
python3 scripts/analyze_bridge_csv.py logs/real_forward_move_test.csv
```

## 7. CSV 新增字段

阶段三 CSV 在阶段二基础上增加：

- `ack_result`
  - receiver 调用 `Move()` 或 `StopMove()` 的返回码。
  - 0 表示 SDK 调用成功。
- `ack_flags`
  - ACK 标志位。
- `robot_command_sent`
  - 1 表示本帧 receiver 调用了 `Move()`。
  - 0 表示本帧没有发 `Move()`，通常是 StopMove 或节流。

## 8. 延迟如何理解

阶段三中：

```text
rtt_ms
```

包含：

```text
UDP 发包 -> receiver 解包 -> SportClient 调用返回 -> ACK 返回 PC
```

因此它比阶段二更接近“PC 转发控制链路反馈延迟”。

但注意：这仍然不是“狗身体真实开始运动”的物理延迟。真实运动响应还包含 A2 内部运动服务调度、状态机响应、执行器响应和机体动力学。

## 9. 下一步

如果本实验能稳定运行，下一步建议增加高层状态反馈订阅，例如订阅 A2 高层状态中的速度信息，记录：

```text
PC 发 Move 的时间
-> A2 高层状态速度开始变化的时间
```

这样才能进一步估计“指令转发到机器人状态响应”的延迟。
