# A2 遥操作与三路视频交接

日期：2026-09-13。本文件按当前磁盘代码与下位机路径整理。

## 1. 当前状态与边界

- 已有功能：未配对宇树手柄经 Windows BLE、UDP 控制 A2；PC1 主臂经 UDP 控制狗上从臂；三路视频返回 PC1。
- 机器狗运动接收器已迁入 Docker `unitree-dev`。机械臂与摄像头服务目前仍运行在 Unitree **宿主机**，不是全部搬入 Docker。
- 本次视频修改：腕部补齐 30→20 FPS 转换；D435i 切换为官方 RealSense SDK 采集；PC1 三路独立解码、各保留最新帧，界面按 20 FPS 刷新。
- 最新视频代码已写入 PC1，并部署相关发送脚本到 Unitree。已做语法、BGR 帧长度和 SDK 支持格式检查；**最新版本三路同时实机运行的帧率、端到端延迟尚未完成验收**。不能将界面刷新率当成摄像头实际帧率。
- 本次没有改 BLE 协议、机器狗轴映射或机械臂关节映射。用户此前确认运动及主从控制可运行。
- 视频故障按单路降级；机械臂初始化失败等关键控制错误仍可能使组合启动器退出，不能宣称任意设备掉线都不影响全流程。

## 2. 两端联动

```text
未配对手柄 → PC1 Windows/Bleak → UDP 39001
  → Unitree host 网络 → Docker unitree-dev/a2_network_bridge
  → SportClient → eth0 → A2
  ← ACK 回 PC1 Windows UDP 39002

主臂 → USBIP/PC1 WSL → pc1_leader_sender.py → UDP 39101
  → Unitree 宿主机 unitree_follower_receiver.py → 从臂串口

A2 主摄像头组播 → Unitree 宿主机转发 → PC1 UDP 17200
腕部 Microdia → MJPEG采集/降帧/H.264编码 → PC1 UDP 17201
D435i RGB → RealSense SDK/H.264编码 → PC1 UDP 17202
  → dashboard_latest.py 三个独立解码进程 → 一个可缩放窗口
```

SSH 用于部署、启动和生命周期管理；持续运动指令与视频经 UDP 传输，不经 VS Code 窗口转发。

## 3. 当前网络与设备

| 项目 | 当前值 |
|---|---|
| Unitree SSH 别名 | `unitree-a2-wifi`，用户 `unitree` |
| Unitree 无线 IP | `172.18.21.114` |
| PC1 Windows/镜像网络 WSL IP | `172.18.21.246` |
| Unitree 内网接口 | `net1=192.168.124.162`、`eth0=192.168.123.162` |
| BLE 手柄地址 | `00:00:00:07:FC:3A` |
| PC1 主臂 | 当前 `/dev/ttyACM0`；原序列号 `5B3D047743` |
| 从臂 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B3D047726-if00` |
| 腕部 | Microdia `0c45:64ab`，启动器自动检测 capture 节点 |
| 第三摄像头 | RealSense D435i `8086:0b3a` |
| 本次 D435 RGB 路径 | `/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4.1.1:1.3-video-index0` |

IP、USB BUSID、ttyACM 编号和 by-path 路径可能随机器、网络、拓展坞接口变化。by-path 标识物理连接位置；更换接口后需要重新确认。

## 4. PC1 上位机代码位置

主目录：`/home/shuochen/feishu/a2pro/local_arm_test/remote_teleop`

| 文件/路径 | 职责 |
|---|---|
| `start_stack_ble_pc_remote.sh` | 版本2总入口：Docker狗接收器、机械臂/视频、Windows BLE发送器 |
| `start_stack_native_remote.sh` | 版本1总入口：原配手柄直接控狗，脚本只启动机械臂/视频 |
| `pc1_ble_docker.py` | SSH调用宿主机Docker入口，等待 `TELEOP_READY`，维护SSH心跳 |
| `launch_pc1_operation.sh` | 部署宿主机脚本，启动远端机械臂/视频、PC1窗口与主臂发送器 |
| `pc1_leader_sender.py` | 读取主臂关节，发送UDP并记录ACK/CSV |
| `arm_udp_protocol.py`、`so101_bus.py` | 手臂协议和Feetech串口访问 |
| `video_dashboard.sh` | 当前窗口入口，直接执行 `dashboard_latest.py` |
| `dashboard_latest.py` | 当前三路独立解码/最新帧显示实现 |
| `dashboard_viewer.py` | 旧的单一合成画布读取器，保留但新入口不调用 |
| `unitree_*.sh`、`unitree_*.py` | PC1保存的下位机部署源文件；修改后下次启动会复制到Unitree |
| `analyze_remote_arm_csv.py` | 机械臂CSV分析 |
| `logs/` | PC1本地运行日志及机械臂CSV |

另有：

- Windows BLE脚本：`D:\unitree_ble_test\ble_udp_sender.py`，WSL对应 `/mnt/d/unitree_ble_test/ble_udp_sender.py`。
- Windows Python默认：`C:\Users\47487\AppData\Local\Programs\Python\Python310\python.exe`。新PC可用 `WINDOWS_PYTHON` 覆盖其 `/mnt/c/.../python.exe` 路径。
- Windows脚本路径可用 `WINDOWS_BLE_SCRIPT` 覆盖；应传 Windows 路径。
- 原始摇杆工程：`/home/shuochen/a2_joystick_lab`，含 `src/network_bridge.cpp`、协议、按钮映射、CMake与CSV分析脚本。
- LeRobot：`/home/shuochen/robot_ws/lerobot`；运行解释器 `.venv/bin/python`。
- 主臂标定：`/home/shuochen/.cache/huggingface/lerobot/calibration/teleoperators/so_leader/aloha_leader.json`。
- LeRobot基准提交：`7de2e4c1efb27d7d678947349dba0d81b61205d0`。本地 `motors_bus.py`、`so_follower.py` 有修改，压缩包保留当前源码，不能只按提交重新拉取替代。

## 5. Unitree 下位机代码位置

### 宿主机

- 机械臂/视频运行目录：`/home/unitree/arm_remote/`。
- 总服务：`unitree_launch_services.sh`。
- 机械臂：`unitree_follower_receiver.py`、`so101_bus.py`、`arm_udp_protocol.py`；使用 `~/arm_remote/.venv/bin/python`，精简LeRobot源码位于 `~/arm_remote/lerobot_src/`。
- 第三摄像头入口：`unitree_uvc_camera_sender.sh`。识别选定节点属于 D435i 后，执行 `unitree_realsense_sender.py`；其他设备保留UVC/FFmpeg分支。
- RealSense使用 `/usr/bin/python3`、`gi/GStreamer`、`numpy`、`pyrealsense2`。此机需要兼容 `from pyrealsense2 import pyrealsense2 as rs` 的模块布局。
- 宿主机日志：`/home/unitree/arm_remote/logs/`。
- 从臂标定：`/home/unitree/.cache/huggingface/lerobot/calibration/robots/so_follower/aloha_follower.json`。以实际设备标定为准，不要直接用主臂标定覆盖。
- Docker运动入口：`/home/unitree/unitree_robot_development/u_robot_move/scripts/run_teleop_docker.sh`。
- Docker部署脚本：同目录下 `scripts/deploy_teleop_docker.sh`；详细说明 `docs/teleop.md`。
- 历史非Docker接收器保留于 `/home/unitree/a2_joystick_lab/bin/`，当前组合入口不启动它。

### Docker `unitree-dev`

- 工作区：`/home/unitree/unitree_robot_development/u_robot_move`。**与宿主机同名路径是两份文件**，不能假定修改一份会自动同步另一份。
- 运行二进制：`install/u_robot_teleop/lib/u_robot_teleop/a2_network_bridge`。
- 配置与监督：`src/u_robot_teleop/config/teleop.yaml`、`scripts/teleop_runtime.py`、`scripts/teleop_receiver.py`。
- Docker使用host网络。日志挂载：宿主机 `/home/unitree/unitree-data/logs` ↔ 容器 `/home/unitree/data/logs`。
- 遥控和真实导航共用运动锁，不能同时占用控制。出现锁冲突应定位持锁进程，不要通过删除锁文件强行接管。
- 迁移时接收器使用原部署二进制；本次没有导入C++并重编译。原件SHA256：`985f9d035418756e0f342919e5324a62a892dd5c1a1acb1408f86bafea7bd276`（来自迁移记录，本次未重新核对容器二进制）。

## 6. 启动命令

在PC1 WSL执行。先结束上一轮，避免设备重复占用。

### 非配对手柄 + 机械臂 + 三路视频

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop

LEADER_PORT=/dev/ttyACM0 \
ARM_REAL_CONTROL=YES \
A2_REAL_CONTROL=YES \
DURATION_SEC=3600 \
UNITREE_HOST="unitree-a2-wifi" \
UNITREE_WIFI_IP="172.18.21.114" \
PC1_WIFI_IP="172.18.21.246" \
BLE_ADDRESS="00:00:00:07:FC:3A" \
ARM_VIEW_MODE="uvc" \
ARM_VIEW_DEVICE="/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4.1.1:1.3-video-index0" \
./start_stack_ble_pc_remote.sh
```

此版本按现有设计要求关闭原配手柄，避免双控制源。

### 原配手柄 + 机械臂 + 三路视频

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop

LEADER_PORT=/dev/ttyACM0 \
ARM_REAL_CONTROL=YES \
DURATION_SEC=3600 \
UNITREE_HOST="unitree-a2-wifi" \
UNITREE_WIFI_IP="172.18.21.114" \
PC1_IP="172.18.21.246" \
ARM_VIEW_MODE="uvc" \
ARM_VIEW_DEVICE="/dev/v4l/by-path/pci-0000:00:14.0-usb-0:4.1.1:1.3-video-index0" \
./start_stack_native_remote.sh
```

两个入口不要同时运行。`Ctrl+C`结束整套流程；窗口 `q`/Esc关闭的是视频窗口，控制可以继续。

`DURATION_SEC`当前必须是正整数，`3600`是一小时；`0`不是总入口的无限运行选项。

## 7. 视频参数和修复依据

| 画面 | 采集/发送方式 | 网络输出 |
|---|---|---|
| Main | `230.1.1.1:1720`，eth0组播原H.264透传 | 分辨率/帧率/码率由狗原始视频源决定；当前未转码降带宽 |
| Wrist | MJPEG 1280×720@30，videorate降帧、缩放、x264 | 480×270@20，目标700 kbps，PT96 |
| Arm/D435i | SDK仅采RGB 640×360@30，单帧队列、appsrc、x264 | 480×270@20，目标800 kbps，PT97 |

码率为编码目标，不是严格的UDP流量上限。新窗口1280×480，左848×480，右上下各432×240；宽度按BGR行对齐处理。

- 每路独立GStreamer进程及读取线程，不使用原来的共享compositor时间轴。
- 每路只保存最新解码帧，UI按20 FPS读取快照。日志每5秒输出 `VIDEO_FPS Main=... Arm=... Wrist=...`，它表示解码到达率，不是玻璃到玻璃延迟。
- 超过0.75秒无新解码帧，对应区域黑屏并输出 `WARNING VIDEO_STALE`；恢复后输出 `VIDEO_OK`。
- D435 SDK内部队列和GStreamer appsrc均限制为单帧，编码前允许丢旧帧；SDK异常会记录警告并重试。
- Unitree视频任务使用独立进程组退出清理；UVC旧分支的timeout改为foreground，避免逃出清理进程组。

已观察到的问题：旧任务残留占摄像头、重复主视频转发；腕部30→20转换缺少videorate导致not-negotiated；D435 V4L2路径存在0字节帧；旧合成窗口测得约10 FPS。

注意：当时约2 Mbps接收、socket零积压/零丢包，不能由此完全排除无线抖动、空口丢包或编码前掉帧；约10 FPS也不足以单独证明compositor是唯一原因。新架构提供逐路计数，后续应根据实际FPS继续判断。

## 8. 迁移前置条件

1. Windows安装Python和Bleak，确认 `WINDOWS_PYTHON` 指向本机路径。Windows BLE依赖不随WSL镜像自动迁移。
2. Windows安装usbipd，运行 `usbipd list`，按当前主臂BUSID执行 `usbipd bind --busid <BUSID>`（首次管理员），再 `usbipd attach --wsl --busid <BUSID>`。不要固定沿用历史7-1。
3. WSL确认主臂可读写、用户串口权限；如缺驱动可加载 `cdc_acm`。仅适配CH343设备，勿将其他串口误当主臂。
4. WSL SSH配置 `unitree-a2-wifi` 使用当前IP与本机私钥，确认 `ssh -o BatchMode=yes unitree-a2-wifi hostname` 成功。压缩包不包含私钥或密码。
5. WSL系统Python需要OpenCV/NumPy；GStreamer需要RTP、H.264解析/软件解码、色彩转换和缩放插件。此版本不依赖OpenCV的GStreamer后端。
6. 机械臂需要恢复LeRobot依赖环境及实际设备标定。源码压缩包不能代替虚拟环境、USB驱动和电机EEPROM标定。
7. Windows防火墙/WSL镜像网络需允许Unitree返回的UDP视频17200–17202及对应控制ACK。PC1地址应填能接收回流的LAN地址。

## 9. 日志与排障入口

```bash
cd /home/shuochen/feishu/a2pro/local_arm_test/remote_teleop
tail -n 60 "$(ls -t logs/video_dashboard_*.log | head -1)"
tail -n 60 "$(ls -t logs/unitree_services_*.log | head -1)"
python3 analyze_remote_arm_csv.py "$(ls -t logs/arm_sender_*.csv | head -1)"
```

下位机在 `~/arm_remote/logs/` 中按最新运行时间找 `main_video_*`、`wrist_video_*`、`arm_view_video_*`。`REALSENSE_READY`表示SDK初始化完成，`REALSENSE_PUSH_FPS`表示送编码器帧率。先看对应一路日志，不要仅凭黑屏判断USB模式或带宽。

旧tests目录一并归档，其中部分测试仍按旧compositor/旧参数设计，最新独立显示架构未完成全套测试适配；不宣称这些测试全量通过。

## 10. 压缩包内容、恢复与回滚

配套包：`../pc1_teleop_handoff_20260913.tar.gz`，解压后顶层为 `pc1_teleop_handoff_20260913/`。

- `remote_teleop/`：当前上位机入口、下位机部署源文件、分析/标定工具、文档、历史测试和calibration_export。
- `windows_ble_test/`：Windows BLE发送器及可用的扫描/监视工具。
- `a2_joystick_lab/`：当前PC1原始摇杆C++源码、构建配置、脚本和文档，供Docker源码导入使用。
- `lerobot/`：当前修改后的LeRobot源码、项目依赖说明和锁文件。
- `calibration/aloha_leader.json`：当前PC1主臂标定备份，仅用于相应设备。`remote_teleop/calibration_export`是历史导出，不能自动视为当前狗端标定。
- `MANIFEST.sha256`：包内文件校验值。

不包含：`.venv`、`.git`、编译产物、摄像头录像、历史日志/CSV、历史压缩包、SSH私钥、Docker镜像和Unitree SDK依赖。部署完整新下位机仍需单独准备Docker运行包及宿主机环境。

```bash
tar -xzf pc1_teleop_handoff_20260913.tar.gz
cd pc1_teleop_handoff_20260913
sha256sum -c MANIFEST.sha256
```

恢复时先备份目标目录，再将 `remote_teleop/` 放到本机工作目录，将 `windows_ble_test/` 放到Windows脚本路径；按第8节配置环境。LeRobot与主臂标定按上文路径分别恢复，勿盲目覆盖另一套设备的标定。

已有修改前备份位于原remote_teleop目录：

- `backup_video_before_latency_fix_20260913_161005.tar.gz`
- `backup_video_independent_20260913_163200.tar.gz`

回滚需停止本轮，恢复PC1对应文件，再通过入口部署到Unitree；仅回滚下位机文件，下次启动可能又被PC1版本覆盖。

## 11. 下一位维护者

先阅读本文，确认IP、串口、RGB设备及最新日志。保持狗控制与视频任务边界，优先依据每路实际FPS判断问题。完整验收需记录三路解码FPS、SDK供帧FPS和实际端到端延迟，并确认掉一路后另外两路及控制仍可用。未经验证不要把配置20 FPS写成实测20 FPS。
