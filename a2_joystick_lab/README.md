> **历史记录：**本文保留原部署／实验阶段说明，旧 IP、机器路径、compositor 参数或功能范围不代表本次默认实现。当前完整说明以[仓库首页](../README.md)、[配置](../docs/CONFIGURATION.md)和[视频](../docs/VIDEO.md)为准。代码未因本次发布改变。

# A2 Joystick Lab

## 实验任务文档

当前实验已按输入采集、单机控制、双机中继和全链路控制整理为 5 个简版 Task，入口见：

- [`docs/tasks/README.md`](docs/tasks/README.md)

根目录的 `EXPERIMENT_01.md` 至 `EXPERIMENT_04_BLE_FORWARD_CONTROL.md` 保留为详细操作记录；`docs/tasks/` 用于阶段汇报和结论归档。

这个小实验只做一件事：在工作台上接收 A2 遥控器/手柄输入，解析按钮和摇杆，并记录到达间隔与相对延迟。程序只订阅 DDS topic，不发布 `lowcmd`、`api/sport/request` 或任何运动控制指令。

## 先回答核心问题

你不一定要登录 A2 上的工控机，也不一定要把程序放到 A2 里运行；工作台可以作为外部 PC 运行订阅程序。

但你通常必须接入 A2 所在的有线网络，或者接入 A2 工控机/基础服务发布 DDS 的那张网。Unitree A2 的遥控器不是一个普通 USB/Bluetooth HID 手柄。按现有文档和 SDK，遥控器信号链路是：

```text
R3/实体遥控器 -> A2 机身接收端/基础服务 -> DDS: rt/lowstate.wireless_remote[40] -> 工作台订阅程序
```

所以，如果“只连接手柄”指完全不接 A2、只让工作台直接连遥控器本体，那么在 Unitree 官方 SDK/ROS2 路径里看不到按钮事件。工作台看到的是 A2 已经接收并转发出来的遥控器数据。

## 相关官方代码在哪里

最贴近 A2 底层数据的是：

- `/home/shuochen/宇树/04_软件服务接口/02_底层服务接口.md`
  - A2 底层状态 topic: `rt/lowstate`
  - 类型: `unitree_hg::msg::dds_::LowState_`
  - 字段: `wireless_remote[40]`
  - `tick` 是基础服务启动后的 1 ms 计数器
- `/home/shuochen/unitree_sdk2/include/unitree/dds_wrapper/common/unitree_joystick.hpp`
  - 定义 `REMOTE_DATA_RX`
  - 定义按钮 bit 位和摇杆 float 布局
- `/home/shuochen/unitree_sdk2/example/wireless_controller/main.cpp`
  - 订阅 `rt/wirelesscontroller`
  - 这是更高层的手柄消息例程，常见于 Go2/B2 等路径
- `/home/shuochen/unitree_ros2/example/src/src/read_wireless_controller.cpp`
  - ROS2 订阅 `/wirelesscontroller`
- `/home/shuochen/unitree_ros2/README _zh.md`
  - “遥控器状态获取”章节说明 `/wirelesscontroller`

对 A2，我建议第一期实验优先订阅 `rt/lowstate`，直接解析 `wireless_remote[40]`。原因是 A2 文档明确写了这个字段，而且 `LowState.tick` 能帮助做相对延迟分析。

## 本实验代码

本目录里的代码是一个只读观察器：

- `src/joystick_protocol.hpp`
- `src/joystick_protocol.cpp`
- `src/main.cpp`
- `tests/test_protocol.cpp`

解析布局来自 Unitree SDK 的 `REMOTE_DATA_RX`：

```text
byte 0..1   header
byte 2..3   uint16 buttons
byte 4..7   float lx
byte 8..11  float rx
byte 12..15 float ry
byte 16..19 float L2/占位字段
byte 20..23 float ly
byte 24..39 reserved/unused
```

按钮 bit 位：

```text
0 R1, 1 L1, 2 Start, 3 Select,
4 R2, 5 L2, 6 F1, 7 F2,
8 A, 9 B, 10 X, 11 Y,
12 Up, 13 Right, 14 Down, 15 Left
```

## WSL2 网络准备

你这台机器当前已经是 WSL2 mirrored networking，WSL 里的 `eth1` MAC 和 Windows Realtek 有线网卡一致，所以方向是对的。

需要做的是把连接 A2 的 Windows 有线网卡设到 A2 网段。A2 文档给出的机身地址是 `192.168.123.161`，工作台可用：

```text
IP: 192.168.123.200
Mask: 255.255.255.0
Gateway: 留空
DNS: 留空
```

Windows 管理员 PowerShell 示例，先确认网卡名：

```powershell
Get-NetAdapter
```

如果 A2 接在名为 `以太网` 的网卡上：

```powershell
Set-NetIPInterface -InterfaceAlias "以太网" -Dhcp Disabled
Get-NetIPAddress -InterfaceAlias "以太网" -AddressFamily IPv4 | Remove-NetIPAddress -Confirm:$false
New-NetIPAddress -InterfaceAlias "以太网" -IPAddress 192.168.123.200 -PrefixLength 24
```

然后重启 WSL 网络视图：

```powershell
wsl --shutdown
```

重新打开 WSL 后检查：

```bash
ip -brief addr show eth1
ping -c 4 192.168.123.161
```

如果 ping 通但 DDS 没数据，先检查 Windows/Hyper-V 防火墙是否拦截 UDP 组播。可以先临时关闭相关防火墙做验证；确认是防火墙后再加精确规则。

## 编译

```bash
cd /home/shuochen/a2_joystick_lab
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
```

## 运行

默认订阅 A2 文档里的 `rt/lowstate`：

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_joystick_monitor eth1 --duration 30
```

如果你只想看低频状态：

```bash
./build/a2_joystick_monitor eth1 --topic rt/lf/lowstate --duration 30
```

运行时按手柄按钮，终端会显示：

```text
seq=1234 hz=500.000 inst_hz=500.000 buttons=A edges=+A - lx=0.000 ly=0.000 rx=0.000 ry=0.000 inter_ms=2.000 rel_delay_ms=0.300 parse_us=0.900
```

CSV 默认写到：

```text
/home/shuochen/a2_joystick_lab/logs/joystick_YYYYMMDD_HHMMSS.csv
```

你也可以指定：

```bash
./build/a2_joystick_monitor eth1 --duration 60 --csv logs/my_first_remote_test.csv
```

## 延迟能测到什么

`LowState.tick` 是 A2 基础服务侧的 1 ms 计数器，不是和工作台同步过的真实时间戳。所以这里能测的是：

- DDS callback 到达间隔
- 每帧解析耗时
- `host_steady_clock - robot_tick` 的相对变化
- 相对最佳样本的额外延迟 `excess_delay_ms`

它不能直接证明“手指按下按钮到工作台收到”的绝对单向延迟。要测真正端到端，需要外部时间基准，比如高速相机、示波器/IO 触发，或手柄侧可插桩的输入事件。

## 安全提醒

这个程序本身只订阅，不控制。但实体遥控器如果仍然和 A2 绑定，A2 自带运动服务可能仍会响应手柄。第一期只做输入实验时，建议让 A2 处于安全支撑/悬空/急停可控状态，并在 App 或服务层避免运动模式接管手柄。
