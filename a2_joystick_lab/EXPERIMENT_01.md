# 实验 01：在工作台接收并解析 A2 实体遥控器输入

实验日期：2026-07-13

## 1. 实验目的

本实验只研究 A2 实体遥控器的输入链路，不控制机器人运动。

目标是：

- 在 WSL2 工作台上接收 A2 发布的 DDS `rt/lowstate` 数据。
- 从 `LowState_.wireless_remote()[40]` 中解析实体遥控器按钮和摇杆。
- 记录每帧到达时间、解析耗时、到达间隔和相对延迟。
- 生成 CSV，便于后续做延迟和抖动分析。

本实验程序是只读订阅程序，不发布 `rt/lowcmd`、`api/sport/request` 或任何运动控制指令。

## 2. 这个延迟调查代码是不是自己写的

是的，这套“遥控器输入解析 + CSV 记录 + 相对延迟统计”的代码是本次实验中新写的本地代码。

它不是 Unitree 官方现成的延迟测试工具，但底层通信使用的是 Unitree SDK2：

- `unitree_hg::msg::dds_::LowState_`
- `unitree::robot::ChannelFactory`
- `unitree::robot::ChannelSubscriber`

也就是说：

```text
Unitree SDK2 负责 DDS 通信
本实验代码负责解析 wireless_remote[40]、打时间戳、写 CSV、输出统计
```

## 3. 主要代码位置

项目目录：

```text
/home/shuochen/a2_joystick_lab
```

主要文件：

- `src/main.cpp`
  - 初始化 DDS。
  - 订阅 `rt/lowstate`。
  - 在 callback 到达时记录工作台时间戳。
  - 读取 `LowState_.wireless_remote()[40]`。
  - 写入 CSV。
  - 输出 `interarrival_ms`、`relative_delay_ms`、`parse_us` 的 p50/p95/p99。
- `src/joystick_protocol.hpp`
  - 定义按钮名称。
  - 定义解析后的遥控器状态结构。
  - 定义相对延迟估计器。
- `src/joystick_protocol.cpp`
  - 解析 40 字节遥控器原始数据。
  - 解码按钮 bit 位。
  - 解码摇杆 float 数值。
  - 根据 A2 的 `LowState.tick` 计算相对延迟。
- `tests/test_protocol.cpp`
  - 测试按钮 bit 解析。
  - 测试摇杆 float 解析。
  - 测试 tick wrap 情况。

## 4. 官方依据

本实验使用的 A2 官方文档位置：

```text
/home/shuochen/宇树/04_软件服务接口/02_底层服务接口.md
```

文档中说明：

- A2 当前状态通过 DDS topic `rt/lowstate` 获取。
- 数据类型是 `unitree_hg::msg::dds_::LowState_`。
- `LowState_` 中包含 `wireless_remote[40]`，这是宇树实体遥控器原始数据。
- `tick` 是 Basic Service 启动后按 1 ms 递增的计数。

SDK 中遥控器原始数据结构参考：

```text
/home/shuochen/unitree_sdk2/include/unitree/dds_wrapper/common/unitree_joystick.hpp
```

其中定义了：

- `REMOTE_DATA_RX`
- `BtnUnion`
- 按钮 bit 位
- 摇杆 float 布局

## 5. 实验连接方式

实际连接链路：

```text
A2 PC1 Ethernet
-> Unitree 航插网口转换器
-> RJ45 网线
-> 工作台 Realtek 有线网口
-> WSL2 eth1
```

这里有一个重要结论：

```text
工作台不是直接连接遥控器本体。
工作台是通过 A2 的 DDS lowstate 数据看到遥控器输入。
```

也就是：

```text
实体遥控器 -> A2 接收端 / Basic Service -> DDS rt/lowstate -> 工作台程序
```

## 6. 网络配置

Windows 有线网卡：

```text
网卡名：以太网
IP：192.168.123.200
PrefixLength：24
网关：留空
DNS：留空
状态：Up
链路速度：1 Gbps
```

WSL2 中看到的接口：

```text
eth1 UP 192.168.123.200/24
```

连通性测试命令：

```bash
ping -c 4 192.168.123.161
```

测试结果：

```text
4 packets transmitted, 4 received, 0% packet loss
rtt min/avg/max/mdev = 0.507/0.836/1.317/0.334 ms
```

说明 WSL2 工作台已经能访问 A2 的 PC1 网络。

## 7. 编译和测试指令

```bash
cd /home/shuochen/a2_joystick_lab
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
```

测试结果：

```text
100% tests passed, 0 tests failed out of 1
```

## 8. 实验指令整理

### 8.1 初次确认 DDS 是否通

```bash
cd /home/shuochen/a2_joystick_lab
./build/a2_joystick_monitor eth1 --duration 30
```

观察到 `seq` 持续增长，说明工作台已经收到 `rt/lowstate`。

### 8.2 按钮和摇杆解析测试

运行：

```bash
./build/a2_joystick_monitor eth1 --duration 10 --csv logs/press_test.csv
```

实验中按下 `A/B/X/Y`，并轻轻拨动摇杆。

查看发生变化的行：

```bash
grep ',1,' logs/press_test.csv | head
```

### 8.3 空闲 baseline 测试

运行：

```bash
./build/a2_joystick_monitor eth1 --duration 10 --csv logs/no_touch_test.csv
```

实验期间不触碰遥控器。

### 8.4 A 键重复按压测试

运行：

```bash
./build/a2_joystick_monitor eth1 --duration 20 --csv logs/a_button_10x.csv
```

实验期间约每 1 秒短按一次 `A`。

提取 A 键按下事件：

```bash
grep '"A","A",""' logs/a_button_10x.csv | head -20
```

提取 A 键事件行号、序号、时间戳和相对延迟：

```bash
awk -F, '/"A","A",""/ {print NR, $1, $2, $8}' logs/a_button_10x.csv
```

## 9. 实验数据文件

本次实验产生的数据文件：

- `logs/press_test.csv`
  - 大小约 2.2 MB。
  - 用于验证 `A/B/X/Y` 和摇杆是否能被解析。
- `logs/no_touch_test.csv`
  - 大小约 2.2 MB。
  - 用于空闲 baseline。
- `logs/a_button_10x.csv`
  - 大小约 4.4 MB。
  - 用于 A 键重复按压事件分析。

## 10. 遥控器解析结果

从 `press_test.csv` 中观察到按钮事件：

```text
0x0100,"A","A",""
0x0200,"B","B",""
0x0800,"Y","Y",""
0x0400,"X","X",""
```

含义：

- 第一列 `0x0100` 等是按钮 bit mask。
- 第二个字段 `"A"` 表示当前按下的按钮。
- 第三个字段 `"A"` 表示本帧出现 A 键按下边沿。
- 第四个字段为空，表示本帧没有释放边沿。

终端中观察到摇杆值变化：

```text
lx=-1.000
rx=0.904
ly=-0.875
ry=-1.000
```

说明按钮和摇杆都已经通过 A2 的 `wireless_remote[40]` 被工作台成功解析。

## 11. 空闲 baseline 数据

命令：

```bash
./build/a2_joystick_monitor eth1 --duration 10 --csv logs/no_touch_test.csv
```

结果：

```text
samples: 10606
interarrival ms p50/p95/p99: 0.920 / 1.586 / 5.264
relative delay ms p50/p95/p99: 0.554 / 3.355 / 6.229
parse us p50/p95/p99: 0.060 / 0.189 / 0.288
```

解释：

- 10 秒内收到 10606 帧，约等于 1.06 kHz。
- `interarrival_ms` 中位数约 0.920 ms，说明 `rt/lowstate` 基本是 1 kHz 量级。
- `parse_us` 的 p99 只有 0.288 us，说明遥控器字段解析本身几乎不耗时。
- 空闲状态下的相对延迟 p99 为 6.229 ms。

## 12. A 键重复按压数据

命令：

```bash
./build/a2_joystick_monitor eth1 --duration 20 --csv logs/a_button_10x.csv
```

结果：

```text
samples: 21191
interarrival ms p50/p95/p99: 0.915 / 1.602 / 5.805
relative delay ms p50/p95/p99: 2.215 / 9.631 / 12.243
parse us p50/p95/p99: 0.060 / 0.154 / 0.240
```

提取到 12 次 A 键按下事件：

```text
CSV行号  seq    host_unix_ns          relative_delay_ms
1528     1527   1783924702888499286   0.876
2559     2558   1783924703858375254   1.990
3485     3484   1783924704740106192   3.723
4476     4475   1783924705683272296   5.888
5444     5443   1783924706604624588   7.240
6455     6454   1783924707566666909   9.282
7508     7507   1783924708565963111   8.576
8560     8559   1783924709542046259   0.000
9634     9633   1783924710538578595   0.164
10666    10665  1783924711511756604   1.896
11718    11717  1783924712513825355   3.964
12792    12791  1783924713532722540   2.857
```

解释：

- 20 秒内收到 21191 帧，仍然约为 1.06 kHz。
- A 键按下事件被捕获了 12 次。
- A 键事件所在帧的 `relative_delay_ms` 范围是 0.000 ms 到 9.282 ms。
- 整个 20 秒实验中，`relative_delay_ms` 的 p99 是 12.243 ms。
- 解析耗时 p99 是 0.240 us，说明解析代码不是延迟瓶颈。

## 13. 关于 relative_delay_ms 的含义

`relative_delay_ms` 不是“手指按下按键到工作台收到”的绝对延迟。

原因是：

- A2 的 `LowState.tick` 是机器人侧 Basic Service 的 1 ms 计数器。
- 工作台本地时钟和 A2 的 tick 没有做严格同步。
- 本实验代码计算的是 `host_steady_clock - robot_tick`，然后减去本次实验中观察到的最小 offset。

因此：

```text
relative_delay_ms = 相对本次实验最佳样本的额外延迟
```

它适合用来观察 DDS、WSL2、网络和系统调度带来的相对抖动。

如果要测真正的“手指按下 -> 工作台收到”的绝对端到端延迟，需要额外时间基准，例如：

- 高速相机；
- 示波器 / IO 触发；
- 可插桩的遥控器输入硬件。

## 14. 实验结论

本次第一期实验成功。

已经验证的链路：

```text
A2 实体遥控器
-> A2 接收端 / Basic Service
-> DDS rt/lowstate
-> WSL2 工作台
-> wireless_remote[40] 解析
-> CSV 和统计输出
```

已经确认：

- 工作台可以通过有线 PC1 网络接收 A2 的 `rt/lowstate`。
- 工作台可以解析实体遥控器按钮。
- 工作台可以解析实体遥控器摇杆。
- A/B/X/Y 按键都能在 CSV 中看到。
- 摇杆 `lx/ly/rx/ry` 数值能在终端和 CSV 中看到。
- `rt/lowstate` 接收频率约 1.06 kHz。
- 遥控器解析代码的耗时是微秒以下量级，不是主要延迟来源。
- 本实验观察到的主要抖动来自 DDS、WSL2、网络和系统调度。

一句话总结：

```text
工作台已经可以稳定接收并解析 A2 实体遥控器输入；本实验完成了“只看遥控器输入、不控制机器人”的最小闭环。
```

## 15. 下一步建议

建议下一步写一个 CSV 自动分析脚本，输入任意一次实验 CSV，输出：

- 按键按下/释放事件表；
- 每次事件的时间戳；
- 相邻按键事件间隔；
- 每个按钮的出现次数；
- `interarrival_ms`、`relative_delay_ms`、`parse_us` 的统计摘要。

这样之后做第二期实验时，不需要手动 `grep` 和 `awk`。
