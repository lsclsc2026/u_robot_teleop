# 排障与已知限制

[返回首页](../README.md) · [配置](CONFIGURATION.md)

先根据本轮日志定位异常组件。表中的操作供实际运维时使用，本次发布没有连接机器人执行排障。避免同时启动多轮入口，使旧端口、摄像头或运动锁占用掩盖实际问题。

| 现象 | 优先查看 | 处理方向 |
|---|---|---|
| `Missing Windows Python` | `WINDOWS_PYTHON` 的 WSL 路径 | 改为本机可执行 `.exe`，用同一 Windows Python 安装 bleak |
| BLE 找不到／不更新 | Windows 扫描输出、BLE 地址、蓝牙开关 | 用 `windows_ble_test/scan_ble.py` 确认实际设备；关闭其它占用 BLE 的监视器；不要用 WSL Python 代替 Windows BLE |
| BLE 已连但 ACK 为零 | Windows UDP 39002、目标 39001、PC1 来源 IP | 区分 Windows LAN 与 WSL NAT 地址，检查对端来源过滤与防火墙 |
| `TELEOP_READY` 超时 | PC1 `docker_a2_receiver_*.log`、下位机 Docker 接收日志 | 确认选中容器已经部署接收器；历史默认 unitree-dev 与新 unitree-review 不能混用；检查 SSH 和运动锁 |
| 运动锁冲突 | 关联 u_robot_move 的运行任务／持锁进程 | 正常结束导航或上一轮遥控，不删除锁文件强占 |
| 找不到主臂 | usbipd 当前 BUSID、`LEADER_PORT`、ttyACM 权限 | 重新按实际设备 attach，确认 CH343／cdc_acm 与 dialout；勿把另一台同型号串口当主臂 |
| 找不到 LeRobot Python | `$HOME/robot_ws/lerobot/.venv/bin/python` | 总入口固定此路径，采用兼容目录；export LEROBOT_PY 不能覆盖 |
| `type NameOrID` 等语法报错 | 执行主臂／从臂的 Python 版本 | 随包完整 LeRobot 需要 Python >=3.12，Windows BLE 的 3.10 环境不适用 |
| EEPROM／JSON 标定不一致 | 主从各自 JSON、串口序列号 | 选择实际设备正确标定；`so101_bus.py` 拒绝自动覆盖 EEPROM，不要用另一只臂的 JSON 规避 |
| 启动姿态差超限 | 从臂日志、主从实际姿态 | 确认姿态与映射；总入口 hard limit 80，底层独立默认 25，不能只靠放宽阈值掩盖标定问题 |
| 主画面黑屏 | 宿主机 `main_video_*.log`、eth0 组播源、17200 | 检查原视频源和转发进程；主路不做转码，原流故障不会被上位机修复 |
| Wrist not-negotiated | 宿主机 `wrist_video_*.log` | 区分 capture 支持格式、30→20 videorate、编码插件与旧残留进程 |
| D435 黑屏／零帧 | `arm_view_video_*.log`、`REALSENSE_READY`、SDK 异常 | 本版本使用 SDK RGB 分支；确认选中 RGB 节点和 `/usr/bin/python3` 下的 pyrealsense2，不只看 `/dev/video*` 是否存在 |
| `VIDEO_STALE` | 对应路接收日志与下位机发送日志 | 无新帧超过 0.75 秒会局部黑屏；观察各路计数，不能仅凭黑屏断言 USB2 或带宽不足 |
| OpenCV GUI 错误 | `/usr/bin/python3` 的 cv2 与 WSL 显示环境 | 系统 Python 需支持 GUI；LeRobot 虚拟环境中的 headless OpenCV 不代替窗口依赖 |
| 关闭窗口后臂仍跟随 | 启动终端的控制进程 | 这是当前生命周期设计；回启动终端 Ctrl+C，并在退出卸扭矩前托住从臂 |

## 日志位置与读数

PC1 WSL：`remote_teleop/logs/` 下的 `docker_a2_receiver_*`、`ble_sender_*`、`arm_video_stack_*`、`unitree_services_*`、`video_dashboard_*` 与 `arm_sender_*.csv`。Windows BLE 另写 `WINDOWS_CSV`。Unitree 宿主机：`~/arm_remote/logs/` 下的 `main_video_*`、`wrist_video_*`、`arm_view_video_*`、`arm_receiver_*`。Docker 历史日志挂载路径见[架构](ARCHITECTURE.md)。

`analyze_remote_arm_csv.py` 分析臂发送记录；`a2_joystick_lab/scripts` 中还保留网络、BLE、中继 CSV 分析工具。ACK RTT、接收器处理时间、DDS 相对延迟和视频 FPS 是不同指标，不能互相替代为绝对单向端到端延迟。

## 残留进程与部署覆盖

用实际端口、进程命令行和日志时间确定是哪轮服务占用，正常停止对应入口。宿主机视频启动器内含旧视频进程组清理逻辑；启动它会改变远端运行状态，并非只读操作。不要用全局杀进程来处理尚未确认的设备占用。

下次 PC1 启动会 scp 覆盖宿主机七个服务文件；在下位机临时修好的脚本若未同步回 PC1 会丢失。Docker 内外同名工作区也可能是不同文件，请记录实际修改位置。

## 保留但不是当前默认的材料

`dashboard_viewer.py` 是旧 compositor 读取器；Insta360 脚本与校准工具保留供维护；`remote_teleop/tests` 中部分断言仍针对旧视频参数／compositor 架构。原实验中“只读观察器”的说法只适用于相应监视程序，`network_bridge.cpp` 可以发真实运动请求。原 README 的旧帧率、网段、目录与功能阶段不能覆盖本次文档对当前代码的说明。
