# 实验 02：遥控器输入的网络打包、解包与反馈延迟

## 1. 实验目的

这个实验验证一条更接近后续真实系统的链路：

```text
遥控器输入
-> A2 lowstate 到工作台
-> 工作台解析 wireless_remote[40]
-> 工作台打包成 UDP 网络包
-> 接收端解包成运动指令
-> 接收端返回 ACK
-> 工作台记录反馈延迟
```

当前版本是安全 dry-run：

```text
接收端只解包并打印 dry_cmd，不向 A2 发布 lowcmd 或 sport/request。
```

也就是说，这一步测的是“网络包链路”和“反馈 ACK 延迟”，不是实际运动控制延迟。

## 2. 新增代码位置

- `src/network_packet.hpp`
  - 定义命令包和 ACK 包结构。
  - 定义摇杆到运动指令的映射。
- `src/network_packet.cpp`
  - 序列化命令包。
  - 反序列化命令包。
  - 序列化 ACK。
  - 反序列化 ACK。
- `src/network_bridge.cpp`
  - `loopback` 模式：一个进程内同时启动 sender 和 receiver。
  - `sender` 模式：订阅 A2 lowstate，解析遥控器，打包 UDP，等待 ACK。
  - `receiver` 模式：接收 UDP 包，解包成 dry-run 运动指令，并返回 ACK。
- `scripts/analyze_bridge_csv.py`
  - 分析网络桥接 CSV，输出 RTT、lowstate-to-ACK 等统计。

## 3. 摇杆到运动指令的映射

当前 dry-run 映射如下：

```text
vx       = ly * 0.5
vy       = -lx * 0.3
yaw_rate = -rx * 0.8
```

含义：

- `ly` 控制前后速度。
- `lx` 控制横向速度。
- `rx` 控制偏航角速度。
- 小于 0.05 的摇杆输入会被当作 0，作为死区。

这些只是 dry-run 指令，不会直接控制机器人。

## 4. 编译

```bash
cd /home/shuochen/a2_joystick_lab
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
```

## 5. 单进程 loopback 测试

这是当前最推荐的第一步。

它会在一个进程内：

- 订阅 `rt/lowstate`；
- 解析遥控器；
- 发送 UDP 包到 `127.0.0.1:39001`；
- 内部 receiver 解包；
- receiver 回 ACK 到 `127.0.0.1:39002`；
- sender 记录 ACK 延迟到 CSV。

运行：

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_network_bridge --mode loopback --interface eth1 --duration 20 --csv logs/network_loopback.csv
```

运行期间可以轻轻拨动摇杆、按 A/B/X/Y。

分析：

```bash
python3 scripts/analyze_bridge_csv.py logs/network_loopback.csv
```

## 6. 两进程测试

终端 1：启动 receiver。

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_network_bridge --mode receiver --listen 0.0.0.0 --port 39001 --ack-target 127.0.0.1 --ack-port 39002
```

终端 2：启动 sender。

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_network_bridge --mode sender --interface eth1 --target 127.0.0.1 --port 39001 --ack-port 39002 --duration 20 --csv logs/network_two_process.csv
```

分析：

```bash
python3 scripts/analyze_bridge_csv.py logs/network_two_process.csv
```

## 7. CSV 字段

`a2_network_bridge` 的 CSV 包含：

- `seq`
  - 网络命令包序号。
- `host_unix_ns`
  - 写入 CSV 时的系统时间。
- `send_steady_ns`
  - sender 发 UDP 包时的 steady clock 时间。
- `lowstate_arrival_steady_ns`
  - 对应 lowstate 样本到达工作台时的 steady clock 时间。
- `robot_tick_ms`
  - A2 lowstate 中的 tick。
- `ack_arrival_steady_ns`
  - sender 收到 ACK 时的 steady clock 时间。
- `rtt_ms`
  - UDP 命令包发送到 ACK 返回的往返时间。
- `lowstate_to_ack_ms`
  - lowstate 到达工作台到 ACK 返回的时间。
- `receiver_oneway_ms_same_clock`
  - receiver 收到包时间减 sender 发包时间。只有 sender 和 receiver 在同一台机器时才有意义。
- `buttons`、`pressed`
  - 遥控器按钮状态。
- `lx/ly/rx/ry`
  - 摇杆值。
- `vx/vy/yaw_rate`
  - dry-run 运动指令。

## 8. 如何理解状态反馈延迟

当前有两个可观察延迟：

```text
rtt_ms = UDP 包发送 -> receiver 解包 -> ACK 回到 sender 的往返时间
```

```text
lowstate_to_ack_ms = lowstate 到达工作台 -> 解析 -> 打包 -> UDP -> 解包 -> ACK 回到工作台
```

如果 sender 和 receiver 都在同一台工作台上，`receiver_oneway_ms_same_clock` 可以粗略看单向解包到达时间。

如果 receiver 将来放到 A2 工控机或另一台机器上，机器之间没有严格时钟同步时，不要把 `receiver_oneway_ms_same_clock` 当成可靠单向延迟；应优先看 `rtt_ms`。

## 9. 后续接入真实运动控制的位置

真实运动控制不应该直接塞进 sender。

建议结构是：

```text
sender: 只负责遥控器解析和网络打包
receiver: 解包后生成 dry_cmd
controller: 明确开启后，才把 dry_cmd 转成 A2 sport/lowcmd
```

下一步如果要真正控制机器狗，建议加一个显式开关，例如：

```text
--enable-robot-command
```

没有这个开关时，receiver 永远只 dry-run。
